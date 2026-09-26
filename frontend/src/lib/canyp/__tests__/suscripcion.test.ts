/**
 * Tests para el servicio de suscripción (Fase 1): client_id local, planes,
 * preferencia MP normalizada y verificación/activación de trial.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  APP_ID,
  CLIENT_ID_KEY,
  activarTrial,
  crearPreferencia,
  getClientId,
  obtenerPlanes,
  verificarSuscripcion,
  type PlanesResponse,
} from "../suscripcion";

function okJson(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
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
