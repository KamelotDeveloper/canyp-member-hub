# CANYP — Club Náutico

Sistema de gestión de socios y membresías para el Club Náutico (predios Embalse y Almafuerte).

## Stack

- **Backend**: FastAPI + SQLAlchemy + SQLite (WAL)
- **Frontend**: React 19 + TypeScript + TanStack Router/Query v5 + shadcn/ui + Tailwind v4 (Vite, puerto 8080)
- **Tests**: pytest (backend) + vitest (frontend)

## Requisitos

- Python 3.12+
- pnpm (NUNCA usar npm)

## Backend

### Primera vez (crear venv)

```bash
cd backend
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt   # Windows
venv/bin/python -m pip install -r requirements.txt           # Mac/Linux
```

### Correr

SIEMPRE desde la raíz del proyecto, con el módulo `backend.main:app`:

```bash
backend\venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000   # Windows
venv/bin/python -m uvicorn backend.main:app --reload --port 8000                    # Mac/Linux
```

> ⚠️ **No usar `python backend/run.py` ni `main:app` desde dentro de `backend/`**:
> al ejecutar un script, Python no agrega la carpeta actual al `sys.path` y el
> import absoluto `backend.*` de `main.py` falla con `ModuleNotFoundError: No module named 'backend'`.

### Tests

```bash
backend\venv\Scripts\python.exe -m pytest backend/tests -v   # Windows
venv/bin/python -m pytest backend/tests -v                   # Mac/Linux
```

### Semilla de datos

```bash
backend\venv\Scripts\python.exe -m backend.seed
```

## Frontend

```bash
cd frontend
pnpm install
pnpm dev        # → http://localhost:8080 (proxea /api → http://localhost:8000)
```

### Verificaciones

```bash
pnpm lint       # ESLint
pnpm tsc --noEmit
pnpm build
pnpm test       # vitest
```

## Endpoints principales

- `GET/POST /api/socios`, `GET/PUT/DELETE /api/socios/{id}`
- `GET/POST /api/membresias`, `GET/PUT/DELETE /api/membresias/{id}`
- `GET/POST /api/parcelas`, `GET/PUT/DELETE /api/parcelas/{id}`
- `GET/POST /api/aranceles`, `PUT /api/aranceles/{id}/monto`
- `GET/POST /api/pagos`, `GET /api/pagos/{numero}`
- `GET/POST /api/notificaciones`
- `GET /api/dashboard/stats`, `GET /api/dashboard/alertas`

## Notas de entorno (Windows)

- `pnpm` en PowerShell/start de procesos se invoca como `pnpm.cmd`
- Preferir `curl.exe` sobre `Invoke-WebRequest` (falla en modo no interactivo)
- `python-dateutil` es dependencia obligatoria (`backend/services/renovacion.py`)