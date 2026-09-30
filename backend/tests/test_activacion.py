"""Frontera de confianza: un build de cliente NO abre sin licencia.

Qué pasa antes de este archivo
-----------------------------
La auditoría confirmó seis puntos por los que un ``settings.json`` escrito a
mano abría la app completa y sin licencia:

1. ``LicenseGate.tsx`` hacía passthrough con ``configured:false``.
2. ``ClientBuildGuard`` (``__root.tsx``) sólo bloqueaba con ``configured:true``.
3. ``desktop_run`` sólo abortaba si ``settings.configured`` era true.
4. El ``DataModeWizard`` se podía cerrar.
5. ``POST /api/auth/first-user`` creaba un admin sin licencia.
6. El resultado conjunto: app completa, funcional, sin pagar.

Y un séptimo, que la auditoría original no listaba y que es el más grave de
todos: en un build de cliente las credenciales de operador **no están** (ver
``backend/operator_credentials.py``: una ``service_role`` dentro del binario
saltaría todas las RLS), así que la fila de licencia de Supabase no se podía
leer y el sistema caía al **trial local**, que es una tabla en el SQLite de la
propia máquina. Borrar la base y volver a pedir el trial era un bypass sin
conexión y sin límite.

Cada test de este archivo es un test de regresión de UNO de esos bypasses: si
alguien reintroduce cualquiera, el test falla. Y cada uno tiene su gemelo en
``TestFlujoDeDesarrolloIntacto`` que demuestra que el mismo camino sigue
funcionando fuera de un build de cliente, porque romper el dev flow es el
riesgo #1 de este trabajo.
"""

import json
import os

import pytest

from backend.activation import (
    MOTIVO_BASE_REMOTA_INVALIDA,
    MOTIVO_FUERA_DE_BUILD_CLIENTE,
    MOTIVO_LISTO,
    MOTIVO_SIN_BASE_REMOTA,
    es_url_remota_valida,
    evaluar_activacion,
    exigir_operacion,
)
from backend.settings_store import AppSettings, load_settings, save_settings

# Rutas de dominio que deben quedar cerradas sin activación. Una por router:
# si alguien agrega un router nuevo sin la dependencia, la lista lo delata.
RUTAS_DE_DOMINIO = [
    ("GET", "/api/socios"),
    ("GET", "/api/membresias"),
    ("GET", "/api/aranceles"),
    ("GET", "/api/pagos"),
    ("GET", "/api/dashboard/stats"),
    ("GET", "/api/notificaciones"),
    ("GET", "/api/parcelas"),
    ("GET", "/api/export/socios"),
    ("GET", "/api/usuarios"),
    ("GET", "/api/backup/status"),
]

# El archivo de texto del bypass original, textual.
SETTINGS_BYPASS = {"dataMode": "local", "databaseUrl": "", "configured": False}
URL_REMOTA_VALIDA = "postgresql://canyp:secreto@db.supabase.co:5432/postgres"


def _escribir_settings(monkeypatch, tmp_path, payload, filename="settings.json"):
    """Apunta default_settings_path a un archivo de prueba y escribe el payload."""
    target = tmp_path / filename
    target.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("backend.settings_store.default_settings_path", lambda: str(target))
    return target


def _build_cliente(monkeypatch):
    monkeypatch.setenv("CANYP_CLIENT_BUILD", "1")


def _sin_build_cliente(monkeypatch):
    monkeypatch.delenv("CANYP_CLIENT_BUILD", raising=False)


@pytest.fixture()
def settings_bypass(monkeypatch, tmp_path):
    """Reproduce exactamente el settings.json del bypass: local, sin configurar."""
    return _escribir_settings(monkeypatch, tmp_path, SETTINGS_BYPASS)


# ===========================================================================
# La regla, en una línea
# ===========================================================================


