# Test Cases

Run the application from `5. Project Development Phase` with dependencies installed. AI-dependent cases require a valid Gemini API key and network access. Record actual results in `Test Results.md`.

| ID | Scenario | Steps / input | Expected result |
|---|---|---|---|
| TC-01 | Landing page | Open `/`. | Landing page renders without server error. |
| TC-02 | Planner navigation | Open `/home-planner`, `/party-planner`, `/jewelry-planner`. | Each planner page renders. |
| TC-03 | Home recommendation | Submit a positive budget, rooms, and style. | A home recommendation is returned and added to history. |
| TC-04 | Party recommendation | Submit event type, guest count, and budget. | A party plan is returned and added to history. |
| TC-05 | Jewelry recommendation | Submit occasion, budget, and preferences without image. | Suggestions are returned and added to history. |
| TC-06 | Jewelry image input | Submit a supported outfit image through the UI. | Request completes or returns a clear validation/service error. |
| TC-07 | History retrieval | Generate a plan, then request `/api/history`. | Response includes the generated entry and total count. |
| TC-08 | Clear history | DELETE `/api/history`, then GET it. | History is empty for the current user. |
| TC-09 | Registration and login | Register a username, then request a token with its credentials. | Registration succeeds and valid credentials return a bearer token. |
| TC-10 | Duplicate registration | Register the same username twice. | Second request returns an appropriate client error. |
| TC-11 | Missing Gemini key | Start without `GEMINI_API_KEY`. | App starts; plans are labelled *Offline recommendation*. |
| TC-12 | Gemini failure | Use invalid/unavailable API configuration and submit a plan. | Offline plan returned with a notice; server remains available. |

Do not use real personal information or sensitive images for test evidence.
| TC-13 | Home quantities | Submit lights=5, fans=4, furniture=2, dining tables=1. | Plan contains items with those quantities; allocations sum to the budget. |
| TC-14 | Shopping links | Generate each planner type. | Items have `shopping_links` for the right platforms; no non-whitelisted hosts. |
| TC-15 | Plan details | GET `/recommendation-details/{id}` as owner and as another user. | 200 for the owner, 404 for others. |
| TC-16 | Session endpoints | GET `/session-info`; POST then GET `/session-data`. | Login time, last activity, duration and merged data returned. |
| TC-17 | Logout revocation | Log out, then reuse the old token. | 401. |
| TC-18 | Idle cleanup | Run session cleanup with every session idle. | Sessions removed; next request returns 401. |
| TC-19 | CORS | Preflight from an allowed and a disallowed origin. | Allowed origin echoed; others get no CORS header. |
| TC-20 | PostgreSQL | Run the suite with `DATABASE_URL` set. | All tests pass; `/startup` reports `postgresql`. |

