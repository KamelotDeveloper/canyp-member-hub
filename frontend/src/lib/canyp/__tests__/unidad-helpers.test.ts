/**
 * Runtime + compile-time tests for the pure unidad-dialog helpers.
 *
 * - `buildNuevaUnidadPayload` → RQ 6 / RQ 12: turns the "Nueva unidad" form
 *   into an ImportPayload (first socio = Titular, rest = Integrantes), so the
 *   backend creates the real Parcela + socios + membresías transactionally.
 * - `itemsPorConcepto` → CBM-02: one payment line per ticked concept, replacing
 *   the single-item resolvers that could only ever bill one arancel.
 * - `arancelPorConcepto` / `conceptosDisponibles` → CBM-01 / CS-05: which catalog
 *   row prices a concept, and which concepts a socio can be charged for.
 */

import { describe, expect, it } from "vitest";
import {
  arancelPorConcepto,
  buildNuevaUnidadPayload,
  conceptoDeMembresia,
  conceptosDisponibles,
  esMembresiaCobrable,
  estadoCriticoDe,
  estadoSocioPorParcela,
  filtrarUnidades,
  itemsPorConcepto,
  lineaAPagoItem,
  predioDeTipo,
  totalEstimado,
} from "../unidad-helpers";
import type { Arancel, EstadoSocio, Membresia, ParcelaConMembresias, ParcelaMiembro, UnidadGroup } from "../types";

describe("buildNuevaUnidadPayload", () => {
  it("builds a single-unit ImportPayload with first=Titular, rest=Integrantes", () => {
    const payload = buildNuevaUnidadPayload({
      nombre: "Cabaña E",
      tipo: "cabaña",
      categoria: "Mediana",
      vencimiento: "2027-01-01",
      socios: [
        { nombre: "Ana", dni: "11111111" },
        { nombre: "Luis", dni: "22222222", telefono: "555-1234" },
      ],
    });
    expect(payload).not.toBeNull();
    expect(payload!.unidades).toHaveLength(1);

    const u = payload!.unidades[0]!;
    expect(u.nombre).toBe("Cabaña E");
    expect(u.tipo).toBe("cabaña");
    expect(u.categoria).toBe("Mediana");
    expect(u.predio).toBe("Almafuerte");
    expect(u.miembros).toHaveLength(2);
    expect(u.miembros[0]!.rol).toBe("Titular");
    expect(u.miembros[1]!.rol).toBe("Integrante");
    expect(u.miembros[0]!.socio.nombre).toBe("Ana");
    expect(u.miembros[1]!.socio.dni).toBe("22222222");
    expect(u.miembros[1]!.socio.telefono).toBe("555-1234");
    expect(u.miembros[0]!.vencimiento).toBe("2027-01-01");
  });

  it("returns null when required fields are missing", () => {
    expect(
      buildNuevaUnidadPayload({
        nombre: "  ",
        tipo: "cabaña",
        vencimiento: "",
        socios: [{ nombre: "Ana", dni: "1" }],
      }),
    ).toBeNull();

    expect(
      buildNuevaUnidadPayload({
        nombre: "Cabaña E",
        tipo: "cabaña",
        vencimiento: "",
        socios: [],
      }),
    ).toBeNull();

    expect(
      buildNuevaUnidadPayload({
        nombre: "Cabaña E",
        tipo: "cabaña",
        vencimiento: "",
        socios: [{ nombre: "", dni: "1" }],
      }),
    ).toBeNull();
  });

  it("omits categoria and optional socio fields when absent", () => {
    const payload = buildNuevaUnidadPayload({
      nombre: "Balsa 1",
      tipo: "balsa",
      vencimiento: "",
      socios: [{ nombre: "Luis", dni: "33" }],
    });
    expect(payload).not.toBeNull();
    const u = payload!.unidades[0]!;
    expect(u.categoria).toBeUndefined();
    expect(u.miembros[0]!.socio.telefono).toBeUndefined();
    expect(u.miembros[0]!.vencimiento).toBeUndefined();
    // predio se deriva del tipo: una balsa va a Embalse (regla del dominio)
    expect(u.predio).toBe("Embalse");
  });

  it("propagates an explicit arancelId into the unidad payload", () => {
    const payload = buildNuevaUnidadPayload({
      nombre: "Balsa 2",
      tipo: "balsa",
      vencimiento: "",
      arancelId: "b1",
      socios: [{ nombre: "Luis", dni: "33" }],
    });
    expect(payload).not.toBeNull();
    const u = payload!.unidades[0]!;
    expect(u.arancelId).toBe("b1");
  });

  it("omits arancelId when the form has none selected", () => {
    const payload = buildNuevaUnidadPayload({
      nombre: "Balsa 1",
      tipo: "balsa",
      vencimiento: "",
      socios: [{ nombre: "Luis", dni: "33" }],
    });
    expect(payload).not.toBeNull();
    const u = payload!.unidades[0]!;
    expect(u.arancelId).toBeUndefined();
  });
});