class TestReglaDeLaFrontera:
    """``evaluar_activacion`` es la única fuente de verdad."""

    def test_build_cliente_sin_configurar_esta_bloqueado(self, settings_bypass, monkeypatch):
        _build_cliente(monkeypatch)
        estado = evaluar_activacion()
        assert estado.operacion_permitida is False
        assert estado.motivo == MOTIVO_SIN_BASE_REMOTA
        assert estado.es_build_cliente is True

    def test_build_cliente_local_configurado_esta_bloqueado(self, monkeypatch, tmp_path):
        # El caso que el desktop_run ya cubría: configurado pero local.
        _escribir_settings(
            monkeypatch,
            tmp_path,
            {"dataMode": "local", "databaseUrl": "", "configured": True},
        )
        _build_cliente(monkeypatch)
        estado = evaluar_activacion()
        assert estado.operacion_permitida is False
        assert estado.motivo == MOTIVO_SIN_BASE_REMOTA

    def test_build_cliente_con_base_remota_valida_esta_permitido(self, monkeypatch, tmp_path):
        _escribir_settings(
            monkeypatch,
            tmp_path,
            {"dataMode": "remoto", "databaseUrl": URL_REMOTA_VALIDA, "configured": True},
        )
        _build_cliente(monkeypatch)
        estado = evaluar_activacion()
        assert estado.operacion_permitida is True
        assert estado.motivo == MOTIVO_LISTO

    def test_fuera_de_build_cliente_siempre_permitido(self, settings_bypass, monkeypatch):
        # El settings de local+sin configurar es el dev flow por definición.
        _sin_build_cliente(monkeypatch)
        estado = evaluar_activacion()
        assert estado.operacion_permitida is True
        assert estado.motivo == MOTIVO_FUERA_DE_BUILD_CLIENTE

    def test_sin_archivo_de_settings_un_build_cliente_esta_bloqueado(self, monkeypatch, tmp_path):
        # Installación recién desempaquetada, sin ningún settings.json.
        _escribir_settings(monkeypatch, tmp_path, SETTINGS_BYPASS)
        monkeypatch.setattr("backend.settings_store.default_settings_path", lambda: str(tmp_path / "no-existe.json"))
        _build_cliente(monkeypatch)
        assert evaluar_activacion().operacion_permitida is False

    def test_no_depende_de_configured_una_vez_remoto(self, monkeypatch, tmp_path):
        # `configured` es un flag de UI, no de seguridad. Si hay base remota
        # válida, la instalación puede operar haya o no pasado por el wizard.
        _escribir_settings(
            monkeypatch,
            tmp_path,
            {"dataMode": "remoto", "databaseUrl": URL_REMOTA_VALIDA, "configured": False},
        )
        _build_cliente(monkeypatch)
        assert evaluar_activacion().operacion_permitida is True


class TestClasificacionDeUrl:
    """``es_url_remota_valida`` falla cerrado, y trata a sqlite como local."""

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://u:p@h:5432/db",
            "postgres://u:p@h/db",
            "postgresql+psycopg://u:p@h/db",
        ],
    )
    def test_acepta_postgres(self, url):
        assert es_url_remota_valida(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "sqlite:///C:/Users/x/AppData/Local/canyp.db",
            "sqlite:///:memory:",
            "sqlite+pysqlite:///data.db",
            "file:///C:/datos.db",
            "",
            "   ",
            "canyp2026temp",  # ni siquiera parsea
            "oracle://u:p@h/db",
        ],
    )
    def test_rechaza_todo_lo_que_no_es_postgres(self, url):
        assert es_url_remota_valida(url) is False

    def test_sqlite_declarado_como_remoto_esta_bloqueado(self, monkeypatch, tmp_path):
        """Bypass nuevo y real: decir "remoto" y apuntar a un archivo local.

        Antes de ``es_url_remota_valida``, un ``settings.json`` con
        ``dataMode:"remoto"`` + ``sqlite:///...`` pasaba cualquier chequeo de
        "está en modo remoto" y el sidecar seguía sirviendo un archivo local.
        """
        _escribir_settings(
            monkeypatch,
            tmp_path,
            {
                "dataMode": "remoto",
                "databaseUrl": "sqlite:///C:/ataque/canyp.db",
                "configured": True,
            },
        )
        _build_cliente(monkeypatch)
        estado = evaluar_activacion()
        assert estado.operacion_permitida is False
        assert estado.motivo == MOTIVO_BASE_REMOTA_INVALIDA

    def test_url_remoto_invalida_esta_bloqueada(self, monkeypatch, tmp_path):
        _escribir_settings(
            monkeypatch,
            tmp_path,
            {"dataMode": "remoto", "databaseUrl": "canyp2026temp", "configured": True},
        )
        _build_cliente(monkeypatch)
        assert evaluar_activacion().motivo == MOTIVO_BASE_REMOTA_INVALIDA


