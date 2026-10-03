# PocketSmart AI — AI Budget Planner (Supabase PostgreSQL edition)

Home, party and jewelry budget planners with Gemini-powered (or offline) recommendations,
user accounts, per-user history and server-side sessions.

**What changed in this version:** only the database. Data now lives in **Supabase PostgreSQL**.
The UI, features, business logic, API routes and workflows are unchanged.

```
.
├── README.md
├── supabase_schema.sql      # run once in the Supabase SQL Editor (tables, indexes, RLS)
├── render.yaml              # Render Blueprint for the backend web service
├── frontend/                # UI: Jinja2 templates + static assets (served by the backend)
│   ├── templates/  static/
│   ├── .env                 # public Supabase values only (nothing required to run)
│   └── .env.example
├── backend/                 # FastAPI app
│   ├── app.py  auth.py  database.py  models.py
│   ├── planner_service.py  recommendations.py  enrichment.py
│   ├── routers/             # auth, home, party, jewelry
│   ├── tests/test_app.py    # 25 tests
│   ├── requirements.txt
│   ├── .env                 # <-- fill in your Supabase values
│   └── .env.example
├── vercel-proxy/            # optional Vercel front door for the Render app (unchanged)
└── docs/                    # original project documentation (unchanged content)
```

The UI is server-rendered, so `frontend/` has no build step: the backend loads
`frontend/templates` and mounts `frontend/static` at `/static`. Deploy `backend/` and keep
`frontend/` next to it.

---

## 1. Set up Supabase (5 minutes)

1. **Create the tables.** Supabase Dashboard → **SQL Editor** → New query → paste all of
   `supabase_schema.sql` → **Run**. It is safe to run again (idempotent). It creates
   `users`, `recommendations`, `sessions`, their foreign keys (cascade delete), check
   constraints, unique and lookup indexes, and enables **Row Level Security**.
2. **Get the connection string.** Dashboard → **Connect** → *Session pooler* (port 5432).
   Use the pooler string on Render/Vercel and any host without IPv6; the direct
   `db.<ref>.supabase.co` host is IPv6-only on most plans.
3. **Get the database password** (Project Settings → Database → *Reset database password*
   if you do not have it). URL-encode special characters (`@` → `%40`, `/` → `%2F`, `:` → `%3A`, `#` → `%23`).
4. Put everything into `backend/.env` (see §3).

### Important: which Supabase credentials the backend actually uses

The backend talks to Postgres directly (SQLAlchemy + psycopg), so the only credential it
needs is the **database connection string with the database password** (`DATABASE_URL`).
The **Publishable key** and **Secret key** are API keys for Supabase's REST/JS APIs; they
cannot open a Postgres connection, and the backend does not call those APIs. They are in
`.env` for completeness / future use only.

- Never put the **Secret key** (`sb_secret_...`) in `frontend/` or any browser code, and never commit it.
- If a secret key was ever pasted into a chat, ticket or repo, rotate it in
  Project Settings → API Keys.

### Row Level Security (why there are no "allow" policies)

The app has its own login (bcrypt + JWT, table `users`) and does not use Supabase Auth, and
every query goes through the backend, which connects as the `postgres` role (bypasses RLS).
Supabase would otherwise expose these tables to anyone holding the publishable key —
including `users.hashed_password`. So the SQL file enables RLS on all three tables,
**revokes** `anon`/`authenticated` privileges, and adds explicit deny-all policies for those
roles. Result: the backend works normally; the public REST API can read and write nothing.

---

## 2. Run locally

```bash
cd backend
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload          # http://127.0.0.1:8000
```

Check the database: open `http://127.0.0.1:8000/startup` →
`"database": {"backend": "postgresql", "ok": true}`.

Local development without Supabase: set `ENVIRONMENT=development` and leave `DATABASE_URL`
empty — the app falls back to a local SQLite file. **In production (`ENVIRONMENT=production`
or `RENDER=true`) the app refuses to start without a database URL**, so data can never
silently end up in a throw-away SQLite file.

### Tests

```bash
python -m unittest discover -s backend/tests -p "test_*.py" -v
```

The tests use a temporary SQLite file by default and never read your real `.env` database
settings. To run them against a **separate/test** Postgres, set `TEST_DATABASE_URL` first.
Do not point it at your production Supabase project.

---

