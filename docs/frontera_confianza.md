# Frontera de confianza: qué decide el cliente y qué decide el servidor

Este documento explica la frontera. La frontera vive en código, en
`backend/activation.py`; este texto la documenta, no la reemplaza.

## El bug que cerró

Con `%APPDATA%\CANYP\settings.json` en
`{"dataMode":"local","databaseUrl":"","configured":false}` —un archivo de texto,
sin tocar una línea de código— la app abría **completa y funcional, sin
licencia**. Seis eslabones lo permitían, y un séptimo que la auditoría original
no había listado (ver más abajo).

## La regla

> En un build de cliente (`CANYP_CLIENT_BUILD=1`), la app **no opera contra
> SQLite local**. Si no hay una base remota válida provisionada, la instalación
> queda en estado de **esperando activación**: sirve la superficie de activación
> y nada más.
>
> El modo local es una herramienta de desarrollo, no un modo operativo.

## Los dos lados, en cinco líneas

1. **El cliente controla** su archivo `settings.json`, su `localStorage` y el
   bundle de JavaScript. Puede editarlo todo; no hay que asumir otra cosa.
2. **El servidor controla** el veredicto de activación
   (`backend/activation.py`), y lo recalcula **en cada petición** leyendo el modo
   de datos y la URL del servidor, más el esquema real de esa URL.
3. **El cliente no puede routearlo** porque el veredicto no se declara: se
   **deriva** de la URL a la que el servidor apunta, y un `settings.json` editado
   a mano cambia *por qué* la app está bloqueada, no si está bloqueada.
4. **La UI no decide**: `LicenseGate` y `ClientBuildGuard` reflejan
   `GET /api/activacion`. Si el frontend mintiera, el backend igual respondería
   503 en cada ruta de dominio. El espejo además **falla cerrado**: sólo un
   `operacionPermitida: true` explícito abre la app, así que un sidecar caído
   muestra el estado y no suelta la app entera.
5. **No hay campo que falsear**: el estado de activación no se persiste. Si fuera
   un campo del JSON, escribirlo a mano sería un bypass más.

## Dónde está cada cosa

| Capa | Archivo | Qué hace |
|---|---|---|
| Frontera | `backend/activation.py` | `evaluar_activacion()`, `es_url_remota_valida()`, `exigir_operacion()` |
| Superficie abierta | `backend/routers/activacion.py` | `GET /api/activacion` — sólo **refleja** el veredicto |
| Aplicación | `backend/main.py` | `Depends(exigir_operacion)` en todas las rutas de dominio |
| Admin | `backend/routers/auth.py` | `first-user` → 403 en build de cliente |
| Licencia | `backend/routers/suscripcion.py` | sin trial local en build de cliente |
| Sidecar | `backend/desktop_run.py` | arranca en local **para mostrar el asistente**, nunca para servir la app |
| UI | `LicenseGate.tsx`, `__root.tsx`, `DataModeWizard.tsx` | reflejan; no deciden |

## Por qué no sirve la defensa en el frontend

El bundle es JavaScript plano. Se parchea en segundos: alcanza con cambiar
`configured` por `true` en el `LicenseGate`, o borrar el `if` del guard. Por eso
**no** hay ofusación ni anti-debug en esta defensa, a propósito: sería esfuerzo
que no compra nada, y ensuciaría el código haciéndolo más difícil de auditar.

La defensa es de arquitectura: **el cliente no tiene los datos.** Los datos del
club viven en un Supabase del operador al que el cliente no tiene acceso. Un
build de cliente sin base remota provisionada no tiene contra qué operar.

## El séptimo bypass: el trial local

Este es el más grave y no estaba en la lista original.

En un build de cliente las credenciales de operador **no están** —no pueden
estarlo, ver `docs/credenciales.md`: una `service_role` dentro del binario salta
todas las RLS—, así que la fila de licencia de Supabase no se puede leer. El
sistema caía entonces al **trial local**, que es una tabla en el SQLite de la
propia máquina del cliente. Borrar la base y volver a pedir el trial era un
bypass **sin conexión y sin límite**, y el trial se "renovaba" cada vez.

El arreglo: en un build de cliente el veredicto de licencia **nunca** sale de
estado local. `POST /api/suscripcion/trial` devuelve 403 y `verificar` corta
antes de mirar la tabla de trials: "no se pudo verificar" es "no hay licencia".
Fuera de un build de cliente el trial sigue igual, porque es una herramienta de
desarrollo legítima.

## `client_id`: por qué no lo anclamos

El `client_id` se genera en el cliente y se guarda en `localStorage`
(`frontend/src/lib/canyp/suscripcion.ts:66-77`, formato `canyp_<timestamp>_<rand>`).
Borrar esa clave regenera un id nuevo, y cada id nuevo sin registro no tenía
licencia: 7 días de trial. Ése era el agujero.

La decisión fue **no proteger la llave y sí eliminar el premio**. En un build de
cliente el trial local no existe: `POST /api/suscripcion/trial` responde 403 y
`verificar` corta antes de mirar la tabla de trials. Un `client_id` regenerado
en un build de cliente no compra nada — devuelve una instalación sin licencia,
que es exactamente el estado de partida. Blindar un valor que ya no vale nada
sería seguridad de mentira; y cualquier esquema de "anclaje" en el cliente
(derivarlo del hardware, firmarlo, hashearlo) es anti-tamper de frontend, que
este proyecto descartó a propósito.

