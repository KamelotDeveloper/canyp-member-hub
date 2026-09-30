/**
 * Tests para el servicio de suscripción (Fase 1): client_id local, planes,
 * preferencia MP normalizada y verificación/activación de trial.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  APP_ID,
  CLIENT_ID_KEY,
  activarTrial,
  confirmarPago,
  confirmarPreferencia,
  consultarEstadoPago,
  consultarEstadoPagoPreferencia,
  crearPreferencia,
  esperarConfirmacionPreferencia,
  getClientId,
  obtenerPlanes,
  verificarSuscripcion,
  type EstadoPagoResponse,
  type PlanesResponse,
} from "../suscripcion";

function okJson(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function errorJson(status: number, detail: string): Response {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("getClientId", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("genera y persiste un id canyp_ con prefijo y sin dos puntos", () => {
    const id = getClientId();
    expect(id.startsWith(`canyp_`)).toBe(true);
    expect(id).not.toContain(":");
    expect(window.localStorage.getItem(CLIENT_ID_KEY)).toBe(id);
    expect(getClientId()).toBe(id);
  });

  it("reutiliza el id persistido entre llamadas", () => {
    window.localStorage.setItem(CLIENT_ID_KEY, "canyp_fijo");
    expect(getClientId()).toBe("canyp_fijo");
  });
});

describe("obtenerPlanes", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("GETea /suscripcion/planes?app_id=canyp", async () => {
    const planes: PlanesResponse = {
      ok: true,
      planes: [{ id: "canyp_1_mes", nombre: "1 mes", descripcion: "", precio: 120000, dias: 30 }],
      prueba_gratis: { id: "gratis", nombre: "Trial", descripcion: "", precio: 0, dias: 7 },
    };
    const fetchMock = vi.fn().mockResolvedValue(okJson(planes));
    vi.stubGlobal("fetch", fetchMock);

    const result = await obtenerPlanes();
    expect(result).toEqual(planes);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit | undefined];
    expect(url).toBe(`/api/suscripcion/planes?app_id=${APP_ID}`);
    expect(init?.method ?? "GET").toBe("GET");
  });
});

describe("crearPreferencia", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTea client_id, app_id y plan; expone init_point (modo real)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        okJson({ success: true, init_point: "https://mp/init", preapproval_plan_id: "p1" }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await crearPreferencia("canyp_1", "canyp_1_mes");
    expect(result.init_point).toBe("https://mp/init");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/suscripcion/crear-preferencia");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      client_id: "canyp_1",
      app_id: "canyp",
      plan: "canyp_1_mes",
    });
  });

  it("normaliza payment_url a init_point (modo mock, sin Supabase)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(okJson({ success: true, payment_url: "https://mock/pago" }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await crearPreferencia("canyp_1", "canyp_1_mes");
    expect(result.init_point).toBe("https://mock/pago");
    expect(result.payment_url).toBe("https://mock/pago");
  });

  it("no inventa init_point si el backend no devuelve URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson({ success: false, message: "error" }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await crearPreferencia("canyp_1", "canyp_1_mes");
    expect(result.init_point).toBeUndefined();
  });
});

describe("verificarSuscripcion / activarTrial", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("verificarSuscripcion POSTea a /suscripcion/verificar", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(okJson({ ok: true, activo: true, tipo: "licencia" }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await verificarSuscripcion("canyp_1");
    expect(result).toMatchObject({ ok: true, activo: true });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/suscripcion/verificar");
    expect(JSON.parse(init.body as string)).toEqual({ client_id: "canyp_1", app_id: "canyp" });
  });

  it("activarTrial POSTea a /suscripcion/trial", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(okJson({ ok: true, activo: true, tipo: "trial", dias_restantes: 7 }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await activarTrial("canyp_1");
    expect(result).toMatchObject({ ok: true, tipo: "trial", dias_restantes: 7 });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/suscripcion/trial");
    expect(JSON.parse(init.body as string)).toEqual({ client_id: "canyp_1", app_id: "canyp" });
  });
});

describe("confirmarPago / consultarEstadoPago", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("confirmarPago manda payment_id, app_id y client_id", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(okJson({ success: true, verificado: true, idempotente: false }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await confirmarPago("9001", "canyp_1");
    expect(result.verificado).toBe(true);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/suscripcion/confirmar-pago?");
    expect(url).toContain("payment_id=9001");
    expect(url).toContain(`app_id=${APP_ID}`);
    expect(url).toContain("client_id=canyp_1");
    expect(init.method).toBe("POST");
  });

  it("consultarEstadoPago escapa el payment_id y no manda client_id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson({ ok: true, activo: true }));
    vi.stubGlobal("fetch", fetchMock);

    await consultarEstadoPago("a b&c=d");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/suscripcion/estado-pago?payment_id=a%20b%26c%3Dd");
    expect(init?.method ?? "GET").toBe("GET");
  });
});

describe("confirmarPreferencia", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("es el camino de Tauri: manda preference_id y client_id", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(okJson({ success: true, verificado: true, idempotente: true }));
    vi.stubGlobal("fetch", fetchMock);

    await confirmarPreferencia("3001", "canyp_1");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/suscripcion/confirmar-preferencia?");
    expect(url).toContain("preference_id=3001");
    expect(url).toContain("client_id=canyp_1");
    expect(init.method).toBe("POST");
  });

  it("consultarEstadoPagoPreferencia usa el parámetro preference_id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson({ ok: true, activo: false }));
    vi.stubGlobal("fetch", fetchMock);

    await consultarEstadoPagoPreferencia("3001");

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe("/api/suscripcion/estado-pago?preference_id=3001");
  });
});

describe("esperarConfirmacionPreferencia", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const activa: EstadoPagoResponse = {
    ok: true,
    activo: true,
    estado: "activo",
    plan: "canyp_1_mes",
    fecha_expiracion: "2026-12-31T00:00:00Z",
    dias_restantes: 30,
  };

  it("reintenta mientras el pago no esté acreditado y corta al confirmarse", async () => {
    // Primero la preferencia todavía no tiene pago (404), después 502 al
    // verificar, y recién ahí activa. Ese es el caso real al volver del
    // navegador: la app no puede rendirse en el primer no.
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(errorJson(404, "todavia no tiene un pago acreditado"))
      .mockResolvedValueOnce(errorJson(502, "No se pudo verificar"))
      .mockResolvedValueOnce(okJson({ success: true, verificado: true, idempotente: false }))
      .mockResolvedValueOnce(okJson(activa));
    vi.stubGlobal("fetch", fetchMock);

    const result = await esperarConfirmacionPreferencia("3001", "canyp_1", {
      intentos: 5,
      delayMs: 0,
    });

    expect(result.activo).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("no reintenta un rechazo: propaga el error de una", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(errorJson(403, "El pago corresponde a otro cliente"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      esperarConfirmacionPreferencia("3001", "canyp_1", { intentos: 5, delayMs: 0 }),
    ).rejects.toThrow();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("falla con un mensaje accionable si se agotan los intentos", async () => {
    // `mockImplementation`, no `mockResolvedValue`: el body de un Response se
    // puede leer una sola vez, y con el mismo objeto el segundo intento recibe
    // una respuesta vacía en vez del 404.
    const fetchMock = vi
      .fn()
      .mockImplementation(() => errorJson(404, "todavia no tiene un pago acreditado"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      esperarConfirmacionPreferencia("3001", "canyp_1", { intentos: 2, delayMs: 0 }),
    ).rejects.toThrow(/todavia no tiene un pago acreditado/);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
