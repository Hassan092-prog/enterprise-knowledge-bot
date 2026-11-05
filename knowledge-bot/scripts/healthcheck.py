#!/usr/bin/env python3
"""
healthcheck.py — Zero-dependency container health & readiness probe for Docker / K8s.
Usage:
  python scripts/healthcheck.py               # Liveness probe (http://localhost:8000/health)
  python scripts/healthcheck.py --ready       # Readiness probe (http://localhost:8000/ready)
  python scripts/healthcheck.py http://...    # Custom probe target
"""

import sys
import json
import urllib.request
import urllib.error

def probe(url: str, timeout: int = 5) -> int:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "EnterpriseKnowledgeBot-Healthcheck/2.2"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.status
            body = resp.read().decode("utf-8")
            if status_code == 200:
                try:
                    data = json.loads(body)
                    status = data.get("status", "")
                    if status in ("ok", "healthy", "ready"):
                        return 0
                    print(f"Healthcheck degraded/unhealthy: {status}", file=sys.stderr)
                    return 1
                except json.JSONDecodeError:
                    return 0  # 200 OK without JSON payload is also considered alive
            print(f"Healthcheck failed with HTTP {status_code}", file=sys.stderr)
            return 1
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        print(f"Healthcheck HTTP error {e.code} {e.reason}: {body}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Healthcheck connection error: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    target = "http://localhost:8000/health"
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        if arg in ("--ready", "-r", "--readiness"):
            target = "http://localhost:8000/ready"
        elif arg.startswith("http://") or arg.startswith("https://"):
            target = arg
    sys.exit(probe(target))
