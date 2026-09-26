# Hallazgos de la prueba integral — CANYP

Registro acumulado de bugs / mejoras detectados durante la prueba de UI y backend.
Se aplicaron TODOS juntos (13/09/2026) y se verificaron en la app instalada.

## Nota de método (UI Automation)
La interacción UI se hizo con Windows UI Automation + clicks reales + teclado.
Artefactos de la automatización que NO son bugs de la app:
- `SetValue` de UIA no dispara el `onChange` de React (el texto se ve pero no entra al estado). Usar clicks reales + SendKeys en su lugar.
- Los IDs de la API son UUIDs de 9+ chars; al borrar usar el ID completo.
- En algunos formularios el click inicial debe caer en el campo para que SendKeys vaya a la ventana correcta (`SetForegroundWindow`).

## Bug #1 — Socio activo sin membresías se muestra "Dada de baja"

- **Severidad**: media (visual/estado incorrecto en el padrón)
- **Dónde**: `frontend/src/routes/socios.index.tsx:104`
- **Evidencia**: Socio recién dado de alta (API: `activo=true`) aparece como "Dada de baja" en la columna "Estado general" del padrón.
- **Causa**: cuando el socio no tiene membresías, `estados` queda vacío y el fallback es
  ```ts
  const general = prioridad.find((p) => estados.includes(p)) ?? "baja";
  ```
  El campo `socio.activo` que manda el backend no se usa en el cálculo del estado general.
- **Solución propuesta**:
  ```ts
  const general =
    prioridad.find((p) => estados.includes(p)) ?? (s.activo ? "activa" : "baja");
  ```
- **Estado**: APLICADO y VERIFICADO en la app instalada (13/09/2026). Un socio activo sin membresías muestra "Activa" en el padrón (creado vía API para verificar; luego eliminado).

## Bug #2 — Membresía de unidad creada desde la ficha nunca es cobrable (rol vacío)

- **Severidad**: media-alta (flujo de cobro bloqueado para socios con membresía de unidad creada a mano).
- **Evidencia**: socio Maria Prueba UI con membresía Balseros/Embalse activa (vence 2027-09-12, arancel Cuota Balsa). Abrir "Registrar pago" desde la ficha → "El socio no tiene membresías activas." La API devuelve la membresía con `rol=""`.
- **Causa**: el modal "Nueva membresía" de la ficha (`socios.$socioId.tsx`) crea la membresía solo con `estado: "activa"` — no expone rol. La regla `esMembresiaCobrable` (`unidad-helpers.ts:54-58`) exige `rol === "Titular"` para áreas de unidad (Balseros/Cabañeros) → con rol vacío la membresía queda incobrable. `/pagos` (`pagos.tsx:104`) filtra con la misma regla.
- **Propuesta de solución**: exponer un selector de rol (Titular/Integrante) en el modal "Nueva membresía" cuando el área es de unidad, o que el backend asigne `rol="Titular"` al crear membresías sueltas. Requiere decisión de negocio.
- **Decisión (13/09/2026)**: opción A — selector de rol en el modal.
- **Estado**: APLICADO y VERIFICADO en la app instalada. El modal muestra "Rol: Titular/Integrante" solo para Balseros/Cabañeros; con Guardería/Windsurf el selector desaparece. Al crear la membresía queda `rol="Titular"` en la API y el modal "Registrar pago" ya la lista como cobrable (antes decía "El socio no tiene membresías activas"). La membresía de verificación se eliminó después.

## Bug #3 — La UI no ofrece "Dar de baja" al socio (el 409 recomienda hacerlo)

- **Severidad**: media (UX — el flujo alternativo que la regla de negocio recomienda no existe en pantalla).
- **Evidencia**: socio con pagos → botón "Eliminar" → el backend responde 409 "No se puede eliminar el socio porque tiene pagos registrados. Podés darlo de baja para conservar el historial." pero la ficha **no tiene** acción "Dar de baja" (solo Eliminar, Nueva membresía, Editar datos, Registrar pago). El backend sí soporta la baja vía `PUT /api/socios/{id} {"activo":false}`.
- **Dónde**: `socios.$socioId.tsx` (acción del socio), `socios.py:171-179` (mensaje 409 que recomienda la baja).
- **Propuesta de solución**: agregar la acción "Dar de baja" (PUT activo=false) en la ficha del socio (o en el padrón), coherente con el mensaje del 409.
- **Estado**: APLICADO y VERIFICADO en la app instalada. La ficha muestra "Dar de baja" (con diálogo de confirmación) cuando el socio está activo; al confirmar, la API recibe `activo=false`, aparece el badge "Dada de baja" y el botón cambia a "Reactivar". Reactivar devuelve `activo=true`. La ficha conserva historial (no borra nada).

## Verificado sin bug (UI)

