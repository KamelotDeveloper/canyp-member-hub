# Credenciales: instalación vs. privilegio del operador

Supuesto de diseño confirmado: los datos de suscripciones y licencias viven en
un proyecto Supabase que administra el **operador**, y el cliente **no** tiene
acceso a ese proyecto. Por lo tanto ninguna credencial de ese proyecto puede
viajar dentro del binario que se distribuye.

La clasificación vive en código, en `backend/operator_credentials.py`. Este
documento la explica; no la reemplaza.

## Los dos dominios

| Credencial | Dominio | Quién la define | ¿Se distribuye? |
|---|---|---|---|
| `SUPABASE_SERVICE_KEY` | operador | el dueño | **nunca** |
| `MP_ACCESS_TOKEN` | operador | el dueño | **nunca** |
| `DATABASE_URL` | instalación | el cliente (wizard `DataModeWizard` / `PUT /api/settings`) | sí, la del cliente |
| `JWT_SECRET` | instalación | el cliente | sí, la del cliente |
| `SUPABASE_URL` | configuración del operador | el dueño | no habilita nada sola |
| `MP_NOTIFICATION_URL` | configuración del operador | el dueño | no habilita nada sola |

`SUPABASE_SERVICE_KEY` es la más peligrosa: su JWT decodifica a
`{"role":"service_role"}`, que **salta todas las RLS** de las tablas de
suscripciones, planes y códigos de descuento. `MP_ACCESS_TOKEN` es el token de
la cuenta de producción de MercadoPago: quien lo tenga cobra en nombre del
operador.

Lo que el cliente configura desde la app (su URL de base) se mantiene: es suyo
y no habilita nada sobre la infraestructura del operador.

## Por qué `backend/.env` no puede ir en el bundle

`collect_data_files()` de PyInstaller copia **todo** archivo que no sea `.py`
dentro del paquete, dotfiles incluidos. Por eso `collect_all('backend')`
llevaba `backend/.env` al artefacto, y por eso el binario distribuido traía
`SUPABASE_SERVICE_KEY` y `MP_ACCESS_TOKEN` dentro.

Filtrar directorios de build (`venv/`, `dist/`) no alcanza: el secreto está al
lado de los fuentes. Los tres `.spec` filtran ahora por **nombre de archivo**
(`.env` y `.env.*`) y además cortan el build con un error si un secreto llega
a `datas`/`binaries`. `backend/tests/test_build_spec_no_secrets.py` ejecuta los
`.spec` reales y lo verifica.

## Ausencia de credencial = fallo explícito

`backend/desktop_run.py` verifica el inventario al arrancar, antes de levantar
el servidor:

- **Build de cliente** (`CANYP_CLIENT_BUILD=1`): las credenciales de operador
  **no deben existir**. Si aparecen, es una regresión de empaquetado y el
  arranque se corta. Un binario con la `service_role` dentro regala las tablas
  de suscripciones a quien lo instale.
- **Build del operador** (dev o compilación propia): las credenciales de
  operador son **obligatorias**. Si falta alguna, el arranque se corta con un
  mensaje que nombra la variable y qué se rompe.

El mensaje nombra variables, nunca valores: ningún log imprime el valor de un
secreto.

## Cómo inyectarlas en producción — SIN DECIDIR

Hoy las credenciales llegan por `backend/.env` (archivo local, ignorado por git
y excluido del bundle). Con el `.env` fuera del bundle, un build distribuido
necesita otra vía. **Esto es una decisión del dueño; el código no la presupone.**
Opciones, con su costo:

| Opción | A favor | En contra |
|---|---|---|
| **Env vars del launcher** (Tauri las pasa al sidecar) | sin secretos en disco, bajo control del instalador | hay que pensar cómo el instalador las obtiene sin pedirlas al usuario final |
| **Prompt de setup** en el primer arranque | explícito, auditable, nada queda en el repo | fricción para el usuario final, las credenciales quedan en su máquina |
| **Proxy remoto**: el sidecar llama a `suscripcion-api` y nunca ve los secretos | el cliente nunca tiene la `service_role` en ningún momento | hay que implementar los endpoints faltantes en el proxy; es el cambio más grande |
| **Licencia firmada** entregada al build | un artefacto, sin canal extra | requiere emitir y revocar licencias |

Mientras no se elija una, el comportamiento es el seguro: el build de cliente
arranca **sin** credenciales de operador y el de operador **corta** si le faltan.

## Rotación (para el dueño)

Después de rotar, el `.env` viejo y cualquier copia ya distribuida quedan
invalidas por sí solos: no hace falta "desdistribuir" nada, alcanza con que la
clave nueva sea la única válida.

1. **Supabase** — Project Settings → API. Rotar la clave de `service_role`
   (Projects →keys / API Keys). La clave `anon` es pública y puede dejarse.
2. **Supabase** — actualizar RLS: confirmar que las políticas siguen protegiendo
   `suscripciones`, `planes_suscripcion`, `codigos_descuento` y `uso_codigos`.
   Con `service_role` las RLS no aplican, así que la rotación no cambia los
   permisos de quien ya tenga la clave vieja, pero sí invalida su copia.
3. **MercadoPago** — Developer panel → Aplicaciones → (tu app) → credenciales →
   regenerar el token de **producción**. Copiar el nuevo antes de revocar el
   anterior, y actualizar el valor en el entorno que lanza el sidecar.
4. **MercadoPago** — actualizar `MP_ACCESS_TOKEN` en el entorno del operador y
   en el que usa `suscripcion-api` (variable de Vercel).
5. **Vercel (`suscripcion-api`)** — actualizar las variables del proyecto
   desplegado con los valores nuevos.
6. **Cerrado** — verificar que un pago real activa la licencia de punta a punta.

Ningún valor aparece en este repositorio: `.env` está en `.gitignore` y los
`.spec` ahora lo excluyen del bundle.
