from __future__ import annotations

from pathlib import Path

from app.config import Settings, get_settings
from app.platforms.registry import get_adapters


def configured(value: object) -> str:
    return "set" if value else "missing"


def report(settings: Settings) -> int:
    env_file = Path(".env")
    print(f"env file found: {env_file.exists()}")
    print(f"LLM provider: {settings.llm_provider}")
    print(f"LLM model: {settings.llm_model}")
    print(f"Gemini key: {configured(settings.gemini_api_key)}")
    print(f"Groq key: {configured(settings.groq_api_key)}")
    print(f"OpenAI key: {configured(settings.openai_api_key)}")
    print(f"Tavily key: {configured(settings.tavily_api_key)}")
    print(f"Active LLM key: {configured(settings.active_llm_key())}")
    print(f"Discovery platforms: {', '.join(adapter.name for adapter in get_adapters())}")

    missing: list[str] = []
    if not settings.tavily_api_key:
        missing.append("TAVILY_API_KEY")
    if settings.llm_provider != "none" and not settings.active_llm_key():
        missing.append(f"key for LLM_PROVIDER={settings.llm_provider}")

    if missing:
        print(f"Not ready. Missing: {', '.join(missing)}")
        return 1
    print("Ready. Start the API with: uvicorn app.main:app --host 127.0.0.1 --port 4000")
    return 0


def main() -> int:
    return report(get_settings())


if __name__ == "__main__":
    raise SystemExit(main())
