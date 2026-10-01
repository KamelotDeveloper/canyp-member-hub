# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
tmp_ret = collect_all('backend')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# `collect_all('backend')` walks the whole backend package directory, so local
# build artifacts that live inside it (venv/, dist/, build*/) get bundled as
# data/binaries and hidden imports. Those are gitignored and not part of the
# package: they bloat the sidecar and can exceed the Windows MAX_PATH during
# copy. Drop them before Analysis.
_EXCLUDED_DIRS = {"venv", "dist", "build", "build_dist", "build_spec", "build_work", "__pycache__"}

# collect_data_files() ships EVERY non-.py file under the package dir, dotfiles
# included, so `backend/.env` (SUPABASE_SERVICE_KEY with role=service_role,
# MP_ACCESS_TOKEN) was landing in the distributable at
# _internal/backend/.env. Filtering directories is not enough — the secret sits
# next to the sources. Drop secret files by name; PyInstaller's TOC does not
# ship the raw source path, so the exclusion holds for onefile and onedir.
_SECRET_FILE_NAMES = {".env"}


def _is_secret_file(src: str) -> bool:
    name = src.replace("\\", "/").rsplit("/", 1)[-1]
    return name in _SECRET_FILE_NAMES or name.startswith(".env.")


def _is_build_artifact(src: str) -> bool:
    parts = src.replace("\\", "/").split("/")
    return any(part in _EXCLUDED_DIRS for part in parts)


def _keep(entry):
    return not (_is_build_artifact(entry[0]) or _is_secret_file(entry[0]))


datas = [d for d in datas if _keep(d)]
binaries = [b for b in binaries if _keep(b)]
hiddenimports = [h for h in hiddenimports if not _is_build_artifact(h.replace(".", "/"))]

# Guard: a packaged sidecar must carry zero operator credentials. Fail the
# build loudly rather than shipping a binary with a service_role key inside.
_leaked = [d[0] for d in datas if _is_secret_file(d[0])]
if _leaked:
    raise SystemExit(
        "canyp-backend.spec: se intentaron empaquetar archivos de secretos en el "
        "sidecar: " + ", ".join(_leaked)
    )


a = Analysis(
    ['backend/desktop_run.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='canyp-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='canyp-backend',
)