- Navegación de las 7 secciones (Dashboard, Socios, Membresías, Aranceles, Pagos, Notificaciones, Ajustes) — OK.
- Modal "Nuevo socio": abre, llena campos, "Dar de alta" crea el socio (verificado por API: seb82229 Maria Prueba UI).
- Modal "Nueva membresía": abre con Predio/Área/Vencimiento/Detalle/Arancel; selecciona arancel desde dropdown; crea la membresía (verificado por API).
- Pantalla Aranceles: tabla con columnas y botón "Nuevo ítem de arancel".
- Ficha de socio: datos personales, botones de acción, secciones Membresías y Pagos vacías sin error.
- Crear arancel desde UI: el backend recibe `monto` correctamente; el `nombre` del ítem se envía desde el estado del formulario (`aranceles.tsx` conecta `value`+`onChange`). El nombre vacío observado durante la prueba fue un artefacto de la automatización, no un bug.
- Con datos de prueba, el select de arancel muestra "Cuota Balsa — $45.000" y se puede elegir.
- Flujo **Registrar pago** desde la ficha: el modal lista las membresías cobrables, seleccionar una muestra el arancel resuelto, "Registrar y emitir comprobante" crea el Pago (nro 0001-00000001, total $20.000, Transferencia) y renueva la membresía 12 meses (2027 → 2028-09-12). Verificado por API.
- **Editar socio**: modal con los campos poblados, guarda cambios (teléfono → 3515556677 verificado por GET).
- **Eliminar socio con pagos**: el diálogo de confirmación abre; el backend responde 409 y la UI muestra toast "Error al eliminar el socio". El socio NO se borra. La regla contable funciona desde la UI (el mensaje 409 recomienda dar de baja, pero la UI no ofrece esa acción — ver Bug #3).
- **Membresías**: tarjetas por área con contadores, filtros Todas/Por vencer/Vencidas/Alertas, botones Importar / + Nueva unidad / Exportar. Botón "Cobrar" → modal "Cobrar unidad" correcto (arancel según el área activa).
- **Notificaciones**: pantalla con botones Enviar por WhatsApp / Enviar recordatorio por email / Quitar selección y tabla Contacto/Membresía/Vencimiento/Estado (vacía sin membresías vencidas — correcto).
- **Ajustes**: muestra modo NUBE (remoto, base en Supabase) con opciones Local/Remoto.
- **Dashboard**: tarjetas por área con socios activos, contadores de vencidas / vencen en 30 días, accesos Buscar socio / Registrar pago.
- **Exportar socios**: dropdown CSV/XLSX → ambos se descargan a `Downloads\canyp\`. XLSX verificado (hoja con Maria y todos sus campos); CSV verificado UTF-8 con BOM (acentos correctos).
- **Importar socios**: modal de 3 pasos (Subir archivo → Revisar y editar → Confirmar) con "Descargar plantilla" — abre correcto.
- **Crear ítem de arancel desde la UI** (con la técnica correcta click real + teclado): se creó arancel "Cuota Prueba UI" Balseros/Embalse $30.800 vigente 2026-09-13, verificado por API. El formulario guarda bien nombre/monto (los nombres vacíos vistos antes eran artefacto de `SetValue`).
- **Eliminar ítem de arancel desde la UI**: el diálogo de confirmación («Se va a eliminar "…". Los pagos ya emitidos conservan el monto y nombre guardados en su comprobante») dispara la mutación y el borrado se refleja en API. El botón Eliminar de la fila necesita InvokePattern (el click real a veces no dispara el AlertDialog en esta zona).
- **Pagos / comprobante**: la pantalla lista el pago (0001-00000001, María, Cuota Guardería, Transferencia, $20.000) con filtros Socio/Área/Desde y botón "Ver comprobante" que abre el comprobante emitido completo (logo, número, fecha, socio + DNI, ítem, total, medio, botones Imprimir/Cerrar).
- **Filtros del padrón**: búsqueda por texto (filtra y muestra "No hay socios que coincidan"), predio (Embalse/Almafuerte), área (Balseros/Cabañeros/Guardería/Windsurf), estado (Activa/Por vencer/Vencida/Suspendida/Dada de baja). Todos filtran bien.
- **Botones de pantallas secundarias**: Histórico de montos (muestra ítem vigente + "Sin actualizaciones previas"), Editar ítem de arancel (campos completos), Nuevo socio ("Dar de alta" con campos obligatorios), Nueva unidad (con Rol Titular en la primera fila), Nueva membresía de Guardería (sin rol — correcto para área de grupo), Importar membresías (flujo de subida), verificado que los botones de envío de Notificaciones existen (sin vencimientos pendientes no hay acción real).
- **Filtros de Pagos**: dropdown de Socio (Todos los socios / Maria Prueba UI) filtra bien la tabla; filtro "Desde" implementado correctamente en `pagos.tsx` (`if (fDesde && p.fecha < fDesde)` — comparación de strings YYYY-MM-DD; su control de fecha no es automatizable por UIA pero la lógica es correcta por código).
- **Importar membresías y Exportar membresías**: el Importar de UnidadesPanel (área Balseros/Cabañeros) dispara el file picker de subida; el Exportar de Membresías usa el mismo ExportButton verificado en Socios (dropdown CSV/XLSX → Downloads\canyp).