**Qué garantiza**

- Regenerar o borrar el `client_id` no otorga acceso en un build de cliente.
- La fila del trial en la base local no influye en el veredicto, ni si se
  inserta a mano (`TestBypass7TrialLocalEnBuildDeCliente`).
- La primera instalación honesta no se rompe: en un build de cliente no hace
  falta trial para nada, porque la activación es una fila que crea el operador
  en su propio registro.

**Qué NO garantiza — con honestidad**

- **No es identidad de equipo.** El id sigue siendo un valor que el cliente
  posee y puede cambiar. Si un cliente paga y después borra su `localStorage`,
  pierde el acceso a lo que pagó y hay que reasignarle la licencia a mano: es un
  costo de soporte, no una falla de seguridad.
- **No evita el traspaso.** El id es una cadena de texto, no un ancla: se puede
  copiar a otra máquina a mano. El registro del operador es lo único que podría
  atar un id a un equipo, y eso vive en `apps/suscripcion-api`, otro
  repositorio.
- **No protege contra un atacante que edita el bundle.** Nada de lo anterior lo
  hace, y no se pretende: quien reescribe el frontend no necesita el `client_id`,
  necesita datos, y los datos no están en la máquina del cliente.

Cerrar el traspaso y la reasignación requiere un identificador de instalación
emitido por el operador (un artefacto de provisionamiento firmado, o un secreto
por instalación validado contra el endpoint de licencias del operador). Es
infraestructura del lado del operador, en otro repositorio, y por eso queda
reportado y no implementado.

## El residual acotado, y por qué no se cerró acá

Queda un caso: escribir `{"dataMode":"remoto","databaseUrl":"postgresql://
<algo>","configured":true}` apuntando a **una base que el propio cliente
provisionó**. El `settings.json` pasa, el sidecar conecta, y la app abre contra
una base vacía.

Qué **no** alcanza para cerrar eso sin una decisión de producto:

- La URL de la base del club viaja en el `settings.json` del cliente, así que el
  cliente la conoce. Un chequeo sobre el valor de la URL es decorativo: él
  escribe la URL.
- Un `databaseUrl` firmado por el operador, o un secreto por instalación,
  requieren un componente del lado del operador que el sidecar tenga que poder
  consultar. Eso implica trabajo de infraestructura en `apps/suscripcion-api`,
  que es otro repositorio y está fuera del alcance de este trabajo.

Mientras tanto el daño está acotado por construcción: apuntar a una base propia
**no da acceso a los datos de ningún club**, porque los datos de cada club viven
en el proyecto que provisionó el operador, no en una base que el cliente pueda
inventar. Lo que queda es una app funcionando sobre una base vacía, no una app
funcionando con datos ajenos.

**Esto es una decisión de producto y quedó sin tomar a propósito.** Las opciones
son: (a) artefacto de provisionamiento firmado por el operador, (b) un secreto
por instalación contra un endpoint de licencias del operador, o (c) aceptar el
residual. No se eligió ninguna acá.

## Modo dev: por qué no se rompe

Fuera de un build de cliente, `evaluar_activacion()` devuelve permitido **antes
de mirar nada**. No es una condición que haya que acordarse de mantener: es la
primera rama de la función, y su propia cobertura de tests lo fija
(`TestFlujoDeDesarrolloIntacto` en `backend/tests/test_activacion.py`).

`CANYP_CLIENT_BUILD` no lo define nadie a mano: lo inyecta el launcher Tauri
(`frontend/src-tauri/src/lib.rs`) y lo compila el build de escritorio. En dev no
está, y por eso la suite entera corre sin él.

## Registro de intentos

Cada operación bloqueada y cada intento de `first-user` o de activar el trial se
escriben en `activacion-intentos.log`, en el directorio de datos por usuario, con
marca de tiempo, motivo y ruta. Nunca incluye credenciales: los callers pasan
motivo y ruta, no payloads
(`test_el_log_nunca_guarda_credenciales` lo verifica).

El registro no es una defensa —quien tiene la máquina tiene el archivo— pero
convierte un bypass silencioso en algo auditable.

## Cobertura de los bypasses

Cada bypass tiene un test de regresión que falla si alguien lo reintroduce, y un
gemelo que demuestra que el flujo de desarrollo sigue igual.

| Bypass | Test |
|---|---|
| 1. `configured:false` era passthrough | `TestBypass1LicenseGateConfiguredFalse`, `licencia-build-cliente.test.tsx` |
| 2. El guard derivaba de `settings` | `TestBypass2ClientBuildGuardSinVeredictoDelServidor`, `root.test.ts` |
| 3. El sidecar arrancaba en local | `TestBypass3SidecarArrancaEnLocalSinLicencia` |
| 4. El wizard se cerraba | `TestBypass4WizardNoDescartable`, `licencia-build-cliente.test.tsx` |
| 5. `first-user` abierto | `TestBypass5FirstUserAbierto` |
| 6. App completa sin licencia | `TestBypass1LicenseGateConfiguredFalse` (las 10 rutas de dominio) |
| 7. Trial local regenerable | `TestBypass7TrialLocalEnBuildDeCliente` |
| El dev flow no se rompe | `TestFlujoDeDesarrolloIntacto`, `licencia-build-dev.test.tsx` |
