"""El sidecar empaquetado no puede llevar credenciales de privilegio.

Estos tests ejecutan los .spec reales de PyInstaller (con Analysis/EXE/COLLECT
stubbeados y un collect_all controlado) y comprueban que ningun archivo de
secretos llegue a `datas`/`binaries`, que es lo que PyInstaller copia al bundle
distribuible.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"

SPECS = sorted(
    p
    for p in [
        REPO_ROOT / "canyp-backend.spec",
        REPO_ROOT / "build_spec" / "canyp-backend.spec",
        REPO_ROOT / "build_spec" / "canyp-console.spec",
    ]
    if p.exists()
)


class _Stub:
    """Absorbe cualquier llamada/atributo del spec sin construir nada real.

    El spec encadena ``Analysis(...) -> a.pure / a.scripts / a.binaries`` y luego
    ``PYZ(a.pure)``; con __getattr__ devolviendo otro stub la cadena completa
    queda cubierta sin construir el grafo de imports de PyInstaller.
    """

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Stub()


def _collect_all_falso(*_args, **_kwargs):
    """Payload que refleja lo que collect_all realmente devuelve hoy.

    Reproduce el caso real: `backend/.env` (y su copia dentro de dist/) aparecen
    como data files porque collect_data_files incluye todo archivo no-.py del
    paquete, dotfiles incluidos.
    """
    datos = [
        (str(BACKEND_DIR / ".env"), "backend"),
        (str(BACKEND_DIR / "dist" / "canyp-backend" / "_internal" / "backend" / ".env"), "backend/dist"),
        (str(BACKEND_DIR / "venv" / "pyvenv.cfg"), "backend/venv"),
        (str(BACKEND_DIR / "dist" / "canyp-backend" / "_internal" / "app.py"), "backend/dist"),
        (str(BACKEND_DIR / "requirements.txt"), "backend"),
        (str(BACKEND_DIR / "config.py"), "backend"),
    ]
    return datos, [], []


def _ejecutar_spec(spec: Path, monkeypatch) -> dict:
    """Ejecuta el .spec y devuelve su espacio de globals final."""
    import PyInstaller.utils.hooks as hooks

    monkeypatch.setattr(hooks, "collect_all", _collect_all_falso)
    globs = {
        "__file__": str(spec),
        "__name__": "__spec__",
        "Analysis": _Stub,
        "PYZ": _Stub,
        "EXE": _Stub,
        "COLLECT": _Stub,
        "TOC": _Stub,
        "Tree": _Stub,
        "DEBUG": _Stub,
        "BINDIR": "",
        "DISTPATH": "",
        "workpath": "",
        "spec_root": str(spec.parent),
    }
    exec(compile(spec.read_text(encoding="utf-8"), str(spec), "exec"), globs)
    return globs


def _nombres_de_secreto(entradas) -> list[str]:
    """Nombres de archivo de secretos presentes en una lista (src, dest)."""
    salida = []
    for entrada in entradas:
        src = entrada[0] if isinstance(entrada, (tuple, list)) else entrada
        nombre = str(src).replace("\\", "/").rsplit("/", 1)[-1]
        if nombre == ".env" or nombre.startswith(".env."):
            salida.append(str(src))
    return salida


def test_hay_spec_que_verificar():
    assert SPECS, "no se encontro ningun .spec de PyInstaller que verificar"


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.name)
def test_spec_no_empaqueta_archivos_de_secreto(spec, monkeypatch):
    globs = _ejecutar_spec(spec, monkeypatch)

    assert not _nombres_de_secreto(globs["datas"]), (
        f"{spec.name} metio secretos en datas"
    )
    assert not _nombres_de_secreto(globs["binaries"]), (
        f"{spec.name} metio secretos en binaries"
    )


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.name)
def test_spec_no_declara_env_como_data_file_explicito(spec):
    """Ninguna referencia textual a empaquetar backend/.env como data file."""
    fuente = spec.read_text(encoding="utf-8")
    sin_comentarios = "\n".join(
        linea for linea in fuente.splitlines() if not linea.strip().startswith("#")
    )
    assert not re.search(r"datas\s*=\s*\[\s*['\"][^'\"]*\.env", sin_comentarios), (
        f"{spec.name} declara un .env como data file"
    )


def test_collect_all_real_entiende_el_env_y_el_spec_lo_filtra(monkeypatch):
    """Evidencia de que el filtro hace trabajo real, no decorativo.

    collect_all sobre el arbol real devuelve backend/.env; el .spec empaquetado
    lo descarta. Si collect_all dejara de recogerlo, este test sigue green pero
    el segundo assert dejaria de ejercitar el filtro, por eso se comprueba
    explicitamente el caso del arbol real.
    """
    from PyInstaller.utils.hooks import collect_all

    monkeypatch.undo()
    datos, _, _ = collect_all("backend")
    assert _nombres_de_secreto(datos), (
        "collect_all ya no recoge backend/.env: el riesgo de regresion cambio, "
        "revisar si el secreto sigue siendo alcanzable en el bundle"
    )

    spec = REPO_ROOT / "canyp-backend.spec"
    globs = _ejecutar_spec(spec, monkeypatch)
    assert not _nombres_de_secreto(globs["datas"])


def test_spec_empaquetado_falla_loud_si_una_credencial_trae_bundle(monkeypatch, tmp_path):
    """El guard del .spec es una post-condicion real, no decorativo.

    Se parte del .spec real, se neutraliza el filtro de secretos (como si
    alguien lo borrara o lo aflojara) y se comprueba que el build se corta con
    un error en vez de producir un binario con la service_role dentro.
    """
    fuente = (REPO_ROOT / "canyp-backend.spec").read_text(encoding="utf-8")
    fuente_neutra = fuente.replace(
        "datas = [d for d in datas if _keep(d)]", "datas = list(datas)"
    )
    assert fuente_neutra != fuente, "no se encontro la linea de filtro a neutralizar"

    spec_copiado = tmp_path / "spec_sin_filtro.spec"
    spec_copiado.write_text(fuente_neutra, encoding="utf-8")

    import PyInstaller.utils.hooks as hooks

    monkeypatch.setattr(hooks, "collect_all", _collect_all_falso)
    globs = {
        "__file__": str(spec_copiado),
        "__name__": "__spec__",
        "Analysis": _Stub,
        "PYZ": _Stub,
        "EXE": _Stub,
        "COLLECT": _Stub,
    }
    with pytest.raises(SystemExit) as exc:
        exec(compile(fuente_neutra, str(spec_copiado), "exec"), globs)
    assert "secretos" in str(exc.value)


@pytest.mark.parametrize(
    "nombre",
    [".env", ".env.local", ".env.production", ".env.test", "env"],
)
def test_filtro_de_secreto_cubre_las_variantes(nombre, monkeypatch):
    """El filtro es por nombre de archivo, no por una lista minima.

    Toma la funcion tal cual queda definida en el .spec real, sin reimplementar
    la logica en el test.
    """
    es_secreto = _ejecutar_spec(REPO_ROOT / "canyp-backend.spec", monkeypatch)["_is_secret_file"]

    esperado = nombre != "env"
    assert es_secreto(f"C:/proj/backend/{nombre}") is esperado
    assert es_secreto(f"C:/proj/backend/sub/carpeta/{nombre}") is esperado


def test_env_real_no_esta_versionado():
    """backend/.env nunca debe entrar al repositorio."""
    import subprocess

    resultado = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "backend/.env"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert resultado.returncode != 0, "backend/.env esta trackeado en git"
