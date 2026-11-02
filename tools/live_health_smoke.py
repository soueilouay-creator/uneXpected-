from __future__ import annotations

import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = os.environ.get("UNEXPECTED_V8_HEALTH_URL", "https://unexpected-v8-unified-test.onrender.com").rstrip("/")


def get(path: str, timeout: float = 12.0):
    request = Request(BASE + path, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8") or "{}")


def main() -> int:
    health = None
    last_error = None
    for attempt in range(1, 13):
        try:
            status, payload = get("/health", timeout=20)
            if status == 200 and payload.get("ok") is True:
                health = payload
                break
            last_error = f"health returned HTTP {status}: {payload}"
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < 12:
            time.sleep(5)

    if health is None:
        print(f"Unified v8 health failed: {last_error}", file=sys.stderr)
        return 1

    runtime = health.get("runtime") or {}
    checks = {
        "runtime_ready": runtime.get("ok") is True,
        "durable_storage": runtime.get("storage") == "postgresql",
        "registered_agents": runtime.get("registeredAgents") == 38,
        "owner_auth_configured": health.get("authConfigured") is True,
    }
    if not all(checks.values()):
        print(json.dumps({"status": "failed", "checks": checks, "health": health}, indent=2), file=sys.stderr)
        return 1

    status_code, _ = get("/v1/status")
    checks["status_requires_auth"] = status_code == 401
    if not checks["status_requires_auth"]:
        print(json.dumps({"status": "failed", "checks": checks, "unauthenticated_status_code": status_code}, indent=2), file=sys.stderr)
        return 1

    # Do not print provider credentials, owner tokens or private configuration.
    print(json.dumps({
        "status": "passed",
        "checks": checks,
        "runtime_version": runtime.get("version"),
        "provider": runtime.get("provider"),
        "storage": runtime.get("storage"),
        "agent_count": runtime.get("registeredAgents"),
        "privileged_actions": "fail-closed"
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