describe("predioDeTipo", () => {
  it("maps balsa -> Embalse and cabaña -> Almafuerte", () => {
    expect(predioDeTipo("balsa")).toBe("Embalse");
    expect(predioDeTipo("cabaña")).toBe("Almafuerte");
  });
});

describe("esMembresiaCobrable", () => {
  function memb(area: Membresia["area"], rol?: Membresia["rol"]): Membresia {
    return {
      id: "m1",
      socioId: "s1",
      area,
      predio: area === "Balseros" ? "Embalse" : "Almafuerte",
      estado: "activa",
      vencimiento: "2099-01-01",
      ...(rol ? { rol } : {}),
    };
  }

  it("a unit membership is only cobrable by its Titular", () => {
    expect(esMembresiaCobrable(memb("Cabañeros", "Titular"))).toBe(true);
    expect(esMembresiaCobrable(memb("Cabañeros", "Integrante"))).toBe(false);
    expect(esMembresiaCobrable(memb("Balseros", "Titular"))).toBe(true);
    expect(esMembresiaCobrable(memb("Balseros", "Integrante"))).toBe(false);
  });

  it("non-unit memberships (Guardería/Windsurf) are always cobrable", () => {
    expect(esMembresiaCobrable(memb("Guardería"))).toBe(true);
    expect(esMembresiaCobrable(memb("Windsurf"))).toBe(true);
  });
});

