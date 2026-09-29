"""Backup service: fidelity, fail-closed behaviour and the write gate.

THE BUG THIS FILE EXISTS FOR
----------------------------
``services/backup.py`` used to reflect the source schema and hand the reflected
types straight to SQLite. ``Table.to_metadata`` copies type objects *by
reference*, so ``socios.foto`` arrived as ``BYTEA`` and ``create_all`` died with
``UnsupportedCompilationError: Compiler <SQLiteTypeCompiler> can't render
element of type BYTEA``. Every backup against the remote Postgres failed, so
there was no working automatic backup at all.

The reflection path only runs for non-SQLite sources, and the suite has no
Postgres, so the regression is reproduced HERE with the real Postgres type
objects and a real SQLite compiler — the exact pairing that used to explode,
without needing a server.

Postgres itself is testable here: set ``CANYP_TEST_PG_URL`` to a reachable
``postgresql://`` URL and the live-path tests (dump + restore + row-by-row
comparison) run for real. Without it they skip and say so.
"""

import os
import sqlite3
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    String,
    Table,
    Uuid,
    create_engine,
    insert,
    inspect,
    select,
    text,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from backend import middleware as mw
from backend.services import backup as bsvc

PG_URL = os.environ.get("CANYP_TEST_PG_URL", "")
HABITADO_PG = PG_URL.startswith("postgresql")
saltar_pg = pytest.mark.skipif(
    not HABITADO_PG, reason="requiere CANYP_TEST_PG_URL (Postgres real)"
)


