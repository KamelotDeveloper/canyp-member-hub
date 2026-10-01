# Contrato del webhook de suscripción (`suscripcion-api`)

El backend ya habla un vocabulario único y un proyecto único. Este documento es
lo que el webhook tiene que cumplir para que un pago **active** la licencia.

**Estado: el webhook todavía NO cumple esto.** Vive en otro repositorio
(`apps/suscripcion-api`, desplegado en Vercel) y sus cambios no están en este
commit. Hasta que se aplique, se sigue cobrando sin activar.

## Los tres cortes

### 1. Prefijo `canyp:` no reconocido

`backend/routers/suscripcion.py` manda
`external_reference = "canyp:<client_id>"`. El webhook solo procesaba si el
valor empezaba con `ERP-`, así que **ninguna** notificación de CANYP entraba al
`if`: se respondía `{received: true}` y no se escribía nada.

El contrato real es `${app_id}:${client_id}` (split por el primer `:`), donde
`app_id` hoy es `canyp` y antes era `ordo`. Hay que reconocer ambos y no romper
el flujo `ERP-` si algún cliente lo sigue usando.

### 2. `activa` vs `activo`

El webhook escribía `estado: 'activa'`. El backend exigía `estado in ("activo",
"prueba")`. La fila quedaba en un valor que la verificación nunca reconocía.

Enum canónico (definido en `backend/subscription_status.py`, es el que hay que
escribir):

| valor | habilita licencia | significado |
|---|---|---|
| `pendiente` | no | pago iniciado, todavía no aprobado |
| `prueba` | sí | acceso gratuito (trial o plan de precio 0) |
| `activo` | sí | pago aprobado |
| `expirado` | no | vencida |

`activa` queda solo como **sinónimo de lectura** en el backend, para no dejar
afuera a quien ya pagó con el webhook viejo. No debe escribirse nunca más.

### 3. Dos proyectos de Supabase

El backend leía del proyecto del operador; el webhook escribía en otro
proyecto distinto (el de Ordo-ERP), hardcodeado en el código y duplicado en el
`.env` de ese repo. El pago se registraba donde el backend no miraba.

**Fuente de verdad: el proyecto del operador**, el mismo que usa
`backend/config.py` (`SUPABASE_URL`, inyectada por entorno). El webhook tiene
que escribir ahí. Cambiarlo es cambiar la variable de entorno del proyecto
desplegado en Vercel, no el código.

## Idempotencia (obligatorio)

MercadoPago reintenta el webhook. Hoy el webhook recalcula
`fecha_expiracion = now + plan` en cada entrega: **cada reintongo regalaría un
período más**. Con eso, reintentar no es inofensivo.

La fila se identifica por `mp_payment_id` (el backend lo guarda al crear la
preferencia). Si la fila ya está en `activo` **con ese mismo `mp_payment_id`**,
la entrega no debe reescribir `fecha_expiracion` ni extender el período: se
responde éxito y listo. El backend ya tiene esta misma regla en
`_activar_suscripcion_por_pago`, y es la que hay que replicar.

## Verificación antes de activar

El webhook hoy activa con que `topic === 'payment' && status === 'approved'`,
tomando el estado del **cuerpo de la notificación**, que no está firmado.

Hay que verificar contra la API: `GET /v1/payments/{id}` con
`MP_ACCESS_TOKEN` y recién entonces activar. Si esa consulta no se puede hacer,
**fallar cerrado** (responder error para que MercadoPago reintente), nunca
activar a ciegas.

## Preflight que hay que hacer antes de desplegar

Estos pasos son del dueño, no del código:

1. Confirmar que el webhook tiene `MP_ACCESS_TOKEN` de producción. Si no, no
   puede verificar y queda en fail-closed, es decir **no activa**.
2. Apuntar `NEXT_PUBLIC_SUPABASE_URL` (Vercel) al proyecto del operador.
3. Rotar la `service_role` y el `MP_ACCESS_TOKEN` (ver
   [`credenciales.md`](./credenciales.md)).

Con el paso 1 pendiente, el webhook pasa de "activa sin verificar" a "no
activa". Es la posición segura, pero significa que hay que completarlo antes de
volver a vender.