describe("itemsPorConcepto (CBM-02)", () => {
  const ANCLAS = { area: "m-area", cuota: "m-cuota" };
  const BALSA = { area: "Balseros", predio: "Embalse", categoria: null } as const;
  const CABAÑA_ESP = { area: "Cabañeros", predio: "Almafuerte", categoria: "Especial" } as const;

  /**
   * Catálogo con las cuatro clases de fila que existen en el dominio: precio de
   * área (por unidad o categoría), precio de CUOTA SOCIAL (por socio), precio de
   * SERVICIO (catálogo real) y el carrier de RECARGO (monto 0). Las tres últimas
   * guardan área/predio placeholder porque esas columnas son NOT NULL.
   */
  const CATALOGO: Arancel[] = [
    {
      id: "a_balsa",
      nombre: "Cuota Balsa",
      area: "Balseros",
      predio: "Embalse",
      monto: 130000,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "area",
    },
    {
      id: "a_cab_esp",
      nombre: "Cabaña Especial",
      area: "Cabañeros",
      predio: "Almafuerte",
      categoria: "Especial",
      monto: 120,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "area",
    },
    {
      id: "a_cab_gen",
      nombre: "Cuota Cabañeros",
      area: "Cabañeros",
      predio: "Almafuerte",
      monto: 100,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "area",
    },
    {
      id: "p_cuota",
      nombre: "Cuota social",
      area: "Balseros",
      predio: "Embalse",
      monto: 12000,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "cuota social",
    },
    {
      id: "p_servicio",
      nombre: "Servicio de luz",
      area: "Balseros",
      predio: "Embalse",
      monto: 7300,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "servicio",
    },
    {
      id: "p_recargo",
      nombre: "Recargo",
      area: "Balseros",
      predio: "Embalse",
      monto: 0,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "recargo",
    },
  ];

  /** Balsa de 4 integrantes: cuota ×4 y área por unidad (CS-03, PAG-01). */
  const CUATRO = { anclas: ANCLAS, miembros: 4, lugar: BALSA, aranceles: CATALOGO };

  it("compone una línea por concepto marcado (CBM-02)", () => {
    const lineas = itemsPorConcepto(["area", "cuota social"], CUATRO);
    expect(lineas.map((l) => l.concepto)).toEqual(["area", "cuota social"]);
  });

  it("multiplica la cuota social por los miembros de la unidad (CS-03)", () => {
    const cuota = itemsPorConcepto(["cuota social"], CUATRO)[0]!;
    expect(cuota.factor).toBe(4);
    expect(cuota.monto).toBe(48000); // 12.000 × 4
    expect(cuota.arancelId).toBe("p_cuota");
    expect(cuota.membresiaId).toBe("m-cuota");
  });

  it("el área NO se multiplica por integrantes: una balsa es importe fijo", () => {
    const area = itemsPorConcepto(["area"], CUATRO)[0]!;
    expect(area.factor).toBe(1);
    expect(area.monto).toBe(130000);
  });

  it("nada marcado compone cero líneas (deja el confirmar deshabilitado)", () => {
    expect(itemsPorConcepto([], CUATRO)).toHaveLength(0);
  });

  it("el recargo usa el importe tipeado y el arancel carrier", () => {
    const [recargo] = itemsPorConcepto(["recargo"], { ...CUATRO, recargo: 10000 });
    expect(recargo!.arancelId).toBe("p_recargo");
    expect(recargo!.monto).toBe(10000);
    expect(recargo!.montoAplicado).toBe(10000);
    expect(recargo!.factor).toBe(1);
  });

  it("un recargo sin importe no compone línea en vez de dejar que el servidor rechace", () => {
    expect(itemsPorConcepto(["recargo"], CUATRO)).toHaveLength(0);
    expect(itemsPorConcepto(["recargo"], { ...CUATRO, recargo: 0 })).toHaveLength(0);
  });

  it("el servicio toma el precio de catálogo y no se multiplica por miembros", () => {
    const servicio = itemsPorConcepto(["servicio"], CUATRO)[0]!;
    expect(servicio.monto).toBe(7300);
    expect(servicio.factor).toBe(1);
    // Sin ajuste, el montoAplicado no viaja: el servidor ya usa el catálogo.
    expect(servicio.montoAplicado).toBeUndefined();
  });

  it("un servicio ajustado manda el importe solo para este cobro", () => {
    const servicio = itemsPorConcepto(["servicio"], { ...CUATRO, servicio: 9500 })[0]!;
    expect(servicio.monto).toBe(9500);
    expect(servicio.montoAplicado).toBe(9500);
  });

  it("una línea sin ancla no se emite", () => {
    expect(
      itemsPorConcepto(["cuota social"], { ...CUATRO, anclas: { area: "m-area" } }),
    ).toHaveLength(0);
  });

  it("una línea sin fila de catálogo se cae y el resto del cobro sigue", () => {
    const sinServicio = CATALOGO.filter((a) => a.concepto !== "servicio");
    const lineas = itemsPorConcepto(["servicio", "area"], { ...CUATRO, aranceles: sinServicio });
    expect(lineas.map((l) => l.concepto)).toEqual(["area"]);
  });

  it("el área resuelve la categoría exacta y, si no, el catch-all", () => {
    const exacta = itemsPorConcepto(["area"], { ...CUATRO, lugar: CABAÑA_ESP })[0]!;
    expect(exacta.arancelId).toBe("a_cab_esp");
    expect(exacta.monto).toBe(120);

    const catchAll = itemsPorConcepto(["area"], {
      ...CUATRO,
      lugar: { area: "Cabañeros", predio: "Almafuerte", categoria: "Grande" },
    })[0]!;
    expect(catchAll.arancelId).toBe("a_cab_gen");
  });

  it("totalEstimado suma las líneas compuestas", () => {
    const lineas = itemsPorConcepto(["area", "cuota social", "recargo"], {
      ...CUATRO,
      recargo: 5000,
    });
    expect(totalEstimado(lineas)).toBe(130000 + 48000 + 5000);
  });
});

