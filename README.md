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
pnpm dev        # → http://localhost:8080 (proxea /api → backend dev en el puerto 8000)
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

### Importación masiva (socios)

- `GET /api/socios/import/template` — plantilla XLSX descargable.
- `POST /api/socios/import/preview` — sube un archivo `.csv/.xlsx` (≤ 10 MB) y devuelve las filas validadas para revisar/editar.
- `POST /api/socios/import/execute` — ejecuta la importación de las filas editadas (validate + dedupe server-side, re-validación por fila).
- Requiere las dependencias `openpyxl` (plantilla/lectura XLSX) y `python-multipart` (subida de archivos) en `backend/requirements.txt`.

## Notas de entorno (Windows)

- `pnpm` en PowerShell/start de procesos se invoca como `pnpm.cmd`
- Preferir `curl.exe` sobre `Invoke-WebRequest` (falla en modo no interactivo)
- `python-dateutil` es dependencia obligatoria (`backend/services/renovacion.py`)
- **PowerShell 5.1 escribe BOM** con `Out-File -Encoding utf8` y
  `Set-Content -Encoding utf8`. Si ese archivo es el mensaje de un commit
  (`git commit -F`), el BOM entra en el subject. Para escribir texto sin BOM:
  `-Encoding utf8NoBOM`, o
  `[IO.File]::WriteAllText($ruta, $texto, (New-Object Text.UTF8Encoding $false))`.

## Hooks de git

Los hooks del repo viven en `.githooks/` y hay que activarlos **una vez por
clon** (no se versionan en la config local de git):

```
git config core.hooksPath .githooks
```

`commit-msg` aborta el commit si el mensaje empieza con un BOM UTF-8, con el
mensaje exacto que lo produce y cómo escribirlo sin BOM. Tres commits de
`fix/cuota-social-siempre-visible` nacieron con BOM en el subject por esto.
