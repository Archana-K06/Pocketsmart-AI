# Test Results

## Automated runs (2026-10-02)

| Command | Environment | Result |
|---|---|---|
| `python -m unittest discover -s "PocketSmart-AI/PocketSmart-AI/6. Project Testing" -p "test_*.py"` | Python 3.12, Linux, SQLite (temporary file), Gemini key absent | **25 tests passed** |
| Same command with `DATABASE_URL=postgres://…` | PostgreSQL 16.15 (local server), psycopg 3.3 | **25 tests passed** |
| Same suite from the final ZIP, extracted into a fresh virtual environment built only from `requirements.txt` | Python 3.12, SQLite | **25 tests passed** |

Coverage: all templates compile; public/protected routes; registration, duplicate and case-insensitive usernames; password limits; login, cookie and bearer auth; logout revocation; sessions and cleanup; all three planners (offline), quantities, link whitelist, calculation table and remaining budget; per-user history and detail ownership; outfit-image validation; Gemini provider contract with a mocked SDK (success, failure, over-budget, string prices); CORS; health endpoint.

## Live HTTP smoke test (uvicorn, `ENVIRONMENT=production`, PostgreSQL)

Production start refused without `SECRET_KEY`; `/startup`; register; login; all 8 pages returned 200; home plan with quantities (remaining budget 0); history; plan details; session info; logout; old cookie then returned 401; security headers present.
The exact `buildCommand` / `startCommand` from `render.yaml` were also run from the repository root (SQLite) and served `/startup` and `/login`.

## Not verified

- **Live Gemini calls** — no API key was available; the provider path is tested with a mocked SDK only.
- **Real Render and Vercel deployments** — configuration was validated locally (YAML/JSON parse, start commands) but not deployed. Verify the post-deploy checklist in the README, in particular that login persists through the Vercel proxy.
- **Browser rendering** — no browser was available; templates were checked by compilation, HTTP responses and reading the scripts. Please click through each planner once.
