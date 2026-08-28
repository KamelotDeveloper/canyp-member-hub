/**
 * Compile-time + runtime tests for the CANYP API client.
 *
 * The type checks verify exports exist with correct signatures.
 * The runtime tests exercise ApiError and apiFetch behavior.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  apiFetch,
  buildUnitPago,
  createPago,
  deleteMembresia,
  getParcelas,
  getSocios,
  importParcelas,
  setBatchEstado,
  setBatchVencimiento,
} from "../api";
import type { ImportPayload, Parcela, Socio } from "../types";

// ---------------------------------------------------------------------------
// Compile-time: exports exist with the expected shapes
// ---------------------------------------------------------------------------

type ApiFetchIsFn = typeof apiFetch extends (...args: never[]) => unknown ? true : false;
const _apiFetchCheck: ApiFetchIsFn = true;

type GetSociosReturns = ReturnType<typeof getSocios>;
type GetParcelasReturns = ReturnType<typeof getParcelas>;

type IsPromise<T> = T extends Promise<unknown> ? true : false;
const _sociosIsPromise: IsPromise<GetSociosReturns> = true;
const _parcelasIsPromise: IsPromise<GetParcelasReturns> = true;

type DeleteMembresiaReturns = ReturnType<typeof deleteMembresia>;
const _deleteMembresiaIsPromise: IsPromise<DeleteMembresiaReturns> = true;

type ApiErrorExtendsError = ApiError extends Error ? true : false;
const _apiErrorCheck: ApiErrorExtendsError = true;

describe("ApiError", () => {
  it("exposes status and message and extends Error", () => {
    const err = new ApiError(404, "Not found");
    expect(err.status).toBe(404);
    expect(err.message).toBe("Not found");
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe("ApiError");
  });
});

describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("throws ApiError with the backend detail on non-ok response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "boom" }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(apiFetch("/socios")).rejects.toMatchObject({
      name: "ApiError",
      status: 500,
      message: "boom",
    });
  });

  it("throws ApiError with statusText when body has no detail", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 404 })));

    await expect(apiFetch("/missing")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
    });
  });

  it("returns parsed JSON on success", async () => {
    const socios: Socio[] = [
      {
        id: "s1",
        nombre: "A",
        dni: "123",
        telefono: "+54",
        email: "a@b.c",
        direccion: "Calle 1",
        fechaAlta: "2024-01-01",
        activo: true,
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(socios), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(apiFetch<Socio[]>("/socios")).resolves.toEqual(socios);
  });

  it("returns undefined for 204 No Content", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));

    await expect(apiFetch<void>("/socios/x")).resolves.toBeUndefined();
  });
});

describe("getSocios / getParcelas", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("getSocios is an async function returning a promise of Socios", async () => {
    expect(typeof getSocios).toBe("function");
    const socios: Socio[] = [
      {
        id: "s1",
        nombre: "A",
        dni: "123",
        telefono: "+54",
        email: "a@b.c",
        direccion: "Calle 1",
        fechaAlta: "2024-01-01",
        activo: true,
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(socios), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const result = await getSocios();
    expect(result).toEqual(socios);
  });

  it("getParcelas is an async function returning a promise of Parcelas", async () => {
    expect(typeof getParcelas).toBe("function");
    const parcelas: Parcela[] = [{ id: "p1", nombre: "Lote 1", tipo: "balsa", predio: "Embalse" }];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(parcelas), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const result = await getParcelas();
    expect(result).toEqual(parcelas);
  });
});

describe("deleteMembresia", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("DELETEs /membresias/{id} and resolves for 204", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await deleteMembresia("m1");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/membresias/m1");
    expect(init.method).toBe("DELETE");
  });
});

describe("unidades compartidas API (PR 3)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("importParcelas POSTs the payload to /parcelas/import and returns created ids", async () => {
    const payload: ImportPayload = {
      unidades: [
        {
          nombre: "Cabaña E",
          tipo: "cabaña",
          categoria: "Mediana",
          predio: "Almafuerte",
          miembros: [{ socio: { nombre: "Ana", dni: "1" }, rol: "Titular" }],
        },
      ],
    };
    const response = { parcelas: ["p1"], socios: ["s1"], membresias: ["m1"] };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await importParcelas(payload);
    expect(result).toEqual(response);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/parcelas/import");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual(payload);
  });

  it("setBatchEstado POSTs to /parcelas/{id}/estado", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ parcelaId: "p1", estado: "vencida" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await setBatchEstado("p1", "vencida");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/parcelas/p1/estado");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ estado: "vencida" });
  });

  it("setBatchVencimiento PUTs to /parcelas/{id}/vencimiento", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ parcelaId: "p1", vencimiento: "2027-01-01" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await setBatchVencimiento("p1", "2027-01-01");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/parcelas/p1/vencimiento");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ vencimiento: "2027-01-01" });
  });

  it("buildUnitPago maps each member to its OWN membresiaId (RQ 14)", () => {
    const pago = buildUnitPago({
      titular: { socioId: "a1", membresiaId: "m1" },
      integrantes: [{ membresiaId: "m2" }],
      medio: "Transferencia",
      items: [
        { arancelId: "ar1", arancelNombre: "Mensualidad", montoAplicado: 100, membresiaId: "m1" },
        { arancelId: "ar1", arancelNombre: "Mensualidad", montoAplicado: 100, membresiaId: "m2" },
      ],
    });
    expect(pago).not.toBeNull();
    expect(pago!.socioId).toBe("a1");
    expect(pago!.items.map((i) => i.membresiaId)).toEqual(["m1", "m2"]);
    expect(pago!.total).toBe(200);
  });

  it("buildUnitPago returns null without a titular or without items", () => {
    expect(
      buildUnitPago({
        titular: { socioId: "", membresiaId: "m1" },
        integrantes: [],
        medio: "Efectivo",
        items: [{ arancelId: "ar1", arancelNombre: "X", montoAplicado: 10, membresiaId: "m1" }],
      }),
    ).toBeNull();
    expect(
      buildUnitPago({
        titular: { socioId: "a1", membresiaId: "m1" },
        integrantes: [],
        medio: "Efectivo",
        items: [],
      }),
    ).toBeNull();
  });

  it("createPago keeps distinct membresiaIds per item (multi-item pago)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response("null", { status: 200, headers: { "Content-Type": "application/json" } }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await createPago({
      socioId: "a1",
      medio: "Transferencia",
      items: [
        { arancelId: "ar1", membresiaId: "m1", montoAplicado: 100, arancelNombre: "Mensualidad" },
        { arancelId: "ar1", membresiaId: "m2", montoAplicado: 100, arancelNombre: "Mensualidad" },
      ],
      total: 200,
    });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body.items.map((i: { membresiaId: string }) => i.membresiaId)).toEqual(["m1", "m2"]);
    expect(body.membresiaIds).toEqual(["m1", "m2"]);
  });
});
