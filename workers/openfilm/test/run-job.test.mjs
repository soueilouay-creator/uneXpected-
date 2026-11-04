import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import test from "node:test";

import { encodeEvent, executeJob, parseRequest, RunnerError } from "../run-job.mjs";

async function workspace() {
  const base = await mkdtemp(path.join(os.tmpdir(), "openfilm-runner-"));
  const projectRoot = path.join(base, "project");
  const artifactRoot = path.join(base, "artifacts");
  const attemptRoot = path.join(artifactRoot, "job-1", "attempt-1");
  await mkdir(projectRoot, { recursive: true });
  await mkdir(attemptRoot, { recursive: true });
  await writeFile(path.join(projectRoot, "film.html"), "<!doctype html><html><body>synthetic</body></html>");
  const request = {
    job_id: "job-1",
    project_root: projectRoot,
    entrypoint: "film.html",
    artifact_root: artifactRoot,
    attempt_root: attemptRoot,
    output_path: path.join(attemptRoot, "master.mp4"),
    max_output_bytes: 50_000_000,
    profile: {
      platform: "youtube_shorts",
      width: 1080,
      height: 1920,
      fps: 30,
      audio_required: true
    }
  };
  return { base, projectRoot, artifactRoot, attemptRoot, request };
}

test("parseRequest accepts one bounded, in-root portrait render request", async (t) => {
  const w = await workspace();
  t.after(() => rm(w.base, { recursive: true, force: true }));
  const parsed = await parseRequest(w.request);
  assert.equal(parsed.jobId, "job-1");
  assert.equal(parsed.profile.platform, "youtube_shorts");
  assert.equal(parsed.projectFile, path.join(w.projectRoot, "film.html"));
  assert.equal(parsed.outputPath, w.request.output_path);
});

test("parseRequest rejects unknown fields, traversal, absolute entrypoint, and profile mismatch", async (t) => {
  const w = await workspace();
  t.after(() => rm(w.base, { recursive: true, force: true }));
  await assert.rejects(() => parseRequest({ ...w.request, shell: "echo unsafe" }), RunnerError);
  await assert.rejects(() => parseRequest({ ...w.request, entrypoint: "../other/film.html" }), RunnerError);
  await assert.rejects(() => parseRequest({ ...w.request, entrypoint: path.join(w.projectRoot, "film.html") }), RunnerError);
  await assert.rejects(() => parseRequest({
    ...w.request,
    profile: { ...w.request.profile, width: 720 }
  }), RunnerError);
});

test("parseRequest rejects output outside the attempt directory and overwrites", async (t) => {
  const w = await workspace();
  t.after(() => rm(w.base, { recursive: true, force: true }));
  await assert.rejects(() => parseRequest({
    ...w.request,
    output_path: path.join(w.artifactRoot, "outside.mp4")
  }), RunnerError);
  await writeFile(w.request.output_path, "existing-artifact");
  await assert.rejects(() => parseRequest(w.request), RunnerError);
});

test("failed OpenFilm look blocks rendering and returns bounded diagnostics", async (t) => {
  const w = await workspace();
  t.after(() => rm(w.base, { recursive: true, force: true }));
  let renders = 0;
  const result = await executeJob(w.request, {
    look: async () => ({ ok: false, lines: ["film 1080×1920", "✗ missing sound: voice.wav"], files: [] }),
    render: async () => { renders += 1; return { out: w.request.output_path }; }
  });
  assert.equal(result.status, "qa_blocked");
  assert.equal(result.failure_category, "openfilm_look_failed");
  assert.equal(renders, 0);
  assert.ok(result.diagnostics.length <= 20);
});

test("successful look validates variant dimensions before rendering", async (t) => {
  const w = await workspace();
  t.after(() => rm(w.base, { recursive: true, force: true }));
  let renders = 0;
  const result = await executeJob(w.request, {
    look: async () => ({ ok: true, lines: ["film 1920×1080 · 10s · 0 sounds"], files: [] }),
    render: async () => { renders += 1; return { out: w.request.output_path }; }
  });
  assert.equal(result.status, "qa_blocked");
  assert.equal(result.failure_category, "variant_dimensions_mismatch");
  assert.equal(renders, 0);
});

test("successful look renders exactly once to unique requested output and returns hash", async (t) => {
  const w = await workspace();
  t.after(() => rm(w.base, { recursive: true, force: true }));
  const calls = [];
  const bytes = Buffer.from("synthetic-mp4-fixture");
  const result = await executeJob(w.request, {
    look: async (args, opts) => {
      calls.push(["look", args, opts]);
      return { ok: true, lines: ["film 1080×1920 · 10s · 1 sound"], files: [] };
    },
    render: async (args, opts) => {
      calls.push(["render", args, opts]);
      await writeFile(opts.out, bytes, { flag: "wx" });
      return { out: opts.out, lines: ["rendered"] };
    }
  });
  assert.equal(result.status, "rendered");
  assert.equal(result.output_size, bytes.length);
  assert.equal(result.output_sha256, createHash("sha256").update(bytes).digest("hex"));
  assert.equal(calls.filter(call => call[0] === "render").length, 1);
  assert.equal(calls[1][2].out, w.request.output_path);
  assert.equal(calls[1][2].workers, 1);
  assert.equal(calls[1][2].hardware, false);
  assert.equal((await readFile(w.request.output_path)).length, bytes.length);
});

test("renderer output mismatch fails and never substitutes a different artifact", async (t) => {
  const w = await workspace();
  t.after(() => rm(w.base, { recursive: true, force: true }));
  await assert.rejects(() => executeJob(w.request, {
    look: async () => ({ ok: true, lines: ["film 1080×1920 · 10s · 1 sound"], files: [] }),
    render: async () => ({ out: path.join(w.attemptRoot, "wrong.mp4"), lines: [] })
  }), RunnerError);
});

test("executeJob emits the newline-delimited events required by the host worker", async (t) => {
  const w = await workspace();
  t.after(() => rm(w.base, { recursive: true, force: true }));
  const events = [];
  const result = await executeJob(w.request, {
    emit: (event) => events.push(event),
    look: async () => ({ ok: true, lines: ["film 1080×1920 · 10s · 1 sound"], files: [] }),
    render: async (_args, opts) => {
      await writeFile(opts.out, Buffer.from("synthetic-mp4"), { flag: "wx" });
      return { out: opts.out, lines: ["rendered"] };
    }
  });
  assert.equal(result.status, "rendered");
  assert.deepEqual(events, [
    { event: "phase", phase: "inspecting" },
    { event: "phase", phase: "rendering" },
    { event: "result", result }
  ]);
  assert.equal(
    encodeEvent(events[0]),
    '{"event":"phase","phase":"inspecting"}' + String.fromCharCode(10)
  );
});
