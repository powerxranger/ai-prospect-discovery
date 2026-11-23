from __future__ import annotations

import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.schemas import DiscoveryResponse

QUERIES = [
    "Football lovers in Washington DC in USA",
    "Digital marketing agency owners in New York USA",
    "Startup founders in London UK",
    "Cricket lovers in Ahmedabad India",
    "Restaurant owners in Dubai UAE",
]

ROOT = Path(__file__).resolve().parents[1]
RESPONSE_FILE = ROOT / "docs" / "sample_responses" / "live-run.json"
LOG_FILE = ROOT / "docs" / "logs" / "live-run.log"


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def platform_counts(response: dict[str, Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for prospect in response.get("prospects", []):
        for link in prospect.get("social_link", []):
            counts[str(link.get("platform", "Unknown"))] += 1
    return dict(sorted(counts.items()))


def main() -> int:
    settings = get_settings()
    if settings.tavily_api_key is None:
        raise SystemExit("TAVILY_API_KEY is missing. Add fresh keys to .env locally and retry.")

    responses: list[dict[str, Any]] = []
    log_lines: list[str] = [
        f"Live discovery run started at {utc_now()}",
        f"LLM provider: {settings.llm_provider}",
        f"LLM model: {settings.llm_model}",
        "API keys are intentionally not logged.",
        "",
    ]

    with TestClient(app) as client:
        health = client.get("/health")
        log_lines.append(f"GET /health -> {health.status_code} {health.json()}")

        for index, query in enumerate(QUERIES, start=1):
            started = time.perf_counter()
            response = client.post("/prospect-discovery", json={"query": query})
            elapsed = round(time.perf_counter() - started, 2)

            if response.status_code == 200:
                payload = response.json()
                DiscoveryResponse.model_validate(payload)
                responses.append(payload)
                log_lines.append(
                    f"[{index}/{len(QUERIES)}] {query} | status=200 | "
                    f"duration={elapsed}s | prospects={payload['total_prospects']} | "
                    f"platforms={platform_counts(payload)}"
                )
            else:
                body = response.json()
                error = body.get("error", {}) if isinstance(body, dict) else {}
                log_lines.append(
                    f"[{index}/{len(QUERIES)}] {query} | status={response.status_code} | "
                    f"duration={elapsed}s | error={error.get('code', 'UNKNOWN')} | "
                    f"message={error.get('message', 'Request failed.')}"
                )

            if index < len(QUERIES):
                time.sleep(2)

    document = {
        "generated_at": utc_now(),
        "source": "local TestClient against app.main:app using fresh .env keys",
        "queries": QUERIES,
        "responses": responses,
    }
    RESPONSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESPONSE_FILE.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    LOG_FILE.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    successful = sum(1 for item in responses if item.get("success") is True)
    total = sum(int(item.get("total_prospects", 0)) for item in responses)
    print(f"Completed {successful}/{len(QUERIES)} queries with {total} total prospects.")
    print(f"Responses: {RESPONSE_FILE}")
    print(f"Log: {LOG_FILE}")
    return 0 if successful == len(QUERIES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
