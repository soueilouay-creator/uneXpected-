import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { lstat, realpath, stat } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { look as openFilmLook } from "openfilm/look";
import { render as openFilmRender } from "openfilm/render";

const OPENFILM_VERSION = "0.2.7";
const MAX_REQUEST_BYTES = 32 * 1024;
const MAX_DIAGNOSTIC_LINES = 20;
const MAX_DIAGNOSTIC_LINE_BYTES = 500;

export class RunnerError extends Error {
  constructor(message, code = "invalid_request") {
    super(message);
    this.name = "RunnerError";
    this.code = code;
  }
}

export function encodeEvent(event) {
  if (!event || typeof event !== "object" || Array.isArray(event)) {
    throw new RunnerError("Worker event must be a JSON object.");
  }
  const encoded = JSON.stringify(event);
  if (typeof encoded !== "string" || Buffer.byteLength(encoded, "utf8") > 16 * 1024) {
    throw new RunnerError("Worker event exceeded the fixed output byte limit.", "result_too_large");
  }
  return encoded + String.fromCharCode(10);
}

function requireString(value, name, maxLength = 1024) {
  if (typeof value !== "string" || !value.trim() || value.length > maxLength || value.includes("\0")) {
    throw new RunnerError(`${name} must be a non-empty string no longer than ${maxLength} characters.`);
  }
  return value;
}

async function requireRealDirectory(value, name) {
  requireString(value, name);
  if (!path.isAbsolute(value) || path.resolve(value) !== value) {
    throw new RunnerError(`${name} must be a normalized absolute path.`);
  }
  let details;
  try { details = await lstat(value); } catch { throw new RunnerError(`${name} does not exist.`); }
  if (!details.isDirectory() || details.isSymbolicLink()) {
    throw new RunnerError(`${name} must be a real directory, not a symlink.`);
  }
  return realpath(value);
}

function isWithin(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative !== "" && relative !== ".." && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}

export async function parseRequest(value) {
  const allowed = new Set([
    "job_id", "project_root", "entrypoint", "artifact_root",
    "attempt_root", "output_path", "profile", "max_output_bytes"
  ]);
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new RunnerError("Request must be a JSON object.");
  }
  if (Object.keys(value).some((key) => !allowed.has(key)) ||
      [...allowed].some((key) => !Object.hasOwn(value, key))) {
    throw new RunnerError("Request fields do not match the fixed runner contract.");
  }

  const jobId = requireString(value.job_id, "job_id", 128);
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(jobId)) {
    throw new RunnerError("job_id contains unsupported characters.");
  }
  const projectRoot = await requireRealDirectory(value.project_root, "project_root");
  const artifactRoot = await requireRealDirectory(value.artifact_root, "artifact_root");
  const attemptRoot = await requireRealDirectory(value.attempt_root, "attempt_root");
  if (!isWithin(artifactRoot, attemptRoot)) {
    throw new RunnerError("attempt_root must be inside artifact_root.");
  }

  const entrypoint = requireString(value.entrypoint, "entrypoint", 1024);
  if (path.isAbsolute(entrypoint) || entrypoint.includes("\\") ||
      entrypoint.split("/").some((part) => !part || part === "." || part === ".." || part.startsWith("."))) {
    throw new RunnerError("entrypoint must be a safe project-relative path.");
  }
  if (entrypoint !== "film.html") {
    throw new RunnerError("The OpenFilm entrypoint must be the project film.html file.");
  }
  const projectFile = path.resolve(projectRoot, entrypoint);
  let entryStats;
  try {
    entryStats = await lstat(projectFile);
    const actual = await realpath(projectFile);
    if (entryStats.isSymbolicLink() || !entryStats.isFile() || actual !== projectFile || !isWithin(projectRoot, actual)) {
      throw new RunnerError("Project entrypoint must be a regular file inside project_root.");
    }
  } catch (error) {
    if (error instanceof RunnerError) throw error;
    throw new RunnerError("Project film.html does not exist as a regular file.");
  }

  const outputPath = requireString(value.output_path, "output_path");
  if (!path.isAbsolute(outputPath) || path.resolve(outputPath) !== outputPath ||
      path.dirname(outputPath) !== attemptRoot || path.extname(outputPath).toLowerCase() !== ".mp4") {
    throw new RunnerError("output_path must be a new .mp4 file directly inside attempt_root.");
  }
  try {
    await lstat(outputPath);
    throw new RunnerError("output_path already exists; the runner never overwrites artifacts.");
  } catch (error) {
    if (error instanceof RunnerError) throw error;
    if (error?.code !== "ENOENT") throw new RunnerError("output_path could not be safely inspected.");
  }

  const profile = value.profile;
  const profileFields = new Set(["platform", "width", "height", "fps", "audio_required", "captions_required"]);
  if (!profile || typeof profile !== "object" || Array.isArray(profile) ||
      Object.keys(profile).some((key) => !profileFields.has(key)) ||
      ["platform", "width", "height", "fps", "audio_required"].some((key) => !Object.hasOwn(profile, key))) {
    throw new RunnerError("profile requires platform, width, height, fps and audio_required; captions_required is optional.");
  }
  const dimensions = {
    youtube_shorts: [1080, 1920],
    tiktok: [1080, 1920],
    youtube_long: [1920, 1080]
  };
  const expected = dimensions[profile.platform];
  if (!expected || profile.width !== expected[0] || profile.height !== expected[1] ||
      !Number.isFinite(profile.fps) || profile.fps < 1 || profile.fps > 60 ||
      typeof profile.audio_required !== "boolean" ||
      (Object.hasOwn(profile, "captions_required") && typeof profile.captions_required !== "boolean")) {
    throw new RunnerError("profile does not match a supported platform render variant.");
  }
  if (!Number.isSafeInteger(value.max_output_bytes) || value.max_output_bytes < 1) {
    throw new RunnerError("max_output_bytes must be a positive, host-supplied integer.");
  }
  return {
    jobId, projectRoot, entrypoint, projectFile, artifactRoot,
    attemptRoot, outputPath, profile: { ...profile },
    maxOutputBytes: value.max_output_bytes
  };
}

