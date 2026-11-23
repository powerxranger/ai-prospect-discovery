from __future__ import annotations

import argparse

from fastapi.testclient import TestClient

from app.main import app

BASE_CHECKS = (
    ("GET", "/health"),
    ("GET", "/platforms"),
    ("GET", "/docs"),
    ("GET", "/openapi.json"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test the local API.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Also call /validate and /prospect-discovery (may use external APIs).",
    )
    args = parser.parse_args()

    checks = list(BASE_CHECKS)
    if args.live:
        checks.extend(
            [
                ("POST", "/validate"),
                ("POST", "/prospect-discovery"),
            ]
        )

    body = {"query": "Football lovers in Washington DC in USA"}
    failed: list[str] = []

    with TestClient(app) as client:
        for method, path in checks:
            response = client.post(path, json=body) if method == "POST" else client.get(path)
            ok = response.status_code < 400
            print(f"{method} {path} -> {response.status_code} {'OK' if ok else 'FAILED'}")
            if not ok:
                failed.append(f"{method} {path}")
                continue
            if path == "/prospect-discovery":
                payload = response.json()
                expected = {"success", "query", "total_prospects", "prospects"}
                if set(payload) != expected:
                    failed.append("response shape")

    if failed:
        print(f"Smoke test failed: {', '.join(failed)}")
        return 1
    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