# ===========================================================================
# BYPASS 1 + 6 — el settings.json de texto no abre la app
# ===========================================================================


class TestBypass1LicenseGateConfiguredFalse:
    """Bypass 1: ``configured:false`` era passthrough en el LicenseGate.

    El fix no es "arreglar el LicenseGate": es que el servidor niegue las rutas
    de dominio. Estos tests atacan la API directamente, que es donde importa.
    """

    @pytest.mark.parametrize("metodo,ruta", RUTAS_DE_DOMINIO)
    def test_toda_ruta_de_dominio_responde_503(self, test_client, settings_bypass, monkeypatch, metodo, ruta):
        _build_cliente(monkeypatch)
        resp = getattr(test_client, metodo.lower())(ruta)
        assert resp.status_code == 503, f"{ruta} respondió {resp.status_code} sin licencia"
        assert "administrador" in resp.json()["detail"]

    def test_ninguna_ruta_de_dominio_sirve_datos(self, test_client, settings_bypass, monkeypatch):
        """No alcanza con el status: el cuerpo no puede filtrar datos del club."""
        _build_cliente(monkeypatch)
        cuerpo = test_client.get("/api/socios").text
        assert "[]" not in cuerpo
        assert "socios" not in cuerpo.lower() or "detail" in cuerpo

    def test_escrituras_tambien_esta_bloqueadas(self, test_client, settings_bypass, monkeypatch):
        """El bloqueo es de la frontera, no sólo de lectura."""
        _build_cliente(monkeypatch)
        resp = test_client.post("/api/socios", json={"dni": "12345678", "nombre": "Intruso", "apellido": "X"})
        assert resp.status_code == 503


class TestBypass2ClientBuildGuardSinVeredictoDelServidor:
    """Bypass 2: el guard de la UI derivaba el bloqueo de ``settings``.

    El endpoint que la UI ahora refleja: si dice que no se puede operar, la
    instalación está bloqueada. Y devuelve 200 siempre, porque "no activado" es
    un estado, no un error.
    """

    def test_activacion_reporta_bloqueo(self, raw_client, settings_bypass, monkeypatch):
        _build_cliente(monkeypatch)
        resp = raw_client.get("/api/activacion")
        assert resp.status_code == 200
        cuerpo = resp.json()
        assert cuerpo["operacionPermitida"] is False
        assert cuerpo["esBuildCliente"] is True
        assert cuerpo["motivo"] == MOTIVO_SIN_BASE_REMOTA
        assert cuerpo["mensaje"]

    def test_activacion_no_filtra_la_url_de_conexion(self, raw_client, monkeypatch, tmp_path):
        """Ni en claro ni enmascarada: la URL es del operador, no del cliente."""
        _escribir_settings(
            monkeypatch,
            tmp_path,
            {"dataMode": "remoto", "databaseUrl": URL_REMOTA_VALIDA, "configured": True},
        )
        _build_cliente(monkeypatch)
        cuerpo = raw_client.get("/api/activacion").text
        assert URL_REMOTA_VALIDA not in cuerpo
        assert "secreto" not in cuerpo
        assert "databaseUrl" not in cuerpo

    def test_activacion_abierta_sin_autenticacion(self, raw_client, settings_bypass, monkeypatch):
        """Pre-login a propósito: hay que poder preguntar sin tener usuario."""
        _build_cliente(monkeypatch)
        assert raw_client.get("/api/activacion").status_code == 200

    def test_activacion_permite_con_base_remota(self, raw_client, monkeypatch, tmp_path):
        _escribir_settings(
            monkeypatch,
            tmp_path,
            {"dataMode": "remoto", "databaseUrl": URL_REMOTA_VALIDA, "configured": True},
        )
        _build_cliente(monkeypatch)
        cuerpo = raw_client.get("/api/activacion").json()
        assert cuerpo["operacionPermitida"] is True
        assert cuerpo["motivo"] == MOTIVO_LISTO