describe("lineaAPagoItem (debt 5a: montoAplicado solo para recargo/servicio ajustado)", () => {
  const CATALOGO: Arancel[] = [
    {
      id: "a_balsa",
      nombre: "Cuota Balsa",
      area: "Balseros",
      predio: "Embalse",
      monto: 130000,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "area",
    },
    {
      id: "p_cuota",
      nombre: "Cuota social",
      area: "Balseros",
      predio: "Embalse",
      monto: 12000,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "cuota social",
    },
    {
      id: "p_servicio",
      nombre: "Servicio de luz",
      area: "Balseros",
      predio: "Embalse",
      monto: 7300,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "servicio",
    },
    {
      id: "p_recargo",
      nombre: "Recargo",
      area: "Balseros",
      predio: "Embalse",
      monto: 0,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "recargo",
    },
  ];
  const LUGAR = { area: "Balseros", predio: "Embalse", categoria: null } as const;
  const OPCIONES = {
    anclas: { area: "m-area", cuota: "m-cuota" },
    miembros: 4,
    lugar: LUGAR,
    aranceles: CATALOGO,
  };

  it("área y cuota social no envían montoAplicado (el servidor usa el catálogo)", () => {
    const items = itemsPorConcepto(["area", "cuota social"], OPCIONES).map(lineaAPagoItem);
    for (const item of items) {
      expect(item).not.toHaveProperty("montoAplicado");
    }
  });

  it("el recargo envía el importe tipeado", () => {
    const [l] = itemsPorConcepto(["recargo"], { ...OPCIONES, recargo: 10000 });
    expect(lineaAPagoItem(l!).montoAplicado).toBe(10000);
  });

  it("el servicio sin ajuste no envía montoAplicado (catálogo vigente del servidor)", () => {
    const [l] = itemsPorConcepto(["servicio"], OPCIONES);
    expect(lineaAPagoItem(l!)).not.toHaveProperty("montoAplicado");
  });

  it("el servicio ajustado envía el importe solo para este cobro", () => {
    const [l] = itemsPorConcepto(["servicio"], { ...OPCIONES, servicio: 9500 });
    expect(lineaAPagoItem(l!).montoAplicado).toBe(9500);
  });

  it("preserva arancelId, membresiaId, nombre y concepto", () => {
    const [l] = itemsPorConcepto(["area"], OPCIONES);
    expect(lineaAPagoItem(l!)).toEqual({
      arancelId: "a_balsa",
      membresiaId: "m-area",
      arancelNombre: "Cuota Balsa",
      concepto: "area",
    });
  });
});

describe("arancelPorConcepto (CBM-01)", () => {
  const BASE: Arancel[] = [
    {
      id: "a_balsa",
      nombre: "Cuota Balsa",
      area: "Balseros",
      predio: "Embalse",
      monto: 130000,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "area",
    },
    {
      id: "p_cuota",
      nombre: "Cuota social",
      area: "Balseros",
      predio: "Embalse",
      monto: 12000,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "cuota social",
    },
  ];

  it("encuentra la cuota social POR CONCEPTO, no por su área placeholder", () => {
    // El placeholder de la fila coincide con un área real: buscarla por
    // área+predio devolvería la cuota de la balsa. El concepto es la clave.
    const cuota = arancelPorConcepto(BASE, "cuota social");
    expect(cuota?.id).toBe("p_cuota");
    expect(cuota?.monto).toBe(12000);
  });

  it("una fila sin concepto cuenta como área (default de la columna)", () => {
    const legacy: Arancel[] = [{ ...BASE[0]!, id: "a_legacy", concepto: undefined }];
    expect(
      arancelPorConcepto(legacy, "area", { area: "Balseros", predio: "Embalse", categoria: null })
        ?.id,
    ).toBe("a_legacy");
  });

  it("desempata por id ascendente, igual que el servidor", () => {
    const dos: Arancel[] = [
      { ...BASE[1]!, id: "p_zzz" },
      { ...BASE[1]!, id: "p_aaa" },
    ];
    expect(arancelPorConcepto(dos, "cuota social")?.id).toBe("p_aaa");
  });

  it("sin fila para el concepto devuelve undefined", () => {
    expect(arancelPorConcepto(BASE, "servicio")).toBeUndefined();
    expect(arancelPorConcepto(BASE, "area")).toBeUndefined();
  });
});

