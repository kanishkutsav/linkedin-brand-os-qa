# API — Python 3.14.7

This API is configured specifically for CPython 3.14.x.

## Windows PowerShell

```powershell
cd apps/api
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload --port 8000
```

## macOS / Linux

```bash
cd apps/api
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --reload --port 8000
```

Health check: http://localhost:8000/health
API docs: http://localhost:8000/docs