class TestBypass3SidecarArrancaEnLocalSinLicencia:
    """Bypass 3: ``desktop_run`` arrancaba SQLite si ``configured`` era false.

    La parte que cambia: arrancar en local sí sigue pasando (el asistente de
    primer uso necesita un backend vivo para que el operador cargue la base
    remota), pero arrancar NO es operar. Lo que se cierra es que el backend
    sirva la app desde ahí.
    """

    def test_sidecar_puede_arrancar_para_mostrar_el_asistente(self, monkeypatch, tmp_path):
        """Se mantiene a propósito: sin backend vivo no hay pantalla de activación."""
        _escribir_settings(monkeypatch, tmp_path, SETTINGS_BYPASS)
        _build_cliente(monkeypatch)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        from backend import desktop_run

        desktop_run._configure_database_url()
        assert os.environ["DATABASE_URL"].startswith("sqlite:///")

    def test_pero_la_app_no_opera_desde_ahi(self, test_client, monkeypatch, tmp_path):
        """El mismo estado del punto anterior, ahora por la API: 503."""
        _escribir_settings(monkeypatch, tmp_path, SETTINGS_BYPASS)
        _build_cliente(monkeypatch)
        assert test_client.get("/api/socios").status_code == 503

    def test_sidecar_advertencia_de_esperando_activacion(self, monkeypatch, tmp_path, capsys):
        """No es un arranque silencioso: el log dice que la app está bloqueada."""
        _escribir_settings(monkeypatch, tmp_path, SETTINGS_BYPASS)
        _build_cliente(monkeypatch)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        from backend import desktop_run

        desktop_run._configure_database_url()
        err = capsys.readouterr().err
        assert "esperando activación" in err.lower()

    def test_sidecar_y_frontera_coinciden_en_que_es_remoto(self, monkeypatch, tmp_path):
        """Si el sidecar dice remoto y la frontera dice local, la frontera miente."""
        from backend import desktop_run

        for payload in (
            {"dataMode": "remoto", "databaseUrl": URL_REMOTA_VALIDA, "configured": True},
            {"dataMode": "remoto", "databaseUrl": "", "configured": True},
            {"dataMode": "local", "databaseUrl": URL_REMOTA_VALIDA, "configured": True},
            {"dataMode": "local", "databaseUrl": "", "configured": False},
        ):
            _escribir_settings(monkeypatch, tmp_path, payload)
            _build_cliente(monkeypatch)
            remoto_para_sidecar = desktop_run._remote_database_url_from_settings() is not None
            permitido = evaluar_activacion().operacion_permitida
            assert permitido == remoto_para_sidecar, payload


class TestBypass4WizardNoDescartable:
    """Bypass 4: el diálogo se cerraba y dejaba ``configured:false``.

    El efecto de servidor de cerrar el wizard es ninguno: el estado bloqueado
    ya no depende de que el wizard siga abierto. Este test fija esa propiedad
    para que nadie la revierta por la vía de "dejemos que el usuario lo cierre".
    """

    def test_descartar_el_wizard_no_libera_la_app(self, test_client, settings_bypass, monkeypatch):
        _build_cliente(monkeypatch)
        # El wizard se "descartó" (el estado del frontend cambió a dismissed).
        # Lo que importa es lo que el servidor responde con ese mismo archivo.
        assert test_client.get("/api/socios").status_code == 503
        assert test_client.get("/api/membresias").status_code == 503

    def test_put_settings_invalido_no_altera_el_bloqueo(self, test_client, settings_bypass, monkeypatch):
        """Guardar "local" desde un cliente no cambia nada: ya estaba bloqueado."""
        _build_cliente(monkeypatch)
        resp = test_client.put("/api/settings", json={"dataMode": "local"})
        assert resp.status_code == 403
        assert test_client.get("/api/socios").status_code == 503