describe("conceptosDisponibles (CS-05)", () => {
  function memb(over: Partial<Membresia> & { id: string }): Membresia {
    return {
      socioId: "s1",
      area: "Balseros",
      predio: "Embalse",
      estado: "activa",
      vencimiento: "2099-01-01",
      concepto: "area",
      ...over,
    };
  }

  const CATALOGO: Arancel[] = [
    {
      id: "p_cuota",
      nombre: "Cuota social",
      area: "Balseros",
      predio: "Embalse",
      monto: 12000,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "cuota social",
    },
    {
      id: "p_servicio",
      nombre: "Servicio",
      area: "Balseros",
      predio: "Embalse",
      monto: 7300,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "servicio",
    },
    {
      id: "p_recargo",
      nombre: "Recargo",
      area: "Balseros",
      predio: "Embalse",
      monto: 0,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "recargo",
    },
  ];

  it("un socio de Windsurf cobra CUOTA SOCIAL y nada más", () => {
    const miembros = [
      memb({ id: "m-w", area: "Windsurf", predio: "Almafuerte", concepto: "cuota social" }),
    ];
    expect(conceptosDisponibles(miembros, CATALOGO)).toEqual(["cuota social"]);
  });

  it("no ofrece cuota social si el socio no tiene esa membresía", () => {
    // El servidor rechaza con 422 una cuota sin membresía que la ancle.
    expect(conceptosDisponibles([memb({ id: "m-a" })], CATALOGO)).toEqual([
      "area",
      "servicio",
      "recargo",
    ]);
  });

  it("no ofrece servicio ni recargo sin fila de catálogo que los pricen", () => {
    expect(conceptosDisponibles([memb({ id: "m-a" })], [])).toEqual(["area"]);
  });

  it("un socio normal ve área, cuota social, servicio y recargo", () => {
    const miembros = [
      memb({ id: "m-a" }),
      memb({ id: "m-c", area: "Balseros", concepto: "cuota social" }),
    ];
    expect(conceptosDisponibles(miembros, CATALOGO)).toEqual([
      "cuota social",
      "area",
      "servicio",
      "recargo",
    ]);
  });

  it("conceptoDeMembresia: sin concepto servido, una membresía es de área", () => {
    expect(conceptoDeMembresia(memb({ id: "m-x", concepto: undefined }))).toBe("area");
    expect(conceptoDeMembresia(memb({ id: "m-y", concepto: "cuota social" }))).toBe("cuota social");
  });
});

// ---------------------------------------------------------------------------
// estadoCriticoDe (EST-01) — estado más urgente de una lista de estados servidos
// ---------------------------------------------------------------------------

describe("estadoCriticoDe (EST-01)", () => {
  it("devuelve el estado más urgente de una lista servida", () => {
    expect(estadoCriticoDe(["Socio activo", "Inactivo — revisar"])).toBe("Inactivo — revisar");
    expect(estadoCriticoDe(["Socio activo", "Socio activo — revisar"])).toBe(
      "Socio activo — revisar",
    );
    expect(estadoCriticoDe(["Socio activo"])).toBe("Socio activo");
    expect(estadoCriticoDe(["Solo cuota social"])).toBe("Solo cuota social");
  });

  it("una unidad al día (solo 🟢) queda en Socio activo", () => {
    expect(estadoCriticoDe(["Socio activo", "Socio activo"])).toBe("Socio activo");
  });

  it("cae a Socio activo para una lista vacía (grupo sin miembros)", () => {
    expect(estadoCriticoDe([])).toBe("Socio activo");
  });
});

