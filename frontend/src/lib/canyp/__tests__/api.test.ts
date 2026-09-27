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
  apiFetchMultipart,
  apiFetchRaw,
  buildUnitPago,
  createArancel,
  createPago,
  deleteArancel,
  deleteMembresia,
  executeImport,
  getImportTemplate,
  getParcelas,
  getSettings,
  getSocios,
  importParcelas,
  previewImport,
  setBatchEstado,
  setBatchVencimiento,
  updateArancel,
  updateMembresiaVencimiento,
  updateSettings,
} from "../api";
import type {
  AppSettings,
  ExecuteResult,
  ImportPayload,
  Parcela,
  PreviewResult,
  Socio,
} from "../types";

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

type GetSettingsReturns = ReturnType<typeof getSettings>;
const _settingsIsPromise: IsPromise<GetSettingsReturns> = true;

type UpdateSettingsReturns = ReturnType<typeof updateSettings>;
const _updateSettingsIsPromise: IsPromise<UpdateSettingsReturns> = true;

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
        numeroSocio: null,
        tieneFoto: false,
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
        numeroSocio: null,
        tieneFoto: false,
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

  it("setBatchVencimiento envía el concepto como query (area | cuota social)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          parcelaId: "p1",
          vencimiento: "2027-01-01",
          concepto: "area",
          actualizadas: 4,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await setBatchVencimiento("p1", "2027-01-01", "cuota social");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/parcelas/p1/vencimiento?concepto=cuota%20social");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ vencimiento: "2027-01-01" });
  });

  it("updateMembresiaVencimiento PUTs to /membresias/{id}/vencimiento", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "m1", vencimiento: "2027-01-01" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await updateMembresiaVencimiento("m1", "2027-01-01");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/membresias/m1/vencimiento");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ vencimiento: "2027-01-01" });
  });

  it("buildUnitPago sends one item per concept + all membresiaIds (RQ 14 / CBM-02)", () => {
    const pago = buildUnitPago({
      titular: { socioId: "a1", membresiaId: "m1" },
      integrantes: [{ membresiaId: "m2" }, { membresiaId: "m3" }],
      medio: "Transferencia",
      items: [
        {
          arancelId: "ar1",
          arancelNombre: "Cuota Balsa",
          montoAplicado: 130000,
          membresiaId: "m1",
          concepto: "area",
        },
        {
          arancelId: "ar2",
          arancelNombre: "Cuota social",
          montoAplicado: 36000,
          membresiaId: "mc1",
          concepto: "cuota social",
        },
        {
          arancelId: "ar3",
          arancelNombre: "Recargo",
          montoAplicado: 5000,
          membresiaId: "m1",
          concepto: "recargo",
        },
      ],
    });
    expect(pago).not.toBeNull();
    expect(pago!.socioId).toBe("a1");
    expect(pago!.items).toHaveLength(3);
    expect(pago!.items.map((i) => i.concepto)).toEqual(["area", "cuota social", "recargo"]);
    // Renueva a TODOS los miembros (titular + integrantes).
    expect(pago!.membresiaIds).toEqual(["m1", "m2", "m3"]);
  });

  it("buildUnitPago no invents a total: el servidor es la autoridad (PAG-01)", () => {
    const pago = buildUnitPago({
      titular: { socioId: "a1", membresiaId: "m1" },
      integrantes: [],
      medio: "Transferencia",
      items: [
        {
          arancelId: "ar1",
          arancelNombre: "Cuota Balsa",
          montoAplicado: 130000,
          membresiaId: "m1",
          concepto: "area",
        },
      ],
    });
    // El importe del cliente es una pista por ítem; el total lo calcula el server.
    expect(pago!.total).toBeUndefined();
  });

  it("buildUnitPago sends the chosen fecha and defaults to today (PAG-02)", async () => {
    const conFecha = buildUnitPago({
      titular: { socioId: "a1", membresiaId: "m1" },
      integrantes: [],
      medio: "Efectivo",
      fecha: "2026-03-15",
      items: [{ arancelId: "ar1", arancelNombre: "X", montoAplicado: 10, membresiaId: "m1" }],
    });
    expect(conFecha!.fecha).toBe("2026-03-15");

    const sinFecha = buildUnitPago({
      titular: { socioId: "a1", membresiaId: "m1" },
      integrantes: [],
      medio: "Efectivo",
      items: [{ arancelId: "ar1", arancelNombre: "X", montoAplicado: 10, membresiaId: "m1" }],
    });
    // Sin fecha explícita, el default vive en createPago (hoy).
    expect(sinFecha!.fecha).toBeUndefined();
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

  it("createPago sends explicit membresiaIds for unit cobro", async () => {
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
      ],
      total: 100,
      membresiaIds: ["m1", "m2", "m3"],
    });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body.items).toHaveLength(1);
    expect(body.membresiaIds).toEqual(["m1", "m2", "m3"]);
    // El id lo genera el backend: el cliente nunca lo envía (seguro para Postgres).
    expect(body.id).toBeUndefined();
  });

  it("createPago derives membresiaIds from items when not provided", async () => {
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
    expect(body.id).toBeUndefined();
  });

  it("createPago sends the chosen fecha (PAG-02)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response("null", { status: 200, headers: { "Content-Type": "application/json" } }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await createPago({
      socioId: "a1",
      medio: "Efectivo",
      fecha: "2026-03-15",
      items: [{ arancelId: "ar1", membresiaId: "m1", montoAplicado: 10, arancelNombre: "X" }],
    });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string).fecha).toBe("2026-03-15");
  });

  it("createPago defaults fecha to today when the caller omits it", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response("null", { status: 200, headers: { "Content-Type": "application/json" } }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await createPago({
      socioId: "a1",
      medio: "Efectivo",
      items: [{ arancelId: "ar1", membresiaId: "m1", montoAplicado: 10, arancelNombre: "X" }],
    });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string).fecha).toBe(new Date().toISOString().slice(0, 10));
  });
});