class TestBypass5FirstUserAbierto:
    """Bypass 5: ``POST /api/auth/first-user`` creaba un admin sin licencia."""

    def test_crear_admin_responde_403_en_build_de_cliente(self, raw_client, settings_bypass, monkeypatch):
        _build_cliente(monkeypatch)
        resp = raw_client.post(
            "/api/auth/first-user", json={"username": "admin", "password": "secreto123"}
        )
        assert resp.status_code == 403
        assert "administrador del sistema" in resp.json()["detail"]

    def test_no_se_crea_el_usuario(self, raw_client, test_db, settings_bypass, monkeypatch):
        """El 403 tiene que venir ANTES de tocar la base, no después."""
        from backend.models.usuario import Usuario

        _build_cliente(monkeypatch)
        raw_client.post("/api/auth/first-user", json={"username": "admin", "password": "secreto123"})
        assert test_db.query(Usuario).count() == 0

    def test_el_intento_queda_registrado(self, raw_client, settings_bypass, monkeypatch, tmp_path):
        """Requisito del dueño: los intentos quedan registrados."""
        _build_cliente(monkeypatch)
        log = tmp_path / "activacion-intentos.log"
        monkeypatch.setattr("backend.activation.default_settings_dir", lambda: str(tmp_path))
        raw_client.post("/api/auth/first-user", json={"username": "admin", "password": "secreto123"})
        assert log.exists()
        contenido = log.read_text(encoding="utf-8")
        assert "first_user_en_build_cliente" in contenido

    def test_intentos_sobre_rutas_de_dominio_quedan_registrados(
        self, test_client, settings_bypass, monkeypatch, tmp_path
    ):
        log = tmp_path / "activacion-intentos.log"
        monkeypatch.setattr("backend.activation.default_settings_dir", lambda: str(tmp_path))
        _build_cliente(monkeypatch)
        test_client.get("/api/socios")
        test_client.get("/api/pagos")
        contenido = log.read_text(encoding="utf-8")
        assert contenido.count("operacion_bloqueada") == 2

    def test_el_log_nunca_guarda_credenciales(self, raw_client, settings_bypass, monkeypatch, tmp_path):
        """Un log de auditoría que filtra secretos es un agujero nuevo."""
        log = tmp_path / "activacion-intentos.log"
        monkeypatch.setattr("backend.activation.default_settings_dir", lambda: str(tmp_path))
        _build_cliente(monkeypatch)
        raw_client.post(
            "/api/auth/first-user", json={"username": "admin", "password": "PasswordSecreto123"}
        )
        assert "PasswordSecreto123" not in log.read_text(encoding="utf-8")