// ---------------------------------------------------------------------------
// filtrarUnidades (EST-01) — filtros Todas / Vencidas / Alertas
// ---------------------------------------------------------------------------

describe("filtrarUnidades (EST-01)", () => {
  function g(parcelaId: string, nombre: string): UnidadGroup {
    return { parcelaId, nombre, predio: "Almafuerte", categoria: null, members: [] };
  }

  const todas: UnidadGroup[] = [
    g("pV", "Inactiva"),
    g("pR", "A revisar"),
    g("pA", "Activa"),
  ];
  const estadoPorParcela: Record<string, EstadoSocio> = {
    pV: "Inactivo — revisar",
    pR: "Socio activo — revisar",
    pA: "Socio activo",
  };
  const estadoDe = (gr: UnidadGroup): EstadoSocio => estadoPorParcela[gr.parcelaId ?? ""] ?? "Socio activo";

  it("'todas' devuelve todas las unidades", () => {
    expect(filtrarUnidades(todas, "todas", estadoDe)).toHaveLength(3);
  });

  it("'vencidas' devuelve solo 🔴 Inactivo — revisar", () => {
    const result = filtrarUnidades(todas, "vencidas", estadoDe);
    expect(result.map((x) => x.nombre)).toEqual(["Inactiva"]);
  });

  it("'alertas' combina 🔴 y ⚠️, excluyendo 🟢", () => {
    const result = filtrarUnidades(todas, "alertas", estadoDe);
    expect(result.map((x) => x.nombre).sort()).toEqual(["A revisar", "Inactiva"]);
  });

  it("devuelve vacío cuando ninguna unidad matchea el filtro", () => {
    expect(filtrarUnidades([g("pA", "Activa")], "vencidas", estadoDe)).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// estadoSocioPorParcela (D5) — estado unit-scoped servido por /api/membresias/parcelas
// ---------------------------------------------------------------------------

describe("estadoSocioPorParcela (D5)", () => {
  function miembro(id: string, estadoSocio: EstadoSocio): ParcelaMiembro {
    return {
      id,
      socioId: `s-${id}`,
      area: "Balseros",
      predio: "Embalse",
      estado: "activa",
      vencimiento: "2099-01-01",
      estadoSocio,
    };
  }

  function parcela(id: string, miembros: ParcelaMiembro[]): ParcelaConMembresias {
    return {
      parcela: { id, nombre: `Balsa ${id}`, tipo: "balsa", predio: "Embalse" },
      membresias: miembros,
    };
  }

  it("un titular al día + un integrante vencido marcan ⚠️ a la unidad (D5)", () => {
    const mapa = estadoSocioPorParcela([
      parcela("p1", [
        miembro("m1", "Socio activo"), // titular, propia área al día
        miembro("m2", "Socio activo — revisar"), // integrante, área vencida
      ]),
    ]);
    expect(mapa.get("p1")).toBe("Socio activo — revisar");
  });

  it("una unidad con toda su área al día queda 🟢", () => {
    const mapa = estadoSocioPorParcela([
      parcela("p1", [miembro("m1", "Socio activo"), miembro("m2", "Socio activo")]),
    ]);
    expect(mapa.get("p1")).toBe("Socio activo");
  });

  it("una cuota vencida manda sobre un área al día (🔴 gana a ⚠️)", () => {
    const mapa = estadoSocioPorParcela([
      parcela("p1", [
        miembro("m1", "Inactivo — revisar"),
        miembro("m2", "Socio activo — revisar"),
      ]),
    ]);
    expect(mapa.get("p1")).toBe("Inactivo — revisar");
  });

  it("una parcela sin miembros cae a 🟢 Socio activo", () => {
    const mapa = estadoSocioPorParcela([parcela("p1", [])]);
    expect(mapa.get("p1")).toBe("Socio activo");
  });

  it("devuelve un Map vacío sin parcelas", () => {
    expect(estadoSocioPorParcela([]).size).toBe(0);
  });
});
