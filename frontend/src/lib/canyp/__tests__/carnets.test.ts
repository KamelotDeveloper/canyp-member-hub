/**
 * Tests for the carnet helpers (carnets.ts) and the foto endpoints
 * (subirFoto / getSocioFoto in api.ts), mirroring api.test.ts style.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { getSocioFoto, subirFoto } from "../api";
import { agruparPorHojas, areasDeSocio, iniciales } from "../carnets";
import type { Membresia, Socio } from "../types";

function membresia(overrides: Partial<Membresia>): Membresia {
  return {
    id: "m1",
    socioId: "s1",
    area: "Balseros",
    predio: "Embalse",
    estado: "activa",
    vencimiento: "2027-01-01",
    ...overrides,
  };
}

function socio(overrides: Partial<Socio> = {}): Socio {
  return {
    id: "s1",
    nombre: "Juan Pérez",
    dni: "30111222",
    telefono: "+54",
    email: "",
    direccion: "",
    fechaAlta: "2024-01-01",
    activo: true,
    numeroSocio: "000123",
    tieneFoto: false,
    ...overrides,
  };
}

describe("iniciales", () => {
  it("takes the initial of the first two words, uppercased", () => {
    expect(iniciales("Juan Pérez")).toBe("JP");
    expect(iniciales("ana maria gomez")).toBe("AM");
  });

  it("falls back for single words and empty names", () => {
    expect(iniciales("Messi")).toBe("M");
    expect(iniciales("   ")).toBe("?");
  });
});

describe("areasDeSocio", () => {
  it("returns unique non-baja areas for a socio", () => {
    const ms = [
      membresia({ area: "Balseros" }),
      membresia({ id: "m2", area: "Windsurf", estado: "baja" }),
      membresia({ id: "m3", area: "Balseros" }),
      membresia({ id: "m4", socioId: "otro", area: "Guardería" }),
    ];
    expect(areasDeSocio(ms, "s1")).toEqual(["Balseros"]);
  });

  it("returns empty for a socio with none", () => {
    expect(areasDeSocio([], "s1")).toEqual([]);
    expect(areasDeSocio([membresia({ socioId: "otro" })], "s1")).toEqual([]);
  });
});

describe("agruparPorHojas", () => {
  it("splits into batches of 8 leaving a partial last page", () => {
    const items = Array.from({ length: 18 }, (_, i) => `s${i}`);
    const hojas = agruparPorHojas(items, 8);
    expect(hojas.map((h) => h.length)).toEqual([8, 8, 2]);
  });

  it("handles empty input", () => {
    expect(agruparPorHojas([], 8)).toEqual([]);
  });
});

describe("foto endpoints", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("subirFoto POSTs multipart field `foto` to /socios/{id}/foto", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ tieneFoto: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["img"], "foto.jpg", { type: "image/jpeg" });
    const result = await subirFoto("s1", file);

    expect(result).toEqual({ tieneFoto: true });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/socios/s1/foto");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    const body = init.body as FormData;
    expect(body.get("foto")).toBe(file);
    // No forced JSON Content-Type: the browser sets the multipart boundary.
    const contentType =
      init.headers instanceof Headers
        ? init.headers.get("Content-Type")
        : (init.headers as Record<string, string> | undefined)?.["Content-Type"];
    expect(contentType).toBeUndefined();
  });

  it("getSocioFoto GETs the raw JPEG bytes as a Blob", async () => {
    const blob = new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: "image/jpeg" });
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(blob, { status: 200, headers: { "Content-Type": "image/jpeg" } }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getSocioFoto("s1");
    expect(result).toBeInstanceOf(Blob);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit | undefined];
    expect(url).toBe("/api/socios/s1/foto");
    expect(init?.method ?? "GET").toBe("GET");
  });

  it("getSocioFoto throws ApiError(404) when the socio has no photo", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Socio s1 not found or has no foto" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(getSocioFoto("s1")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
    });
  });
});
