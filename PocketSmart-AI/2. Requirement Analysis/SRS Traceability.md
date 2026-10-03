# SRS Traceability

Source: *PocketSmart AI: Your Smart Budget & Recommendation Assistant* (SmartBridge / SmartInternz SRS).
Status as of 2026-10-02. Tests refer to `6. Project Testing/test_app.py`.

| SRS item | Implementation | Status |
|---|---|---|
| Home Budget Planner: budget, room types, quantities of lights / fans / furniture / dining tables | `routers/home.py` (`num_*` fields), `templates/home_planner.html`, quantity-aware plan in `recommendations.py` | Done (`test_home_quantities_are_honoured_and_budget_adds_up`) |
| Party Planner: budget, guests, event type, venue, needs; platforms per category (Swiggy, Zomato, OYO, …) | `routers/party.py`, `enrichment.py` category→platform rules | Done (`test_party_links_follow_category_rules`) |
| Jewelry Planner: budget, occasion, style, optional outfit image, Amazon/Flipkart/Bluestone/Tanishq/CaratLane/Melorra/Meesho | `routers/jewelry.py`, image validation, outfit analysis via Gemini | Done (image path tested with mocked SDK + offline) |
| Gemini integration, multimodal input | `recommendations.py`; models configurable (`GEMINI_MODEL`) because *Gemini 1.5 Flash Pro* named in the SRS no longer exists | Done; live key not exercised in tests |
| Budget breakdown: category, allocation, items (name, description, price, quantity, search terms), calculation table, remaining budget, additional suggestions/tips | `enrichment.py` adds `search_terms`, `shopping_links`, `calculation_table`, `total_budget`, `remaining_budget`; tips from model/fallback | Done |
| INR / Indian market | Prompts, ₹ formatting, Indian platforms | Done |
| Routes `/generate-home`, `/generate-party`, `/generate-jewelry` | `routers/*.py` | Done |
| `/register`, `/login`, `/logout`, `/token` | `routers/auth.py` | Done |
| `/session-info` (login time, last activity, duration), `/session-data` (read/update) | DB-backed sessions (`database.py`, `routers/auth.py`) | Done (`test_session_info_and_session_data_post`) |
| Logout invalidates token ("blacklist") | Session row revoked; JWT carries `jti` | Done (`test_logout_revokes_the_token_server_side`) |
| Background cleanup of expired sessions (30 min idle, every 5 min) | `app.py` lifespan task → `cleanup_sessions` | Done (`test_session_cleanup_removes_idle_sessions`) |
| `/recommendations-details`, `/recommendation-details/{id}` | `app.py` | Done (owner-only) |
| `/history` page and API, history view/clear | `app.py`, `templates/history.html` | Done |
| `/startup` and `__main__` uvicorn entry | `app.py` | Done |
| CORS + static routing | `CORSMiddleware` with explicit origins (`CORS_ORIGINS`) | Done (`test_cors_allows_only_configured_origins`) |
| Fallback recommendations when AI returns insufficient results; input validation | `_fallback`, `_is_valid_result`, Pydantic limits, minimum budget ₹1 | Done |
| Mock / simulated platform data | Search-link generation (no scraping of third-party sites) | Done (links only) |
| Modular structure `routes/ services/ models/` | `routers/`, `planner_service.py` + `recommendations.py` + `enrichment.py`, `models.py` | Equivalent (different folder names) |
| UI: landing, testimonials, footer, register, login, dashboard, planners, history | Existing templates retained | Done |
| Login "Forgot password?" link (UI mock-up only) | — | **Not implemented** (needs e-mail provider) |
| SRS "Prerequisites" (IBM Cloud / Watsonx / FastAPI docs) and Flask/AWS diagram | Inconsistent with the rest of the SRS (the app uses Google Gemini and FastAPI) | Not applicable; FastAPI used |
