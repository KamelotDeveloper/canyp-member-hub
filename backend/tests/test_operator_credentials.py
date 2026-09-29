"""Ausencia de credencial de operador = fallo explicito, nunca default inseguro.

El sidecar distribuido no puede llevar la service_role de Supabase ni el token
de MercadoPago del operador. Estos tests cubren las dos caras del arranque:
que un build de cliente las rechace si aparecen, y que un build del operador
corte con un mensaje util cuando falta alguna.
"""

from __future__ import annotations

import pytest

from backend import operator_credentials as oc
from backend.config import Settings
from backend.operator_credentials import (
    CREDENCIALES_OPERADOR,
    FaltanCredencialesOperador,
    credenciales_de_operador_presentes,
    credenciales_operador_ausentes,
    verificar_credenciales_operador,
)

SECRETO_FALSO = "valor-que-no-debe-aparecer-en-mensajes"


def _settings(**valores) -> Settings:
    base = {
        "SUPABASE_URL": "https://proyecto.supabase.co",
        "SUPABASE_SERVICE_KEY": SECRETO_FALSO,
        "MP_ACCESS_TOKEN": SECRETO_FALSO,
    }
    base.update(valores)
    return Settings(**base)


# ==================== INVENTARIO Y CLASIFICACION ====================


def test_service_key_y_mp_token_son_de_operador():
    """Las dos credenciales que se filtraban son privilegio del operador."""
    por_nombre = {c.nombre: c for c in CREDENCIALES_OPERADOR}
    assert set(por_nombre) == {"SUPABASE_SERVICE_KEY", "MP_ACCESS_TOKEN"}


def test_la_base_del_club_no_es_credencial_de_operador():
    """El cliente configura SU base; no es una credencial del operador."""
    dominios = {c.nombre: c.dominio for c in oc.CREDENCIALES}
    assert dominios["DATABASE_URL"] == oc.DOMINIO_INSTALACION
    assert dominios["JWT_SECRET"] == oc.DOMINIO_INSTALACION
    assert dominios["SUPABASE_SERVICE_KEY"] == oc.DOMINIO_OPERADOR
    assert dominios["MP_ACCESS_TOKEN"] == oc.DOMINIO_OPERADOR


def test_ninguna_credencial_de_instalacion_exige_privilegio_del_dueno():
    """Lo que el cliente puede configurar por su cuenta no es del operador."""
    assert all(
        c.dominio == oc.DOMINIO_INSTALACION
        for c in oc.CREDENCIALES
        if c.nombre in {"DATABASE_URL", "JWT_SECRET"}
    )


# ==================== DETECCION DE AUSENCIA ====================


@pytest.mark.parametrize("faltante", ["SUPABASE_SERVICE_KEY", "MP_ACCESS_TOKEN"])
def test_detecta_la_credencial_de_operador_ausente(faltante):
    ausentes = credenciales_operador_ausentes(_settings(**{faltante: ""}))
    assert [c.nombre for c in ausentes] == [faltante]


def test_espacios_en_blanco_cuentan_como_ausente():
    assert [c.nombre for c in credenciales_operador_ausentes(_settings(MP_ACCESS_TOKEN="   "))] == [
        "MP_ACCESS_TOKEN"
    ]


def test_una_credencial_de_instalacion_ausente_no_es_de_operador():
    """Sin JWT_SECRET el operador NO es el problema: no debe cortarse el arranque."""
    assert credenciales_operador_ausentes(_settings(JWT_SECRET="")) == []


# ==================== FALLO EXPLICITO EN BUILD DE OPERADOR ====================


@pytest.mark.parametrize("faltante", ["SUPABASE_SERVICE_KEY", "MP_ACCESS_TOKEN"])
def test_build_de_operador_sin_credencial_corta_con_mensaje_util(faltante):
    with pytest.raises(FaltanCredencialesOperador) as exc:
        verificar_credenciales_operador(
            _settings(**{faltante: ""}), es_build_cliente=False
        )

    mensaje = str(exc.value)
    assert faltante in mensaje, "el mensaje debe nombrar la variable que falta"
    assert "no puede funcionar" in mensaje
    assert SECRETO_FALSO not in mensaje, "el mensaje no debe filtrar ningun valor"


def test_el_mensaje_explica_para_que_sirve_cada_credencial():
    with pytest.raises(FaltanCredencialesOperador) as exc:
        verificar_credenciales_operador(
            _settings(SUPABASE_SERVICE_KEY="", MP_ACCESS_TOKEN=""),
            es_build_cliente=False,
        )

    mensaje = str(exc.value)
    assert "MercadoPago" in mensaje
    assert "suscripciones" in mensaje
    assert SECRETO_FALSO not in mensaje