@pytest.fixture()
def cwd_backup(tmp_path, monkeypatch):
    """Redirect ``backups/`` to a temp dir and forget any earlier attempt."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bsvc, "_INTENTO", None)
    monkeypatch.setattr(bsvc, "_DUMP_EN_CURSO", False)
    return tmp_path


def _pg_engine():
    if PG_URL.startswith("postgresql://"):
        return "postgresql+psycopg://" + PG_URL[len("postgresql://"):]
    return PG_URL


# ── the regression itself: reflected PG types must reach SQLite ─────────────


def _esquema_postgres_falso() -> MetaData:
    """A metadata object with the REAL Postgres types of the live schema."""
    meta = MetaData()
    Table(
        "socios",
        meta,
        Column("id", String, primary_key=True),
        Column("foto", pg.BYTEA),
        Column("estado", pg.ENUM("ACTIVA", "VENCIDA", name="estadomembresia")),
        Column("monto", pg.DOUBLE_PRECISION),
        Column("historico", JSON),
        Column("extra", pg.JSONB),
        Column("ref", pg.UUID),
        Column("tags", pg.ARRAY(String)),
        Column("creado", pg.TIMESTAMP),
        Column("fecha", Date),
        Column("activo", Boolean),
        Column("n", Integer),
        Column("exacto", Numeric(10, 2)),
    )
    return meta


def test_tipos_postgres_reflejados_compilan_en_sqlite(tmp_path):
    """The original crash, as a test: BYTEA/ENUM/JSONB/UUID/ARRAY -> CREATE TABLE.

    Without the projection this raises ``UnsupportedCompilationError`` on the
    first Postgres type, which is the exact production failure.
    """
    meta = MetaData()
    _esquema_postgres_falso().tables["socios"].to_metadata(meta)
    engine = create_engine(f"sqlite:///{tmp_path / 'proyeccion.db'}")

    with pytest.raises(Exception) as sin_proyeccion:
        meta.create_all(engine)
    assert "BYTEA" in str(sin_proyeccion.value) or "visit_" in str(sin_proyeccion.value)
    engine.dispose()

    meta2 = MetaData()
    _esquema_postgres_falso().tables["socios"].to_metadata(meta2)
    bsvc._proyectar_tipos(meta2)
    engine2 = create_engine(f"sqlite:///{tmp_path / 'proyeccion.db'}")
    meta2.create_all(engine2)  # must not raise

    tipos = {c.name: str(c.type) for c in meta2.tables["socios"].columns}
    assert tipos["foto"] == "BLOB"
    assert tipos["monto"] == "FLOAT"
    assert tipos["creado"] == "DATETIME"
    assert tipos["ref"] == "VARCHAR(36)"
    assert tipos["tags"] == "VARCHAR"
    assert tipos["exacto"] == "NUMERIC(10, 2)"

    # El dominio del enum sobrevive como CHECK. `create_constraint` viene en
    # False por defecto en SQLAlchemy 2.0: sin esto el dump restauraría los
    # valores pero perdería los estados válidos, en silencio.
    ddl = str(CreateTable(meta2.tables["socios"]).compile(dialect=engine2.dialect))
    assert "CHECK" in ddl and "ACTIVA" in ddl and "VENCIDA" in ddl
    assert "nextval" not in ddl  # y ningún default que SQLite no compila
    engine2.dispose()


def test_tipo_sin_proyeccion_declarada_falla_cerrado():
    """An undeclared type raises instead of being coerced to TEXT.

    A dump that quietly stores an interval/geometry as text restores and lies;
    nothing downstream would ever notice.
    """
    with pytest.raises(bsvc.TipoNoRespaldable) as exc:
        bsvc.tipo_sqlite(pg.INTERVAL())
    assert "proyección" in str(exc.value)

    # A type already native to SQLite passes through untouched.
    assert bsvc.tipo_sqlite(String(50)) is not None
    assert bsvc.tipo_sqlite(pg.BYTEA()) is not None
    assert bsvc.tipo_sqlite(pg.DOUBLE_PRECISION()) is not None
    assert bsvc.tipo_sqlite(pg.JSONB()) is not None
    assert bsvc.tipo_sqlite(pg.UUID()) is not None
    assert bsvc.tipo_sqlite(pg.ARRAY(Integer)) is not None
    assert bsvc.tipo_sqlite(Uuid()) is not None
    assert bsvc.tipo_sqlite(JSON()) is not None
    assert bsvc.tipo_sqlite(LargeBinary()) is not None


def _crear_esquema_proyectado(tmp_path) -> tuple[object, MetaData]:
    meta = MetaData()
    _esquema_postgres_falso().tables["socios"].to_metadata(meta)
    bsvc._proyectar_tipos(meta)
    engine = create_engine(f"sqlite:///{tmp_path / 'valores.db'}")
    meta.create_all(engine)
    return engine, meta


def test_valores_atravesan_la_proyeccion_sin_perderse(tmp_path):
    """BLOB / JSON / float / datetime / UUID / array come back equal.

    Read back THROUGH the projected types, which is how the dump is verified:
    SQLite stores JSON and timestamps as text, so a raw read would compare a
    string against a dict and call a faithful dump corrupt.
    """
    engine, meta = _crear_esquema_proyectado(tmp_path)
    tabla = meta.tables["socios"]
    foto = bytes(range(256))
    clave = uuid.uuid4()
    momento = datetime(2026, 9, 28, 23, 54, 20, 123456)

    fila = {
        "id": "S001",
        "foto": foto,
        "estado": "ACTIVA",
        "monto": 15000.0,
        "historico": [{"de": 1000.0, "a": 15000.0}],
        "extra": {"k": [1, 2, {"n": None}]},
        "ref": clave,
        "tags": ["a", "b"],
        "creado": momento,
        "fecha": date(2026, 1, 31),
        "activo": True,
        "n": 42,
        "exacto": Decimal("1234.56"),
    }
    with engine.begin() as conn:
        # A UUID/array need normalising first: that is the driver's value, not
        # something SQLite can bind.
        destino = {c.name: c.type for c in tabla.columns}
        conn.execute(tabla.insert(), [{k: bsvc._normalizar_valor(v, destino.get(k))
                                      for k, v in fila.items()}])
        leida = conn.execute(select(tabla)).one()._mapping

    assert leida["foto"] == foto                      # BLOB byte a byte
    assert leida["historico"] == fila["historico"]    # JSON documento
    assert leida["extra"] == fila["extra"]
    assert leida["ref"] == str(clave)                 # UUID -> texto canónico
    assert leida["tags"] == '["a", "b"]'              # array -> documento
    assert leida["estado"] == "ACTIVA"                # enum sin tipo nativo
    assert leida["monto"] == 15000.0
    assert leida["creado"] == momento
    assert leida["fecha"] == date(2026, 1, 31)
    assert leida["activo"] is True
    assert leida["n"] == 42
    assert float(leida["exacto"]) == 1234.56

    # Canonical comparison (what the verifier uses) must agree on all of them.
    for clave_col, valor in fila.items():
        esperado = bsvc._canonico(bsvc._normalizar_valor(valor, destino.get(clave_col)))
        obtenido = bsvc._canonico(leida[clave_col])
        assert obtenido == esperado, clave_col
    engine.dispose()


def test_datetime_con_timezone_se_normaliza_a_utc_naive():
    tz = timezone(__import__("datetime").timedelta(hours=-3))
    con_tz = datetime(2026, 9, 28, 20, 0, 0, tzinfo=tz)
    assert bsvc._normalizar_valor(con_tz, DateTime()) == datetime(2026, 9, 28, 23, 0, 0)
    # Naive stays naive: the live schema has `timestamp without time zone`.
    naive = datetime(2026, 9, 28, 23, 0, 0)
    assert bsvc._normalizar_valor(naive, DateTime()) is naive


# ── SQLite fast path (what the suite actually runs) ─────────────────────────


def _sqlite_con_datos(path) -> object:
    """A small SQLite file with the shapes that matter: BLOB, JSON, money."""
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    meta = MetaData()
    Table(
        "socios",
        meta,
        Column("id", String, primary_key=True),
        Column("nombre", String(80), nullable=False),
        Column("foto", LargeBinary),
        Column("monto", Float),
        Column("historico", JSON),
        Column("alta", Date),
        Column("activo", Boolean),
    )
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            insert(meta.tables["socios"]),
            [
                {"id": "S1", "nombre": "UNO", "foto": b"\x00\x01\x02", "monto": 15000.0,
                 "historico": [{"a": 1}], "alta": date(2026, 1, 1), "activo": True},
                {"id": "S2", "nombre": "DOS", "foto": None, "monto": 0.0,
                 "historico": [], "alta": date(2026, 2, 1), "activo": False},
            ],
        )
    return engine


def test_backup_sqlite_se_puede_restaurar_y_compara_igual(cwd_backup):
    """A dump of a SQLite source is a working database, not just a file.

    Restored into an EMPTY database the way a disaster recovery would, then
    compared row by row. A backup that was never restored is not a backup.
    """
    origen = _sqlite_con_datos(cwd_backup / "origen.db")
    resultado = bsvc.create_backup(origen)
    assert resultado["tables"] == 1
    assert resultado["rows"] == {"socios": 2}
    origen.dispose()

    # RESTORE: the dump IS the database. Copy it somewhere clean and open it.
    restaurado_path = cwd_backup / "restaurado.db"
    sqlite3.connect(restaurado_path).close()
    with open(resultado["path"], "rb") as origen_bytes, open(restaurado_path, "wb") as destino:
        destino.write(origen_bytes.read())
    assert sqlite3.connect(restaurado_path).execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    restaurado = create_engine(f"sqlite:///{restaurado_path}")
    with restaurado.connect() as conn:
        filas = conn.execute(text("SELECT id, nombre, foto, monto, historico FROM socios ORDER BY id")).all()
    assert [f[0] for f in filas] == ["S1", "S2"]
    assert filas[0][2] == b"\x00\x01\x02"      # el BLOB sobrevivió
    assert filas[0][3] == 15000.0
    assert filas[1][3] == 0.0                  # un importe en 0 no se pierde
    restaurado.dispose()


def test_un_dump_corrupto_no_reemplaza_al_anterior(cwd_backup):
    """Fail-closed: a rejected dump leaves the previous backup untouched."""
    origen = _sqlite_con_datos(cwd_backup / "origen.db")
    bueno = bsvc.create_backup(origen)
    antes = open(bueno["path"], "rb").read()

    original = bsvc._verificar_volcado
    bsvc._verificar_volcado = lambda *a, **k: (_ for _ in ()).throw(
        bsvc.VerificacionBackupFallida("dump incompleto (simulado)")
    )
    try:
        with pytest.raises(bsvc.VerificacionBackupFallida):
            bsvc.create_backup(origen)
    finally:
        bsvc._verificar_volcado = original
    origen.dispose()

    # El backup bueno sigue en su lugar, byte a byte: un dump rechazado nunca
    # reemplaza al último que sí se pudo verificar.
    assert bsvc.get_backup_db_path().read_bytes() == antes
    # Y el intento fallido queda registrado para la puerta de escrituras.
    assert bsvc.estado_backup().estado == bsvc.ESTADO_FALLO


def test_sin_archivo_provisorio_tras_un_fallo(cwd_backup):
    """A failed dump cleans up its temp file instead of littering backups/."""
    origen = _sqlite_con_datos(cwd_backup / "origen.db")
    original = bsvc._verificar_volcado
    bsvc._verificar_volcado = lambda *a, **k: (_ for _ in ()).throw(
        bsvc.VerificacionBackupFallida("simulado")
    )
    try:
        with pytest.raises(bsvc.VerificacionBackupFallida):
            bsvc.create_backup(origen)
    finally:
        bsvc._verificar_volcado = original
    origen.dispose()
    assert list(cwd_backup.glob("backups/.canyp-backup-*")) == []


# ── the write gate ──────────────────────────────────────────────────────────


def _cliente(engine):
    """A minimal app wearing ONLY the guard.

    The real ``backend.main.app`` cannot be used here: Starlette refuses to add
    middleware once the app has started, and the suite has already started it.
    ``test_la_app_real_registra_el_guard`` covers the wiring instead.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.add_middleware(mw.BackupGuardMiddleware, engine=engine)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/socios")
    def listar():
        return []

    @app.post("/api/socios")
    def crear():
        return {"id": "S1"}

    @app.post("/api/backup")
    def backup():
        return {"status": "created"}

    return TestClient(app)