describe("catálogo de aranceles API (PR4)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("createArancel POSTs concepto + categoria junto con la tupla (ReQ-005)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "a_new" }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createArancel({
      nombre: "Servicio (luz)",
      area: "Guardería",
      predio: "Almafuerte",
      monto: 2500,
      concepto: "servicio",
      categoria: null,
      vigenteDesde: "2026-09-27",
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/aranceles");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      nombre: "Servicio (luz)",
      area: "Guardería",
      predio: "Almafuerte",
      monto: 2500,
      concepto: "servicio",
      categoria: null,
      vigenteDesde: "2026-09-27",
      historico: [],
    });
  });

  it("updateArancel PUTs el re-tag de concepto (el 409 lo decide el backend)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "a1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await updateArancel("a1", { concepto: "cuota social", area: "Guardería" });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/aranceles/a1");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({
      concepto: "cuota social",
      area: "Guardería",
    });
  });

  it("createArancel propaga el detail del 409 de tupla duplicada (ReQ-006)", async () => {
    const detail =
      "Ya existe un arancel con area=Balseros, predio=Embalse, categoria=—, concepto=servicio (id=a_serv_balseros)";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail }), {
          status: 409,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(
      createArancel({
        nombre: "Servicio",
        area: "Balseros",
        predio: "Embalse",
        monto: 5000,
        concepto: "servicio",
        vigenteDesde: "2026-09-27",
      }),
    ).rejects.toMatchObject({ name: "ApiError", status: 409, message: detail });
  });

  it("deleteArancel propaga el detail del 409 con los conteos bloqueantes (ReQ-007)", async () => {
    const detail = "No se puede eliminar el arancel a1: 2 pago_items (pi1, pi4); 1 membresias (m1)";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail }), {
          status: 409,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(deleteArancel("a1")).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      message: detail,
    });
  });
});

describe("settings API (modo de datos)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("getSettings GETs /settings and returns AppSettings", async () => {
    const settings: AppSettings = { dataMode: "local", databaseUrl: "", configured: true };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(settings), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getSettings();
    expect(result).toEqual(settings);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit | undefined];
    expect(url).toBe("/api/settings");
    expect(init?.method ?? "GET").toBe("GET");
  });

  it("updateSettings PUTs {dataMode, databaseUrl} to /settings", async () => {
    const updated: AppSettings = {
      dataMode: "remoto",
      databaseUrl: "postgresql://u:p@h/db",
      configured: true,
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(updated), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await updateSettings({
      dataMode: "remoto",
      databaseUrl: "postgresql://u:p@h/db",
    });
    expect(result).toEqual(updated);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/settings");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({
      dataMode: "remoto",
      databaseUrl: "postgresql://u:p@h/db",
    });
  });
});

describe("import masivo API (PR 3)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("previewImport POSTs multipart FormData with the file and returns a PreviewResult", async () => {
    const preview: PreviewResult = {
      resource: "socios",
      columns: { "Nombre y Apellido": "nombre", Dni: "dni" },
      ignoredColumns: [],
      rows: [
        {
          nombre: "Ana",
          dni: "123",
          telefono: "",
          email: "",
          direccion: "",
          fechaAlta: "2024-01-01",
          activo: true,
        },
      ],
      stats: { total: 1, validas: 1, conErrores: 0, aSaltar: 0 },
      errors: [],
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(preview), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["a,b\n1,2"], "x.csv", { type: "text/csv" });
    const result = await previewImport("socios", file);

    expect(result).toEqual(preview);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/socios/import/preview");
    expect(init.method).toBe("POST");
    // No forced JSON Content-Type; body must be FormData (browser sets boundary).
    expect(typeof init.body).toBe("object");
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("executeImport POSTs {rows} as JSON and returns an ExecuteResult (201)", async () => {
    const execute: ExecuteResult = {
      importados: 1,
      fallidos: 0,
      omitidos: 0,
      rows: [{ fila: 1, outcome: "importado", id: "s1", errores: [] }],
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(execute), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await executeImport("socios", [
      { data: { nombre: "Ana", dni: "123" }, skip: false },
    ]);

    expect(result).toEqual(execute);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/socios/import/execute");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      rows: [{ data: { nombre: "Ana", dni: "123" }, skip: false }],
    });
  });

  it("getImportTemplate returns the XLSX as a Blob from the template endpoint", async () => {
    const blob = new Blob([new Uint8Array([0x50, 0x4b])], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(blob, { status: 200, headers: { "Content-Type": blob.type } }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getImportTemplate("socios");
    expect(result).toBeInstanceOf(Blob);
    expect(result.type).toBe("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit | undefined];
    expect(url).toBe("/api/socios/import/template");
    expect(init?.method ?? "GET").toBe("GET");
  });

  it("apiFetchRaw and apiFetchMultipart throw ApiError using the backend detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "El archivo supera el límite" }), {
          status: 413,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(apiFetchMultipart("/socios/import/preview", new FormData())).rejects.toMatchObject(
      {
        name: "ApiError",
        status: 413,
        message: "El archivo supera el límite",
      },
    );
    await expect(apiFetchRaw("/x")).rejects.toMatchObject({ name: "ApiError", status: 413 });
  });
});