class TestBypass7TrialLocalEnBuildDeCliente:
    """Bypass 7 (el que la auditoría original no listaba): el trial local.

    En un build de cliente no hay ``SUPABASE_SERVICE_KEY`` —no puede haberla, es
    la credencial que salta todas las RLS—, así que la fila de licencia no se
    podía leer y el veredicto caía al trial, que vive en el SQLite de la máquina
    del cliente. Borrar la base y pedir el trial otra vez era un bypass sin
    conexión, y el trial se "renovaba" cada vez.
    """

    def test_activar_trial_responde_403(self, raw_client, settings_bypass, monkeypatch):
        _build_cliente(monkeypatch)
        resp = raw_client.post("/api/suscripcion/trial", json={"client_id": "canyp_x", "app_id": "canyp"})
        assert resp.status_code == 403
        assert "build de cliente" in resp.json()["detail"]

    def test_activar_trial_no_escribe_nada(self, raw_client, test_db, settings_bypass, monkeypatch):
        from backend.models.licencia_trial import LicenciaTrial

        _build_cliente(monkeypatch)
        raw_client.post("/api/suscripcion/trial", json={"client_id": "canyp_x", "app_id": "canyp"})
        assert test_db.query(LicenciaTrial).count() == 0

    def test_verificar_no_devuelve_trial_inexistente(self, raw_client, settings_bypass, monkeypatch):
        """Sin fila en el registro del operador: sin licencia. No un trial."""
        _build_cliente(monkeypatch)
        cuerpo = raw_client.post(
            "/api/suscripcion/verificar", json={"client_id": "canyp_x", "app_id": "canyp"}
        ).json()
        assert cuerpo["ok"] is False
        assert cuerpo["activo"] is False
        assert cuerpo["error"] == "licencia_no_verificable"

    def test_verificar_ignora_un_trial_manipulado_en_la_base(
        self, raw_client, test_db, settings_bypass, monkeypatch
    ):
        """El ataque real: el cliente inserta la fila del trial a mano.

        Escribiendo directamente en la base —sin pasar por el endpoint— el
        cliente se concede a sí mismo 7 días. Como la fila es suya, el trial
        local no puede ser la fuente del veredicto en un build de cliente.
        """
        from datetime import datetime, timedelta

        from backend.models.licencia_trial import LicenciaTrial

        test_db.add(
            LicenciaTrial(
                client_id="canyp_falso",
                app_id="canyp",
                fecha_inicio=datetime.utcnow(),
                fecha_fin=datetime.utcnow() + timedelta(days=7),
                activo=True,
            )
        )
        test_db.commit()
        _build_cliente(monkeypatch)

        cuerpo = raw_client.post(
            "/api/suscripcion/verificar", json={"client_id": "canyp_falso", "app_id": "canyp"}
        ).json()
        assert cuerpo["ok"] is False
        assert cuerpo["error"] == "licencia_no_verificable"

    def test_borrar_la_base_no_regenera_el_trial(self, raw_client, settings_bypass, monkeypatch):
        """El bypass completo: base vacía + pedir trial. Ahora, 403."""
        _build_cliente(monkeypatch)
        assert (
            raw_client.post("/api/suscripcion/trial", json={"client_id": "canyp_x", "app_id": "canyp"}).status_code
            == 403
        )
        cuerpo = raw_client.post(
            "/api/suscripcion/verificar", json={"client_id": "canyp_x", "app_id": "canyp"}
        ).json()
        assert cuerpo["ok"] is False


# ===========================================================================
# El riesgo #1: el flujo de desarrollo no se rompe
# ===========================================================================


