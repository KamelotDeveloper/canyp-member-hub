# CANYP Member Hub

Prompt para Lovable — Maqueta Sistema de Gestión CANYP

Copiá y pegá esto directo en Lovable:

Quiero que diseñes, con foco en UX, la maqueta funcional de un sistema de gestión interno (uso administrativo, no para socios finales) para un club náutico llamado CANYP. Es una herramienta de escritorio/web para el personal administrativo del club, que la va a usar todos los días. No es una landing ni un sitio de marketing: priorizá usabilidad, jerarquía clara de información, mínima fricción para tareas repetitivas (cargar un pago, buscar un socio, cambiar un estado de membresía) y consistencia visual entre pantallas.

Quiero que pienses el flujo de uso real, no solo pantallas sueltas: por ejemplo, cómo un administrativo llega desde el dashboard hasta registrar un pago de un socio en 2-3 clicks, o cómo detecta rápido qué socios están vencidos sin tener que buscar manualmente. Simulá la navegación e interacciones completas entre pantallas (no solo el diseño estático), para poder probar el flujo como si fuera la app real.

Antes de armar las pantallas, definí una jerarquía de información clara: qué datos son más importantes de ver primero en cada vista (ej: en la ficha de socio, el estado de sus membresías debería ser lo primero que se vea, no enterrado abajo), y qué acciones son las más frecuentes para que estén más accesibles (menos clicks, botones primarios bien visibles).

Contexto del negocio

El club tiene 2 predios:

Embalse: actividad de balseros (socios con balsas/amarras)

Almafuerte: actividad de cabañeros, guardería de embarcaciones pequeñas, y una subcomisión de windsurf (pagan canon de acceso)

Un mismo socio puede tener actividad en ambos predios a la vez (por ejemplo, ser balsero en Embalse y cabañero en Almafuerte), y en ese caso paga y gestiona cada actividad por separado, como membresías independientes.

Pantallas necesarias

1. Dashboard principal

Resumen general: cantidad de socios activos por área (balseros, cabañeros, guardería, windsurf)

Alertas destacadas: membresías vencidas y por vencer (próximos 30 días), con contador visual

Accesos rápidos a las secciones principales

2. Listado de Socios

Tabla con nombre, DNI, contacto (teléfono/email), predios/áreas en las que tiene membresía activa, y estado general

Buscador y filtros (por predio, por área, por estado de membresía)

Botón "Nuevo socio"

3. Ficha de Socio (detalle)

Datos personales completos (nombre, DNI, dirección, teléfono, email, fecha de alta)

Listado de todas sus membresías (puede tener varias: ej. Balsero-Embalse + Cabañero-Almafuerte), cada una mostrando: área, predio, estado, fecha de vencimiento

Historial de pagos y comprobantes de ese socio

Botones para editar datos, agregar nueva membresía, o dar de baja

4. Gestión de Membresías

Vista tipo tabla/kanban separada por área (Balseros / Cabañeros / Guardería / Windsurf)

Cada membresía muestra: socio asociado, predio, estado (activa/suspendida/vencida/dada de baja), fecha de vencimiento

Acción para cambiar estado (activar, suspender, dar de baja) y editar fecha de vencimiento

Filtro visual rápido para ver "vencidas" y "por vencer"

5. Aranceles (catálogo de precios)

Tabla editable de ítems de arancel por área (ej: "Canon balsa Embalse", "Cuota cabaña Almafuerte", "Guardería embarcación chica", "Canon windsurf")

Cada ítem muestra el monto vigente y permite cargar un nuevo monto (dejando registro de que el anterior queda como histórico, no se borra)

Botón "Nuevo ítem de arancel"

6. Pagos y Comprobantes

Formulario para registrar un nuevo pago: seleccionar socio, seleccionar membresía(s)/área(s) a pagar, se listan automáticamente los ítems de arancel correspondientes con sus montos

Vista previa de comprobante con el detalle de ítems, tipo factura simple

Listado histórico de comprobantes emitidos, con filtro por socio, área y fecha

7. Centro de Notificaciones

Listado de socios con membresía vencida o por vencer, con checkbox para seleccionar a quién notificar

Botones de acción: "Enviar recordatorio por email" y "Enviar por WhatsApp" (este último puede simularse como que genera el mensaje listo para enviar)

Historial de notificaciones enviadas

Estilo visual

Paleta que evoque lo náutico pero de forma sobria: azules, celestes, blanco, algún acento en un color cálido para alertas (naranja/rojo para vencimientos)

Tipografía clara, legible, orientada a datos (no decorativa)

Sidebar de navegación fija con las secciones: Dashboard, Socios, Membresías, Aranceles, Pagos, Notificaciones

Tablas con buen espaciado, badges de color para estados (verde=activa, amarillo=por vencer, rojo=vencida, gris=dada de baja)

Alcance de esta maqueta

No necesita conectarse a una base de datos real ni tener backend funcional de verdad — usá datos de ejemplo (mock data) para poblar tablas, socios, membresías y pagos. Pero sí quiero que la navegación y las interacciones estén simuladas de punta a punta: que se pueda hacer click en "nuevo socio" y completar el formulario, entrar a la ficha de un socio y ver sus membresías, cambiar el estado de una membresía y que se refleje visualmente, simular el registro de un pago y ver el comprobante generado. La idea es poder recorrer los flujos como si fuera la app terminada, para validar la experiencia antes de pasarlo al desarrollo real.

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/315e5fd3-5500-491d-a49c-1d5a34f4d161).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```