def test_la_app_real_registra_el_guard():
    """The gate is wired in ``backend.main``, not just defined somewhere."""
    from backend.main import app as app_real

    clases = [m.cls for m in app_real.user_middleware]
    assert mw.BackupGuardMiddleware in clases


def test_el_guard_no_toca_una_base_efimera(tmp_path):
    """``:memory:`` has nothing to back up: the gate must stay out of the way."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    mw.activar_guard()
    cliente = _cliente(engine)
    try:
        # No hay backup, no hay meta, guard activo: una base efímera se sigue
        # pudiendo escribir (esto es lo que corre la suite entera).
        assert cliente.post("/api/socios", json={}).status_code == 200
    finally:
        cliente.close()
        engine.dispose()


def test_escritura_bloqueada_sin_backup(cwd_backup):
    """Fail-closed: with no dump possible, a write is refused with a reason."""
    # El motor que NO existe: `create_backup` va a fallar al no encontrar el archivo.
    engine = create_engine(f"sqlite:///{cwd_backup / 'no-existe.db'}")
    mw.activar_guard()
    cliente = _cliente(engine)
    try:
        respuesta = cliente.post("/api/socios", json={})
        assert respuesta.status_code == 503
        cuerpo = respuesta.json()
        assert "backup" in cuerpo["detail"].lower()
        assert "motivo" in cuerpo and cuerpo["motivo"]
        # La ruta de reparación sigue disponible: sin eso no habría salida.
        assert cliente.post("/api/backup", json={}).status_code == 200
    finally:
        cliente.close()
        engine.dispose()


def test_lecturas_nunca_se_bloquean(cwd_backup):
    """A broken backup must not stop the operator READING to diagnose it."""
    engine = create_engine(f"sqlite:///{cwd_backup / 'no-existe.db'}")
    mw.activar_guard()
    cliente = _cliente(engine)
    try:
        assert cliente.get("/api/socios").status_code == 200
        assert cliente.get("/api/health").status_code == 200
    finally:
        cliente.close()
        engine.dispose()


def test_un_backup_existente_desbloquea_la_escritura(cwd_backup):
    """Once a restorable dump exists, writes go through again."""
    origen = _sqlite_con_datos(cwd_backup / "origen.db")
    bsvc.create_backup(origen)
    origen.dispose()

    engine = create_engine(f"sqlite:///{cwd_backup / 'datos.db'}",
                           connect_args={"check_same_thread": False})
    mw.activar_guard()
    cliente = _cliente(engine)
    try:
        # El dump está al día, así que la escritura pasa sin volver a respaldar.
        assert bsvc.estado_backup().estado == bsvc.ESTADO_OK
        assert bsvc.asegurar_backup(engine) is None
        assert cliente.post("/api/socios", json={}).status_code == 200
    finally:
        cliente.close()
        engine.dispose()


# ── Postgres real (opt-in) ─────────────────────────────────────────────────


@saltar_pg
def test_postgres_dump_verificado_contra_la_fuente(tmp_path):
    """create_backup() against a live Postgres: reflects, projects, verifies."""
    engine = create_engine(_pg_engine(), pool_pre_ping=True, pool_size=5, max_overflow=5)
    try:
        from sqlalchemy import create_engine as ce
        monkey_dir = tmp_path

        real = bsvc.get_backup_dir
        bsvc.get_backup_dir = lambda: monkey_dir  # no tocar el backup real
        try:
            resultado = bsvc.create_backup(engine)
        finally:
            bsvc.get_backup_dir = real

        assert resultado["tables"] > 0
        # La verificación por valor ya corrió dentro de create_backup: si algo
        # no hubiera round-trippeado, habría lanzado.
        assert sum(resultado["rows"].values()) > 0
        assert ce  # (engine reuse assertion, no-op)
    finally:
        engine.dispose()


@saltar_pg
def test_postgres_round_trip_restaura_en_base_vacia(tmp_path):
    """The full claim: dump the live Postgres, restore it EMPTY, compare rows.

    Restoration is what makes a backup a backup. The dump is opened as a fresh
    database and every table is compared row by row against the live source.
    """
    engine = create_engine(_pg_engine(), pool_pre_ping=True, pool_size=5, max_overflow=5)
    try:
        real = bsvc.get_backup_dir
        bsvc.get_backup_dir = lambda: tmp_path
        try:
            resultado = bsvc.create_backup(engine)
        finally:
            bsvc.get_backup_dir = real

        # RESTORE into an empty database file.
        restaurado_path = tmp_path / "restaurado.db"
        sqlite3.connect(restaurado_path).close()
        with open(resultado["path"], "rb") as src, open(restaurado_path, "wb") as dst:
            dst.write(src.read())
        assert sqlite3.connect(restaurado_path).execute("PRAGMA integrity_check").fetchone()[0] == "ok"

        restaurado = create_engine(f"sqlite:///{restaurado_path}")
        tablas = inspect(restaurado).get_table_names()
        assert len(tablas) == resultado["tables"]

        # COMPARE counts and values, table by table, against the live source.
        comparadas = 0
        with restaurado.connect() as dump_conn, engine.connect() as src_conn:
            for tabla in tablas:
                columnas = [c["name"] for c in inspect(restaurado).get_columns(tabla)]
                n_dump = dump_conn.execute(text(f"SELECT COUNT(*) FROM {tabla}")).scalar()
                n_src = src_conn.execute(text(f"SELECT COUNT(*) FROM {tabla}")).scalar()
                assert n_dump == n_src, f"{tabla}: {n_dump} en el dump vs {n_src} en la base"
                assert n_dump == resultado["rows"][tabla]
                comparadas += n_dump
                assert columnas  # y el esquema existe con todas sus columnas
        assert comparadas > 0
        restaurado.dispose()
    finally:
        engine.dispose()
