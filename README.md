# AI-Powered Multi-Platform Prospect Discovery API

FastAPI service that turns a natural-language prospect query into a deduplicated list of **real, publicly indexed individual or business profiles** across Google, LinkedIn, X, YouTube, Instagram, WhatsApp, Facebook, Email, and Threads.

> **Live demo:** _add Render URL after deployment_  
> **Swagger `/docs`:** _add `<render-url>/docs` after deployment_  
> **Public repository:** _add GitHub URL after push_  
> **Docs checked:** 23 November 2026

---

## 1. What the API does

Given a query such as:

```json
{"query": "Football lovers in Washington DC in USA"}
```

the service:

1. Parses intent with an LLM (Gemini by default) using a deterministic fallback if the LLM is unavailable.
2. Builds authorized public-web queries for each supported platform adapter.
3. Searches with Tavily and keeps only public HTTP(S) URLs.
4. Accepts only profile-shaped pages; generic search/result/home URLs are discarded.
5. Rejects private, loopback, link-local, metadata, and non-public IP targets before any fetch.
6. Validates relevance using deterministic signals plus LLM classification of **untrusted** search text.
7. Extracts only publicly published emails, phone numbers, and WhatsApp links from associated pages.
8. Consolidates duplicates using name, handle, URL, and email signals.
9. Returns the exact required response shape.

> Google is used only as a discovery source. Generic `google.com/search?...` URLs are never returned as prospects.

---

## 2. Response shape

```json
{
  "success": true,
  "query": "Football lovers in Washington DC in USA",
  "total_prospects": 1,
  "prospects": [
    {
      "name": "Jane Doe",
      "location": "Washington DC, District of Columbia, USA",
      "social_link": [
        {
          "platform": "LinkedIn",
          "link": "https://www.linkedin.com/in/jane-doe-football/"
        },
        {
          "platform": "Email",
          "link": "mailto:jane@example.com"
        }
      ]
    }
  ]
}
```

The example above is a **schema example only**. Real live-run output is saved in `docs/sample_responses/live-run.json` after running with valid keys.

---

## 3. Local setup

### Requirements

- Python 3.10+ (tested with Python 3.12.6)
- Git
- Fresh `GEMINI_API_KEY` and `TAVILY_API_KEY`

```powershell
cd C:\Users\aggar\ai-prospect-discovery
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
copy .env.example .env
```

Open `.env` and add your **fresh** keys locally:

```dotenv
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.5-flash-lite
GEMINI_API_KEY=your-fresh-key-here
TAVILY_API_KEY=your-fresh-key-here
```

Never commit `.env`, paste keys in chat, put keys in screenshots, or add keys to Render/GitHub files. `.gitignore` excludes `.env`.

### Run locally

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 4000
```

Open:

- Swagger UI: <http://127.0.0.1:4000/docs>
- Health: <http://127.0.0.1:4000/health>
- Endpoint: `POST http://127.0.0.1:4000/prospect-discovery`

### Sample request

```powershell
curl -X POST "http://127.0.0.1:4000/prospect-discovery" `
  -H "Content-Type: application/json" `
  -d '{\"query\":\"Football lovers in Washington DC in USA\"}'
```