## 3. Environment variables (`backend/.env`)

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | **Yes (production)** | Supabase Postgres connection string (Session pooler). `postgres://` / `postgresql://` both accepted. TLS is enforced automatically. |
| `SUPABASE_URL` | Optional | `https://<ref>.supabase.co`. If `DATABASE_URL` is empty, the backend builds the *direct* connection URL from this + `SUPABASE_DB_PASSWORD`. |
| `SUPABASE_DB_PASSWORD` | Optional | Only used together with `SUPABASE_URL` as above. |
| `SUPABASE_PROJECT_NAME`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY` | No | Stored for reference/future use; not used by the DB connection. |
| `SECRET_KEY` | **Yes (production)** | Signs login tokens. A strong random value is already generated in the shipped `backend/.env`; use a different one per environment. |
| `ENVIRONMENT` | Recommended | `production` enforces `SECRET_KEY`, `DATABASE_URL` and Secure cookies. |
| `CORS_ORIGINS` | No | Comma-separated allowed browser origins (never `*`; cookies are used). |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | No | Connection pool tuning (defaults 5 / 5). Keep the total below your Supabase pooler limit. |
| `GEMINI_API_KEY` | No | Without it the app uses offline plans. |
| `GEMINI_MODEL`, `GEMINI_FALLBACK_MODELS`, `GEMINI_TIMEOUT_SECONDS` | No | Unchanged from before. |
| `ACCESS_TOKEN_EXPIRE_MINUTES`, `SESSION_IDLE_MINUTES`, `COOKIE_SECURE`, `COOKIE_SAMESITE`, `HOST`, `PORT` | No | Unchanged from before. |

Connection modes: session pooler (port 5432, recommended) and transaction pooler
(port 6543) both work — prepared statements are disabled in the driver so pgbouncer is happy.

---

## 4. Deploy

### Backend on Render

1. Push this repository to GitHub.
2. Render → **New → Blueprint** → select the repo (`render.yaml` is picked up).
3. When prompted, set: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_PROJECT_NAME`,
   `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, optionally `GEMINI_API_KEY`.
   `SECRET_KEY` is generated for you. Set `CORS_ORIGINS` to your site URL.
4. Health check path is `/startup` (reports `degraded` if the database is unreachable).

Manual settings if you do not use the Blueprint:
Build `pip install -r backend/requirements.txt` · Start
`cd backend && uvicorn app:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"`.

### Optional: Vercel front door

`vercel-proxy/vercel.json` rewrites every request to the Render service. Replace
`YOUR-REAL-SERVICE.onrender.com` with your Render hostname, deploy `vercel-proxy/` as a
Vercel project, then set `CORS_ORIGINS` on Render to the Vercel URL.

### Post-deploy checklist

- `/startup` → `"status": "running"` and `"backend": "postgresql"`.
- Register an account, log in, create a plan, reload `/history` → the plan is there.
- Supabase → Table Editor shows rows in `users`, `recommendations`, `sessions`.
- Supabase → Authentication → Policies shows RLS enabled on all three tables.

---

## 5. Data model

| Table | Purpose | Keys / constraints |
|---|---|---|
| `users` | accounts | PK `id`; unique `lower(username)`, unique `lower(email)`; `username` not blank |
| `recommendations` | saved plans (JSON stored as text) | PK `id` (uuid text); FK `user_id → users.id` on delete cascade; `category in (home, party, jewelry)`; `budget >= 1`; index `(user_id, timestamp)` |
| `sessions` | server-side logins (JWT `jti`) | PK `id`; FK `user_id → users.id` on delete cascade; indexes on `user_id`, `expires_at`, `last_activity` |

Timestamps stay ISO-8601 **text** columns because the application compares and parses them
as strings; changing them to `timestamptz` would require code changes, which this migration
deliberately avoids.

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| App exits at start: `DATABASE_URL is not set` | Fill `DATABASE_URL` in `backend/.env` / Render env. |
| `password authentication failed` | Wrong **database** password (not an API key); reset it in Supabase and URL-encode special characters. |
| `Network is unreachable` / hangs to `db.<ref>.supabase.co` | Direct host is IPv6-only; use the **Session pooler** string. |
| `Tenant or user not found` | Pooler username must be `postgres.<project-ref>`, and the pooler host must match your project's region. |
| `/startup` says `degraded` | The app is up but cannot reach Postgres; check the string and that the Supabase project is not paused (free projects pause after inactivity). |

## 7. Security notes

- Secrets come only from environment variables; `SECRET_KEY` and `DATABASE_URL` are mandatory in production.
- Cookies are HttpOnly, `Secure` in production, `SameSite=Lax`. Logout revokes the session server-side.
- RLS is enabled on every table and the public API roles are denied (see §1).
- Shopping links are built only from a fixed platform whitelist; prices are AI/offline planning estimates.
- No password-reset / e-mail verification flow and **no rate limiting** (unchanged from the original; add rate limiting, e.g. at Vercel/Cloudflare, before a public launch).
- Uploaded outfit images are analysed in memory and not stored.
- `.env` is git-ignored; commit only the `.env.example` templates. If any key was ever pasted into a chat, document or screenshot, rotate it.
