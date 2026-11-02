import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';

const DEFAULT_RUNTIME_PORT = 8765;

export function buildRuntimeEnv(parentEnv, internalToken, runtimePort = DEFAULT_RUNTIME_PORT) {
  const publicPort = String(parentEnv.PORT || '10000');
  return {
    ...parentEnv,
    PORT: String(runtimePort),
    UNEXPECTED_RUNTIME_PORT: String(runtimePort),
    UNEXPECTED_RUNTIME_BIND_HOST: '127.0.0.1',
    UNEXPECTED_RUNTIME_API_TOKEN: internalToken,
    UNEXPECTED_GATEWAY_URL: `http://127.0.0.1:${publicPort}/orchestrate`,
    UNEXPECTED_GATEWAY_TOKEN: internalToken,
    UNEXPECTED_GATEWAY_MODE: parentEnv.UNEXPECTED_GATEWAY_MODE || 'openai',
    UNEXPECTED_PROVIDER: parentEnv.UNEXPECTED_PROVIDER || 'ai_studio_gateway',
    UNEXPECTED_MAX_WORKERS: parentEnv.UNEXPECTED_MAX_WORKERS || '2'
  };
}

export async function waitForRuntimeReady({
  url = 'http://127.0.0.1:8765',
  attempts = 40,
  intervalMs = 500,
  fetchImpl = globalThis.fetch,
  sleepImpl = delay
} = {}) {
  const parsed = new URL(url);
  if (parsed.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(parsed.hostname)) {
    throw new Error('Runtime readiness URL must use HTTP on loopback only.');
  }
  if (!Number.isInteger(attempts) || attempts < 1 || attempts > 120) {
    throw new Error('Runtime readiness attempts must be between 1 and 120.');
  }
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetchImpl(`${url.replace(/\/$/, '')}/health`, {
        signal: AbortSignal.timeout(1200),
        redirect: 'error'
      });
      if (response.ok) {
        const body = await response.json();
        if (body && body.ok === true && typeof body.version === 'string') return body;
      }
      lastError = new Error('Runtime health endpoint did not report ready.');
    } catch (error) {
      lastError = error;
    }
    if (attempt < attempts) await sleepImpl(intervalMs);
  }
  throw new Error(`Runtime did not become ready within ${attempts} attempts: ${lastError?.name || 'health check failed'}`);
}

async function main() {
  const externalToken = String(process.env.UNEXPECTED_ACCESS_TOKEN || '');
  if (externalToken.length < 32) throw new Error('UNEXPECTED_ACCESS_TOKEN must be configured with at least 32 characters.');
  if (!String(process.env.UNEXPECTED_DATABASE_URL || '').trim()) {
    throw new Error('UNEXPECTED_DATABASE_URL is required; unified hosted runtime refuses ephemeral SQLite state.');
  }

  const internalToken = randomBytes(32).toString('hex');
  const runtimePort = Number(process.env.UNEXPECTED_RUNTIME_PORT || DEFAULT_RUNTIME_PORT);
  if (!Number.isInteger(runtimePort) || runtimePort < 1024 || runtimePort > 65535) {
    throw new Error('UNEXPECTED_RUNTIME_PORT must be a valid unprivileged TCP port.');
  }
  const runtimeUrl = `http://127.0.0.1:${runtimePort}`;
  const pythonEnv = buildRuntimeEnv(process.env, internalToken, runtimePort);
  const python = spawn(process.env.PYTHON_EXECUTABLE || 'python3', ['-m', 'unexpected_runtime.http_api'], {
    cwd: process.cwd(), env: pythonEnv, stdio: 'inherit'
  });
  let app;
  let stopping = false;

  const shutdown = (code = 0) => {
    if (stopping) return;
    stopping = true;
    if (app && app.exitCode === null) app.kill('SIGTERM');
    if (python.exitCode === null) python.kill('SIGTERM');
    process.exitCode = code;
  };
  python.once('error', error => {
    process.stderr.write(`Python runtime failed to start: ${error.message}\n`);
    shutdown(1);
  });
  python.once('exit', (code, signal) => {
    if (!stopping) {
      process.stderr.write(`Python runtime exited unexpectedly (code=${code}, signal=${signal}).\n`);
      shutdown(code || 1);
    }
  });

  try {
    await waitForRuntimeReady({ url: runtimeUrl });
  } catch (error) {
    process.stderr.write(`Python runtime readiness failed: ${error.message}\n`);
    shutdown(1);
    return;
  }

  const nodeEnv = {
    ...process.env,
    UNEXPECTED_RUNTIME_INTERNAL_URL: runtimeUrl,
    UNEXPECTED_RUNTIME_INTERNAL_TOKEN: internalToken,
    UNEXPECTED_GATEWAY_INTERNAL_TOKEN: internalToken
  };
  app = spawn(process.execPath, ['server.js'], { cwd: process.cwd(), env: nodeEnv, stdio: 'inherit' });
  app.once('error', error => {
    process.stderr.write(`Public application failed to start: ${error.message}\n`);
    shutdown(1);
  });
  app.once('exit', (code, signal) => {
    if (!stopping) {
      process.stderr.write(`Public application exited unexpectedly (code=${code}, signal=${signal}).\n`);
      shutdown(code || 1);
    }
  });

  process.once('SIGTERM', () => shutdown(0));
  process.once('SIGINT', () => shutdown(0));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => {
    process.stderr.write(`uneXpected unified startup failed: ${error.message}\n`);
    process.exitCode = 1;
  });
}
