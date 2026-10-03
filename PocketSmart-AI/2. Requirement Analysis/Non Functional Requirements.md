# Non-Functional Requirements

- **Usability:** Forms use clear labels, input constraints, and actionable error messages.
- **Performance:** Non-AI pages do not wait on external services; Gemini calls time out after `GEMINI_TIMEOUT_SECONDS` (default 25 s) per model and then fall back.
- **Reliability:** External API errors are logged and never crash the server; an offline plan is returned.
- **Security:** Secrets come from environment variables; `SECRET_KEY` is mandatory in production; HttpOnly + Secure cookies; server-side session revocation; explicit CORS origins; security headers; link whitelist.
- **Privacy:** Uploaded outfit images are processed in memory only and not retained.
- **Maintainability:** Route handlers are separated by feature; dependencies are listed in `requirements.txt`; 25 automated tests.
- **Portability:** Windows, macOS and Linux; SQLite locally, PostgreSQL in production.
- **Data durability:** Met when `DATABASE_URL` points to PostgreSQL. SQLite on Render's free disk is not durable.