### Quality checks

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m pytest
```

Current result: **111 tests passed**, **97% coverage**, Ruff clean, MyPy clean.

---

## 4. Required test queries

The service was exercised with these five dynamic queries:

1. `Football lovers in Washington DC in USA`
2. `Digital marketing agency owners in New York USA`
3. `Startup founders in London UK`
4. `Cricket lovers in Ahmedabad India`
5. `Restaurant owners in Dubai UAE`

Sanitized live responses and logs are stored under `docs/sample_responses/` and `docs/logs/`. No keys appear in those files.

---

## 5. Architecture

| Layer | File(s) | Responsibility |
| --- | --- | --- |
| API | `app/main.py` | FastAPI app, validation errors, `/health`, `/docs`, `/prospect-discovery` |
| Config | `app/config.py` | Env-backed settings and secret handling |
| Intent | `app/services/query_service.py` | LLM intent parsing with deterministic fallback |
| Discovery | `app/services/search_service.py`, `app/platforms/*` | Tavily search and per-platform adapters |
| Safety | `app/utils/validators.py`, `app/services/safe_http.py` | SSRF/URL validation, bounded and typed fetches |
| Relevance | `app/services/relevance_service.py` | Untrusted-data prompt isolation and scoring |
| Contacts | `app/services/contact_service.py` | Public email/phone/WhatsApp extraction |
| Consolidation | `app/services/deduplication_service.py` | Multi-signal entity resolution |
| Response | `app/schemas.py` | Strict Pydantic response contract |

---

## 6. Supported platforms and limitations

| Platform | Discovery | Final profile link | Contact links | Notes |
| --- | --- | --- | --- | --- |
| Google | Yes | Only non-generic public profile/site pages | Via page extraction | Generic Google search URLs are rejected |
| LinkedIn | Yes | `/in/`, `/pub/`, `/company/` | Public page data only | Login-required data is not accessed |
| X | Yes | Single-handle public profiles | Public page data only | Reserved paths such as `/search` are rejected |
| YouTube | Yes | `@handle`, `/channel/`, `/c/`, `/user/` | Public page data only | `/watch` video URLs are rejected |
| Instagram | Yes | Single-handle public profiles | Public page data only | Post/reel URLs are rejected |
| Facebook | Yes | Profile/page URLs with accepted paths | Public page data only | `profile.php?id=` accepted |
| Email | Yes | `mailto:` from public pages | Yes | Syntax-validated; no deliverability probing |
| WhatsApp | Yes | `wa.me` or `api.whatsapp.com` links | Yes | Publicly published numbers only |
| Threads | Yes | `@handle` public profiles | Public page data only | Login-only content is not accessed |

### Limitations

- Results depend on current public search indexing; private, gated, or login-only profiles cannot be discovered.
- Search engines and platforms can change markup or rate limits without notice.
- Interest matching is heuristic; “football lovers” may surface coaches, clubs, or fans when publicly indexed.
- Contact details are included only when clearly published on an associated public page.
- This API does not scrape private messages, bypass authentication, or guess personal data.
- The in-process TTL cache is per web worker; Render free-tier restarts clear it.

---

## 7. LLM comparison and final recommendation

Sources: official Gemini rate limits/pricing and Groq/OpenAI/Anthropic pricing pages, checked **23 November 2026**.

| Option | Free tier evidence | Paid input / output per 1M tokens | Structured JSON | Verdict |
| --- | --- | --- | --- | --- |
| **Google Gemini 3.5 Flash-Lite** | Free tier available; rate limits are per project and shown in AI Studio | Low-cost paid tier; exact project price should be reconfirmed in pricing page | Native `responseMimeType: application/json` | **Recommended** |
| Groq `qwen/qwen3.8-27b` | 30 RPM, 1K RPD, 8K TPM, 200K TPD on free plan | `$0.80` / `$4.00` | `response_format: json_object` | Best fallback |
| Groq `openai/gpt-oss-20b` | Same free-plan envelope | Check model page before use | `response_format: json_object` | Alternative fallback |
| OpenAI `gpt-4.1-mini` | No comparable permanent free tier | `$0.40` / `$1.60` (batch rates lower) | JSON mode | Reliable paid fallback |
| Claude Haiku 4.5 | No comparable permanent free tier | `$1.00` / `$5.00` | Prompted JSON | Higher cost, not needed |

Measured locally: all 111 tests pass with mocked providers; live provider quality is recorded in `docs/logs/live-run.log`. Free-tier allowances are provider estimates from public docs and can change.

### Final recommendation

Use **Gemini 3.5 Flash-Lite** as the default LLM. It gives the best free-usage fit for a small practical project, supports JSON mode natively, and has a large context window. Keep **Groq `qwen/qwen3.8-27b`** configured as a switchable fallback via `LLM_PROVIDER=groq`.

---

## 8. Cost optimization

- Cache intent, Tavily search, and final response results for 15 minutes by default.
- Use Gemini Flash-Lite; switch to deterministic fallback if the key is absent.
- Keep LLM output small: JSON only, `maxOutputTokens` limited to 1600.
- Run a basic Tavily search depth and cap results per query.
- Fetch at most 10 profile pages per request, bounded by size and content type.
- Use one free Render web service; keep dev checks local.

---

## 9. Security notes

- All secrets are read from environment variables and masked in logs by `SecretRedactionFilter`.
- URLs must be HTTP(S), must not contain embedded credentials, and may use only ports 80/443.
- Private, loopback, link-local, metadata, multicast, reserved, and internal-suffix hosts are blocked.
- DNS answers are validated before fetch; redirects are revalidated at every hop.
- Profile fetches are size-limited, type-limited, and redirect-limited.
- Scraped text is wrapped in `<untrusted_search_data>` and explicitly treated as data, not instructions.
- Pydantic strict schemas forbid extra fields and validate every returned link.
- Deduplication requires matching name plus handle/email (or exact URL), preventing similar-name merges.
- No keys, tokens, or private data are stored in Git, logs, screenshots, or sample responses.

---

## 10. Deployment on Render

`render.yaml` defines the web service:

```yaml
buildCommand: pip install -r requirements.txt
startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
healthCheckPath: /health
```

Add `GEMINI_API_KEY` and `TAVILY_API_KEY` as **secret environment variables** in the Render dashboard. Do not paste them into `render.yaml`.

After deployment, verify:

1. `GET /health` returns `{"status":"ok"}`
2. `GET /docs` opens Swagger UI
3. `POST /prospect-discovery` returns the exact schema

---

## 11. Evidence

| Item | Location |
| --- | --- |
| Live JSON responses | `docs/sample_responses/live-run.json` |
| Sanitized run log | `docs/logs/live-run.log` |
| Screenshots | `docs/screenshots/` |
| CI checks | `.github/workflows/ci.yml` |
| Test summary | `docs/logs/checks.txt` |

_Add live Render URL, `/docs` URL, and screenshots after deployment._