def test_build_de_operador_completo_arranca():
    verificar_credenciales_operador(_settings(), es_build_cliente=False)


# ==================== FALLO EXPLICITO EN BUILD DE CLIENTE ====================


def test_build_de_cliente_sin_credenciales_de_operador_arranca():
    """El bundle de cliente NO lleva esas credenciales: es el estado esperado."""
    verificar_credenciales_operador(
        _settings(SUPABASE_SERVICE_KEY="", MP_ACCESS_TOKEN=""), es_build_cliente=True
    )


@pytest.mark.parametrize("presente", ["SUPABASE_SERVICE_KEY", "MP_ACCESS_TOKEN"])
def test_build_de_cliente_con_credencial_de_operador_corta(presente):
    """Si una credencial de operador aparece en un build de cliente, se corta.

    Es la regresion de empaquetado que se quiere cazar: un binario con la
    service_role dentro regala las tablas de suscripciones a quien lo instale.
    """
    with pytest.raises(FaltanCredencialesOperador) as exc:
        verificar_credenciales_operador(_settings(), es_build_cliente=True)

    assert exc.value.fuga_en_build_cliente is True
    assert presente in str(exc.value)
    assert "service_role" in str(exc.value)
    assert SECRETO_FALSO not in str(exc.value)


def test_build_de_cliente_con_la_base_del_cliente_sigue_arrancando():
    """La base del club y el JWT si pueden estar: son del cliente, no del dueno."""
    verificar_credenciales_operador(
        _settings(SUPABASE_SERVICE_KEY="", MP_ACCESS_TOKEN=""), es_build_cliente=True
    )


# ==================== ARRANQUE REAL DEL SIDECAR ====================


def _settings_sin_operador() -> Settings:
    return _settings(SUPABASE_SERVICE_KEY="", MP_ACCESS_TOKEN="")


def test_sidecar_corta_el_arranque_con_mensaje_en_stderr(monkeypatch, capsys):
    """desktop_run corta con exit 1 y mensaje util; nunca imprime el valor."""
    monkeypatch.delenv("CANYP_CLIENT_BUILD", raising=False)
    monkeypatch.setattr("backend.config.settings", _settings_sin_operador())

    from backend import desktop_run

    with pytest.raises(SystemExit) as exc:
        desktop_run._verify_operator_credentials()

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "SUPABASE_SERVICE_KEY" in err
    assert "MP_ACCESS_TOKEN" in err
    assert SECRETO_FALSO not in err


def test_sidecar_no_levanta_el_servidor_si_falta_credencial(monkeypatch):
    """El corte ocurre ANTES de levantar uvicorn: no se sirve ni un request."""
    monkeypatch.delenv("CANYP_CLIENT_BUILD", raising=False)
    monkeypatch.setattr("backend.config.settings", _settings_sin_operador())

    import uvicorn

    from backend import desktop_run

    levantados: list[str] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: levantados.append("run"))
    monkeypatch.setattr(desktop_run, "_configure_database_url", lambda: None)

    with pytest.raises(SystemExit):
        desktop_run.main()

    assert levantados == [], "no debe haberse levantado el servidor"


def test_sidecar_arranca_con_credenciales_de_operador(monkeypatch):
    """Con el inventario completo el corte no ocurre y se llega a uvicorn."""
    monkeypatch.delenv("CANYP_CLIENT_BUILD", raising=False)
    monkeypatch.setattr("backend.config.settings", _settings())

    import uvicorn

    from backend import desktop_run

    levantados: list[str] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: levantados.append("run"))
    monkeypatch.setattr(desktop_run, "_configure_database_url", lambda: None)

    desktop_run.main()

    assert levantados == ["run"]


def test_build_de_cliente_con_credencial_filtrada_corta_en_el_sidecar(monkeypatch, capsys):
    """La regresion de empaquetado se caza al arrancar, no solo en un helper."""
    monkeypatch.setenv("CANYP_CLIENT_BUILD", "1")
    monkeypatch.setattr("backend.config.settings", _settings())

    from backend import desktop_run

    with pytest.raises(SystemExit) as exc:
        desktop_run._verify_operator_credentials()

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "cliente" in err
    assert "service_role" in err
    assert SECRETO_FALSO not in err
