# Installation Guide

The complete, maintained guide (local setup, environment variables, PostgreSQL, Render and Vercel) is the
repository-root **README.md**. Short version:

```powershell
Set-Location "PocketSmart-AI\PocketSmart-AI\5. Project Development Phase"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app:app --reload
```

Browse to http://127.0.0.1:8000. `GEMINI_API_KEY` is optional; without it plans are generated offline.
Set a stable `SECRET_KEY` to keep logins valid across restarts, and set `DATABASE_URL` to use PostgreSQL.
