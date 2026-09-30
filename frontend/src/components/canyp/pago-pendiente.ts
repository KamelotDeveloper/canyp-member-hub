/**
 * Estado del pago a medio camino, para el rescate por navegador.
 *
 * El problema: en Tauri, el Checkout Pro abre en el navegador EXTERNO. Cuando el
 * usuario paga, MercadoPago redirige a `/exito` del backend — no a la app. La app
 * no se entera de nada, se queda con la fila en `pendiente` y el gate de licencia
 * la bloquea aunque el usuario haya pagado.
 *
 * Lo único que la app sí conserva es el `preference_id` que le devolvió
 * `/crear-preferencia`. Ese id es el hilo para retomar: alcanza para preguntarle a
 * MercadoPago qué pago corresponde y confirmar la licencia.
 *
 * Vive en localStorage (y no en estado de React) porque tiene que sobrevivir al
 * remount, y al reinicio de la app, que es justo cuando el usuario vuelve del
 * navegador. Sin eso, volver del pago reiniciaba el estado y se perdía el rastro.
 */

/** Clave de localStorage. */
export const PAGO_PENDIENTE_KEY = "canyp_pago_pendiente";

export interface PagoPendiente {
  preference_id: string;
  /** Para mostrar "1 mes" en la pantalla, no para decidir nada. */
  plan?: string;
  /** Epoch ms del momento en que se abrió el checkout. */
  iniciado: number;
}

/**
 * Un pago se puede ignorar después de esto.
 *
 * Sin tope, un `preference_id` olvidado en localStorage haría que la app consultara
 * MercadoPago en cada arranque, para siempre. Dos horas es de sobra para que un
 * pago se aclare.
 */
const VIGENCIA_MS = 2 * 60 * 60 * 1000;

/** Guarda el pago a la vista. Tolera que localStorage no exista (modo privado). */
export function guardarPagoPendiente(preferenceId: string, plan?: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      PAGO_PENDIENTE_KEY,
      JSON.stringify({ preference_id: preferenceId, plan, iniciado: Date.now() }),
    );
  } catch {
    // Sin localStorage no hay rescate automático; el webhook sigue siendo la vía
    // principal, así que no vale la pena romper el flujo de compra por esto.
  }
}

/** El pago pendiente, o null si no hay, está vencido o está corrupto. */
export function leerPagoPendiente(): PagoPendiente | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(PAGO_PENDIENTE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    const { preference_id, plan, iniciado } = parsed as Partial<PagoPendiente>;
    if (typeof preference_id !== "string" || preference_id.length === 0) return null;
    if (typeof iniciado !== "number") return null;
    if (Date.now() - iniciado > VIGENCIA_MS) {
      limpiarPagoPendiente();
      return null;
    }
    return {
      preference_id,
      ...(typeof plan === "string" ? { plan } : {}),
      iniciado,
    };
  } catch {
    limpiarPagoPendiente();
    return null;
  }
}

export function limpiarPagoPendiente(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(PAGO_PENDIENTE_KEY);
  } catch {
    // Idem: si no se puede limpiar, se reintenta en el próximo arranque.
  }
}
