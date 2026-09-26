# AGENT.md — CANYP Sistema de Gestión

## Rol del agente

Sos el desarrollador backend/full-stack de este proyecto, trabajando junto
a Giuliano bajo metodología spec-driven development. Tu responsabilidad es
implementar el backend (FastAPI + SQLite) y conectar el frontend ya
generado por Lovable con datos y lógica reales — no rediseñar producto ni
tomar decisiones de negocio por tu cuenta.

Comportamiento esperado:
- Priorizá corrección en el manejo de dinero (pagos, montos, comprobantes)
  por sobre velocidad de entrega. Este es un sistema que maneja cobros
  reales de un club, no una maqueta.
- Si una regla de negocio no está clara o el pedido de una feature entra
  en conflicto con lo ya definido en este archivo, preguntá antes de
  improvisar una interpretación propia.
- No inventes herramientas, librerías o alcance que no se haya acordado.
- Explicá brevemente decisiones técnicas no triviales (ej. por qué elegís
  cierta estrategia de migración o de concurrencia), pero sin extenderte
  de más — Giuliano prefiere avanzar con supuestos razonables antes que
  frenar todo con preguntas, salvo que el punto sea realmente ambiguo.
- Nunca commitear ni pushear sin instrucción explícita en el momento.

## Contexto del proyecto

Aplicación interna de gestión para el Club Náutico CANYP. Administra socios,
membresías, aranceles, pagos y notificaciones entre dos predios: **Embalse**
y **Almafuerte**.

Es una app de **uso interno**, un solo rol de usuario (administración), sin
necesidad de RBAC. Prioridad: UX clara, mínima fricción para tareas
repetitivas, cero ambigüedad en el manejo de dinero.

## Estructura del repo (mono-repo)

```
/frontend   → app generada con Lovable (React 19 + TS), NO reescribir estructura de UI
/backend    → FastAPI + SQLite, desarrollo nuevo desde cero
```

Mismo patrón que el proyecto Ordo ERP.

## Stack

**Frontend** (heredado de Lovable, no tocar salvo integración con backend real):
- React 19 + TypeScript
- TanStack Router + TanStack Start
- TanStack Query para data fetching
- Tailwind CSS v4 (variables CSS)
- shadcn/ui (Button, Card, Dialog, Input, Label, Select, Table, Checkbox, Sonner/toast)
- Lucide React (iconos)
- IBM Plex Sans / IBM Plex Mono

**Backend** (a construir):
- FastAPI
- SQLite
- Empaquetado final: Tauri 2 (backend como sidecar local)
- n8n como orquestador de notificaciones (email + WhatsApp)

## Package manager

**Usar SIEMPRE pnpm.** Nunca npm ni npx. Todos los comandos de instalación,
scripts y ejecución del frontend van con `pnpm` (`pnpm install`, `pnpm dev`,
`pnpm add <pkg>`, etc.). Si en algún momento se sugiere un comando con
`npm`/`npx`, está mal — corregir a `pnpm`/`pnpm dlx`.

## Git

El agente **nunca** hace `commit` ni `push` sin instrucción explícita del
usuario en el momento. Dejar los cambios preparados (staged o no) y avisar
qué se hizo; el commit lo maneja Giuliano manualmente.

## Modelo de dominio (fuente de verdad: backend)

```
Socio: id, nombre, dni (único), telefono, email, direccion, fechaAlta, activo
Membresia: id, socioId, area, predio, estado, vencimiento, detalle
Arancel: id, nombre, area, predio, monto, vigenteDesde, historico[]
Pago: id, numero, socioId, fecha, medio, items[], total, membresiaIds[]
PagoItem: id, pagoId, arancelId, membresiaId, montoAplicado
Notificacion: id, socioId, canal, fecha, motivo, mensaje

Predio = "Embalse" | "Almafuerte"
Area = "Balseros" | "Cabañeros" | "Guardería" | "Windsurf"
EstadoMembresia = "activa" | "suspendida" | "vencida" | "baja"
EstadoSocio = "Socio activo" | "Socio activo — revisar"
              | "Inactivo — revisar" | "Solo cuota social"  (calculado, ver regla 1)
```

## Reglas de negocio (definidas, no reinterpretar)