function diagnostics(lines, roots) {
  const replacements = roots.map((root) => [root, "<job-path>"]).filter(([root]) => root);
  return (Array.isArray(lines) ? lines : [])
    .slice(0, MAX_DIAGNOSTIC_LINES)
    .map((line) => {
      let text = String(line);
      for (const [root, replacement] of replacements) text = text.split(root).join(replacement);
      return Buffer.from(text, "utf8").subarray(0, MAX_DIAGNOSTIC_LINE_BYTES).toString("utf8");
    });
}

function dimensionsFromLook(lines) {
  for (const line of Array.isArray(lines) ? lines : []) {
    const match = String(line).match(/(?:film\s+)?(\d{2,5})×(\d{2,5})/);
    if (match) return [Number(match[1]), Number(match[2])];
  }
  return null;
}

async function sha256File(file) {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(file)) hash.update(chunk);
  return hash.digest("hex");
}

export async function executeJob(value, api = { look: openFilmLook, render: openFilmRender }) {
  const request = await parseRequest(value);
  const emit = typeof api.emit === "function" ? api.emit : () => {};
  const finish = (result) => {
    emit({ event: "result", result });
    return result;
  };
  emit({ event: "phase", phase: "inspecting" });
  const inspected = await api.look([request.entrypoint], {
    root: request.projectRoot,
    offline: true,
    network: { allow: [] },
    count: 12
  });
  const inspectedLines = diagnostics(inspected?.lines, [request.projectRoot, request.artifactRoot]);
  if (!inspected || inspected.ok !== true) {
    return finish({
      status: "qa_blocked",
      job_id: request.jobId,
      failure_category: "openfilm_look_failed",
      diagnostics: inspectedLines
    });
  }
  const dimensions = dimensionsFromLook(inspected.lines);
  if (!dimensions || dimensions[0] !== request.profile.width || dimensions[1] !== request.profile.height) {
    return finish({
      status: "qa_blocked",
      job_id: request.jobId,
      failure_category: "variant_dimensions_mismatch",
      diagnostics: inspectedLines
    });
  }
  if (request.profile.audio_required && !/\b[1-9]\d* sounds?\b/i.test(inspectedLines[0] ?? "")) {
    return finish({
      status: "qa_blocked",
      job_id: request.jobId,
      failure_category: "required_audio_missing",
      diagnostics: inspectedLines
    });
  }

  emit({ event: "phase", phase: "rendering" });
  // Network denial is enforced by the worker's host container, not by OpenFilm's render() options.
  const rendered = await api.render([request.entrypoint], {
    root: request.projectRoot,
    out: request.outputPath,
    fps: request.profile.fps,
    workers: 1,
    hardware: false,
    samples: 1,
    subtitles: request.profile.captions_required === true
  });
  if (!rendered || path.resolve(String(rendered.out ?? "")) !== request.outputPath) {
    throw new RunnerError("OpenFilm renderer returned a different output path.", "output_path_mismatch");
  }
  const output = await stat(request.outputPath).catch(() => null);
  if (!output || !output.isFile() || output.size <= 0) {
    throw new RunnerError("OpenFilm renderer did not produce a non-empty output file.", "output_missing");
  }
  if (output.size > request.maxOutputBytes) {
    throw new RunnerError("Rendered output exceeded the host-supplied byte limit.", "output_too_large");
  }
  const outputSha256 = await sha256File(request.outputPath);
  return finish({
    status: "rendered",
    job_id: request.jobId,
    openfilm_version: OPENFILM_VERSION,
    output_size: output.size,
    output_sha256: outputSha256,
    profile: request.profile,
    look_diagnostics: inspectedLines,
    render_diagnostics: diagnostics(rendered.lines, [request.projectRoot, request.artifactRoot])
  });
}

async function readStdin(limit) {
  const chunks = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > limit) throw new RunnerError("Input exceeded the fixed JSON request byte limit.");
    chunks.push(chunk);
  }
  if (!size) throw new RunnerError("No JSON request was provided on stdin.");
  return Buffer.concat(chunks).toString("utf8");
}

async function main() {
  try {
    const input = await readStdin(MAX_REQUEST_BYTES);
    let value;
    try { value = JSON.parse(input); }
    catch { throw new RunnerError("stdin was not valid JSON."); }
    const result = await executeJob(value, {
      look: openFilmLook,
      render: openFilmRender,
      emit: (event) => process.stdout.write(encodeEvent(event))
    });
    if (result.status === "qa_blocked") process.exitCode = 3;
  } catch (error) {
    const result = {
      status: "failed",
      failure_category: error instanceof RunnerError ? error.code : "renderer_error",
      message: error instanceof RunnerError ? error.message : "OpenFilm runner failed."
    };
    process.stdout.write(encodeEvent({ event: "result", result }));
    process.exitCode = error instanceof RunnerError ? 2 : 1;
  }
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  await main();
}
