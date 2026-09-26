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


def _is_build_artifact(src: str) -> bool:
    parts = src.replace("\\", "/").split("/")
    return any(part in _EXCLUDED_DIRS for part in parts)


datas = [d for d in datas if not _is_build_artifact(d[0])]
binaries = [b for b in binaries if not _is_build_artifact(b[0])]
hiddenimports = [h for h in hiddenimports if not _is_build_artifact(h.replace(".", "/"))]


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