1. **Estado de socio** (4 estados, calculados en el backend desde los
   `vencimiento`; nunca persistidos):
   - El backend es la única autoridad y el frontend consume el valor que le
     llega por la API, sin recalcularlo.
   - 🟢 `Socio activo`: cuota social al día y (sin membresía de área o área al
     día).
   - ⚠️ `Socio activo — revisar`: cuota social al día pero área vencida. Aplica
     a **toda la unidad** (titular e integrantes), no solo al titular: la
     unidad se paga una vez y su estado es el `vencimiento` más vencido de sus
     miembros.
   - 🔴 `Inactivo — revisar`: cuota social vencida, o su membresía de cuota
     social en `suspendida`/`baja`. Sigue visible, exportable y cobrable: no
     se borra ni se oculta nada.
   - `Solo cuota social`: sin membresía de área y cuota al día.
   - `vencimiento == hoy` cuenta como al día. El `suspendida`/`baja` de una
     membresía de **área** no afecta el estado.
   - No hay ventana de anticipación ni estado intermedio: sólo deuda real.
   - Son SOLO control visual: no borran datos ni impiden cobrar. Al pagar, el
     estado se restaura solo en la siguiente lectura (es un recálculo, no un
     flag guardado).
   - Implementación: `backend/services/estado_socio.py` —
     `calcular_estado_socio(cuota, area, hoy)` puro + `estados_socio`, que
     resuelve un listado entero en UNA consulta agrupada. Lo usan el padrón, la
     ficha de socio, el listado de membresías/unidad y el dashboard. Nunca
     duplicar la lógica en el frontend.

2. **Comprobantes de pago**: numeración secuencial única y global
   (`0001`, `0002`, ...), no separada por predio. Debe generarse de forma
   atómica en el backend (no calcular "max+1" desde el cliente) para evitar
   colisiones si hay dos cobros simultáneos.

3. **Al registrar un pago**: cada membresía incluida se renueva al
   ciclo mensual 10 → 10 y pasa a `activa`.
   - `vencimiento = max(vencimiento, dia10(fecha_pago))`, donde
     `dia10(f)` es el primer día 10 **en o después** de `f`: el día 10 de ese
     mes si `f.día <= 10`, o el día 10 del mes siguiente si `f.día > 10`.
   - Un pago posterior al día 10 cubre el período en curso (15/09 → 10/10,
     20/11 → 10/12). El atraso se penaliza con recargo manual, nunca
     acortando el período cubierto.
   - Un segundo cobro dentro del mismo período no adelanta la cobertura, y
     una membresía ya pagada por adelantado nunca se acorta.
   - Implementación: `backend/services/renovacion.py` (`dia10` +
     `renovar_membresias`).

4. **Aranceles**: al actualizar un monto, el valor anterior se guarda en
   `historico[]` con su fecha de vigencia. El monto aplicado a un pago
   queda **congelado** en `PagoItem.montoAplicado` al momento del cobro —
   no se recalcula retroactivamente si el arancel cambia después.

5. **Auth**: login simple, un solo rol (administración). Sin niveles de
   permiso diferenciados.

6. **Notificaciones**:
   - Email: enviado vía n8n (backend dispara el webhook, n8n gestiona el
     envío real).
   - WhatsApp v1: generación de link `wa.me` con mensaje precargado
     (manual, como en el mock de Lovable). Automatización vía WhatsApp
     Business API queda para una v2, no implementar ahora.

## Datos mock / seed

Mantener el criterio del prompt original: al menos 10 socios, 15
membresías, 6 aranceles, 4 pagos, con vencimientos relativos a la fecha
actual (para que el dashboard muestre alertas realistas). Usar esto como
seed script del backend (SQLite), no como datos hardcodeados en el
frontend.

## Metodología de trabajo (SDD)

- Spec-driven development: antes de tocar código, escribir/actualizar el
  spec de la feature en cuestión.
- Cambios grandes se dividen en specs chicos y verificables.
- No asumir requisitos no confirmados — si algo del dominio no está claro,
  preguntar antes de implementar, no improvisar.

## Cosas que NO hacer

- No reescribir la estructura de rutas/componentes del frontend generado
  por Lovable salvo que sea estrictamente necesario para conectar con el
  backend real.
- No usar npm/npx bajo ninguna circunstancia.
- No commitear/pushear sin instrucción explícita.
- No dejar la lógica de estado de membresía duplicada en frontend y
  backend.
- No recalcular montos de pagos históricos cuando cambia un arancel.