class TestFlujoDeDesarrolloIntacto:
    """Los mismos caminos, con ``CANYP_CLIENT_BUILD`` ausente: todo como antes."""

    def test_rutas_de_dominio_abiertas(self, test_client, settings_bypass, monkeypatch):
        _sin_build_cliente(monkeypatch)
        for _metodo, ruta in RUTAS_DE_DOMINIO:
            resp = test_client.get(ruta)
            assert resp.status_code == 200, f"{ruta} respondió {resp.status_code} en dev"

    def test_first_user_abierto(self, raw_client, settings_bypass, monkeypatch):
        _sin_build_cliente(monkeypatch)
        resp = raw_client.post("/api/auth/first-user", json={"username": "admin", "password": "secreto123"})
        assert resp.status_code == 201
        assert resp.json()["token"]

    def test_trial_local_abierto(self, raw_client, settings_bypass, monkeypatch):
        _sin_build_cliente(monkeypatch)
        resp = raw_client.post("/api/suscripcion/trial", json={"client_id": "canyp_dev", "app_id": "canyp"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_verificar_devuelve_el_trial_local(self, raw_client, settings_bypass, monkeypatch):
        _sin_build_cliente(monkeypatch)
        raw_client.post("/api/suscripcion/trial", json={"client_id": "canyp_dev", "app_id": "canyp"})
        cuerpo = raw_client.post(
            "/api/suscripcion/verificar", json={"client_id": "canyp_dev", "app_id": "canyp"}
        ).json()
        assert cuerpo["ok"] is True
        assert cuerpo["tipo"] == "trial"

    def test_settings_put_local_aceptado(self, test_client, settings_bypass, monkeypatch):
        _sin_build_cliente(monkeypatch)
        resp = test_client.put("/api/settings", json={"dataMode": "local"})
        assert resp.status_code == 200

    def test_activacion_permite_sin_build_de_cliente(self, raw_client, settings_bypass, monkeypatch):
        _sin_build_cliente(monkeypatch)
        cuerpo = raw_client.get("/api/activacion").json()
        assert cuerpo["operacionPermitida"] is True
        assert cuerpo["esBuildCliente"] is False

    def test_exigir_operacion_no_levanta_en_dev(self, settings_bypass, monkeypatch):
        _sin_build_cliente(monkeypatch)
        exigir_operacion()  # no debe lanzar

    def test_dev_puede_operar_sobre_sqlite_local(self, test_client, settings_bypass, monkeypatch):
        """El dev flow completo: local + sin configurar = app funcionando."""
        _sin_build_cliente(monkeypatch)
        assert test_client.get("/api/socios").status_code == 200
        assert test_client.get("/api/dashboard/stats").status_code == 200


# ===========================================================================
# Detalles de la dependencia
# ===========================================================================


class TestDetallesDeLaDependencia:
    def test_veredicto_se_relee_en_cada_peticion(self, test_client, settings_bypass, monkeypatch, tmp_path):
        """Sin caché: si el administrador provisiona, la app abre en el acto.

        Es también la razón de por qué el atajo de la UI no alcanza: el
        veredicto se calcula contra el archivo de ajustes del servidor en cada
        request, no contra nada que el cliente pueda cachear a su favor.
        """
        _build_cliente(monkeypatch)
        assert test_client.get("/api/socios").status_code == 503

        _escribir_settings(
            monkeypatch,
            tmp_path,
            {"dataMode": "remoto", "databaseUrl": URL_REMOTA_VALIDA, "configured": True},
        )
        # La respuesta ya no es 503: cambió el veredicto, no una variable de
        # sesión ni un token. (El 500 de conexión a la base no se comprueba acá:
        # este test es sobre la frontera, no sobre la red.)
        assert test_client.get("/api/socios").status_code != 503

    def test_503_lleva_retry_after(self, test_client, settings_bypass, monkeypatch):
        """Es un estado transitorio esperando al operador, no un error fatal."""
        _build_cliente(monkeypatch)
        assert test_client.get("/api/socios").headers.get("retry-after") == "30"

    def test_settings_store_ignora_bom(self, monkeypatch, tmp_path):
        """Un BOM de Windows no puede hacer caer la instalación a 'sin base'.

        ``load_settings`` abre con ``utf-8-sig`` justamente por esto: un
        PowerShell que reescribe el archivo con BOM no debe convertir un
        ``configured:true`` en un ``configured:false`` silencioso.
        """
        target = tmp_path / "settings.json"
        target.write_bytes(
            b"\xef\xbb\xbf"
            + json.dumps(
                {"dataMode": "remoto", "databaseUrl": URL_REMOTA_VALIDA, "configured": True}
            ).encode("utf-8")
        )
        monkeypatch.setattr("backend.settings_store.default_settings_path", lambda: str(target))
        _build_cliente(monkeypatch)
        assert evaluar_activacion().operacion_permitida is True

    def test_settings_inexistente_en_directorio_inexistente_no_revienta(
        self, monkeypatch, tmp_path
    ):
        """load_settings nunca debe lanzar: un archivo roto no abre la app."""
        monkeypatch.setattr(
            "backend.settings_store.default_settings_path", lambda: str(tmp_path / "no" / "existe.json")
        )
        _build_cliente(monkeypatch)
        assert evaluar_activacion().operacion_permitida is False

    def test_app_settings_por_defecto_es_local_no_configurado(self, tmp_path):
        """El invariante que originó el bypass: default = local. Sigue siendo cierto.

        Lo que cambió no es el default (no se tocan los defaults de desarrollo)
        sino que en un build de cliente ese default ya no abre la app.
        """
        s = load_settings(str(tmp_path / "ausente.json"))
        assert s == AppSettings(dataMode="local", databaseUrl="", configured=False)

    def test_save_settings_no_mezcla_estado_de_activacion(self, tmp_path):
        """La activación no se persiste en el archivo: se deriva, no se declara.

        Si el veredicto fuera un campo del JSON, escribirlo a mano sería un
        bypass más. Al derivarlo del modo de datos + la URL no hay campo que
        falsear.
        """
        path = str(tmp_path / "settings.json")
        save_settings(
            AppSettings(dataMode="local", databaseUrl="", configured=True), path=path
        )
        crudo = json.loads(open(path, encoding="utf-8").read())
        assert set(crudo) == {"dataMode", "databaseUrl", "configured"}
