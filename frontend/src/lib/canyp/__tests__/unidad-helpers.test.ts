/**
 * Runtime + compile-time tests for the pure unidad-dialog helpers.
 *
 * - `buildNuevaUnidadPayload` → RQ 6 / RQ 12: turns the "Nueva unidad" form
 *   into an ImportPayload (first socio = Titular, rest = Integrantes), so the
 *   backend creates the real Parcela + socios + membresías transactionally.
 * - `itemsPorArancel` → ReQ-001 / ReQ-012: one payment line per ticked
 *   `arancelId`, keyed by catalog row (two apartes of a place = two lines).
 * - `arancelesDisponibles` / `membresiaDeLugar` / `arancelPorConcepto` →
 *   ReQ-002 / ReQ-003 / ReQ-004: which catalog rows a place may tick, which
 *   membership anchors a place, and the dual place/concept resolution rule.
 */

import { describe, expect, it } from "vitest";
import {
  arancelPorConcepto,
  arancelesDisponibles,
  buildNuevaUnidadPayload,
  conceptoDeMembresia,
  esMembresiaCobrable,
  estadoCriticoDe,
  estadoSocioPorParcela,
  filtrarUnidades,
  formatearAvisosCobro,
  itemsPorArancel,
  lineaAPagoItem,
  membresiaDeLugar,
  predioDeTipo,
  totalEstimado,
  type LugarCobrable,
  type LugarCobro,
  type OpcionesItemsPorArancel,
} from "../unidad-helpers";
import type {
  Arancel,
  EstadoSocio,
  Membresia,
  ParcelaConMembresias,
  ParcelaMiembro,
  UnidadGroup,
} from "../types";

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

describe("itemsPorArancel (ReQ-001 / ReQ-012)", () => {
  const ANCLAS = { area: "m-area", cuota: "m-cuota" };

  /** Dos lugares reales: una balsa y una cabaña especial, cada uno con su ancla. */
  const LUGARES: LugarCobrable[] = [
    { area: "Balseros", predio: "Embalse", categoria: null, membresiaId: "m-area" },
    { area: "Cabañeros", predio: "Almafuerte", categoria: "Especial", membresiaId: "m-cab" },
  ];

  /**
   * Catálogo con las cuatro clases de fila que existen en el dominio: precio de
   * área, CUOTA SOCIAL (por socio), SERVICIO (ahora POR LUGAR, dos apartes del
   * mismo lugar) y el carrier de RECARGO (monto 0). Los conceptos por lugar
   * llevan su área/predio real; cuota social y recargo guardan un placeholder.
   */
  const CATALOGO: Arancel[] = [
    {
      id: "a_balsa",
      nombre: "Amarre",
      area: "Balseros",
      predio: "Embalse",
      monto: 18500,
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
      id: "p_cuota",
      nombre: "Cuota social",
      area: "Guardería",
      predio: "Almafuerte",
      monto: 12000,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "cuota social",
    },
    {
      id: "p_serv_luz",
      nombre: "Servicio (luz)",
      area: "Balseros",
      predio: "Embalse",
      monto: 5000,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "servicio",
    },
    {
      id: "p_serv_agua",
      nombre: "Servicio (agua)",
      area: "Balseros",
      predio: "Embalse",
      monto: 3000,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "servicio",
    },
    {
      id: "p_recargo",
      nombre: "Recargo",
      area: "Guardería",
      predio: "Almafuerte",
      monto: 0,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "recargo",
    },
  ];

  /** Balsa de 4 integrantes: cuota ×4 y área por unidad (CS-03, PAG-01). */
  const CUATRO: OpcionesItemsPorArancel = { anclas: ANCLAS, miembros: 4 };

  it("compone una línea por arancelId tickeado (ReQ-012)", () => {
    const lineas = itemsPorArancel(CATALOGO, LUGARES, new Set(["a_balsa", "p_cuota"]), CUATRO);
    expect(lineas.map((l) => l.arancelId)).toEqual(["a_balsa", "p_cuota"]);
  });

  it("multiplica la cuota social por los miembros de la unidad (CS-03)", () => {
    const cuota = itemsPorArancel(CATALOGO, LUGARES, new Set(["p_cuota"]), CUATRO)[0]!;
    expect(cuota.factor).toBe(4);
    expect(cuota.monto).toBe(48000); // 12.000 × 4
    expect(cuota.arancelId).toBe("p_cuota");
    expect(cuota.membresiaId).toBe("m-cuota");
  });

  it("el área NO se multiplica por integrantes: una balsa es importe fijo", () => {
    const area = itemsPorArancel(CATALOGO, LUGARES, new Set(["a_balsa"]), CUATRO)[0]!;
    expect(area.factor).toBe(1);
    expect(area.monto).toBe(18500);
    expect(area.membresiaId).toBe("m-area");
  });

  it("nada marcado compone cero líneas (deja el confirmar deshabilitado)", () => {
    expect(itemsPorArancel(CATALOGO, LUGARES, new Set(), CUATRO)).toHaveLength(0);
  });

  it("dos apartes SERVICIO del mismo lugar emiten DOS líneas (ReQ-001)", () => {
    const lineas = itemsPorArancel(
      CATALOGO,
      LUGARES,
      new Set(["p_serv_luz", "p_serv_agua"]),
      CUATRO,
    );
    expect(lineas).toHaveLength(2);
    expect(lineas.map((l) => l.arancelId)).toEqual(["p_serv_luz", "p_serv_agua"]);
    expect(lineas.map((l) => l.monto)).toEqual([5000, 3000]);
    // Ambas se imputan al lugar de la balsa: la misma membresía ancla.
    expect(lineas.every((l) => l.membresiaId === "m-area")).toBe(true);
  });

  it("un arancelId que no está en el catálogo no emite línea", () => {
    expect(itemsPorArancel(CATALOGO, LUGARES, new Set(["no_existe"]), CUATRO)).toHaveLength(0);
  });

  it("el servicio toma el precio de catálogo y no se multiplica por miembros", () => {
    const servicio = itemsPorArancel(CATALOGO, LUGARES, new Set(["p_serv_luz"]), CUATRO)[0]!;
    expect(servicio.monto).toBe(5000);
    expect(servicio.factor).toBe(1);
    // Sin ajuste, el montoAplicado no viaja: el servidor ya usa el catálogo.
    expect(servicio.montoAplicado).toBeUndefined();
  });

  it("un servicio ajustado manda el importe solo para este cobro (ReQ-010)", () => {
    const servicio = itemsPorArancel(CATALOGO, LUGARES, new Set(["p_serv_luz"]), {
      ...CUATRO,
      ajustes: { p_serv_luz: 7300 },
    })[0]!;
    expect(servicio.monto).toBe(7300);
    expect(servicio.montoAplicado).toBe(7300);
  });

  it("el recargo usa el importe tipeado y el arancel carrier", () => {
    const [recargo] = itemsPorArancel(CATALOGO, LUGARES, new Set(["p_recargo"]), {
      ...CUATRO,
      ajustes: { p_recargo: 10000 },
    });
    expect(recargo!.arancelId).toBe("p_recargo");
    expect(recargo!.monto).toBe(10000);
    expect(recargo!.montoAplicado).toBe(10000);
    expect(recargo!.factor).toBe(1);
  });

  it("un recargo sin importe no compone línea en vez de dejar que el servidor rechace", () => {
    expect(itemsPorArancel(CATALOGO, LUGARES, new Set(["p_recargo"]), CUATRO)).toHaveLength(0);
  });

  it("una línea sin ancla no se emite", () => {
    expect(
      itemsPorArancel(CATALOGO, LUGARES, new Set(["p_cuota"]), {
        ...CUATRO,
        anclas: { area: "m-area" },
      }),
    ).toHaveLength(0);
  });

  it("totalEstimado suma las líneas compuestas", () => {
    const lineas = itemsPorArancel(
      CATALOGO,
      LUGARES,
      new Set(["a_balsa", "p_cuota", "p_recargo"]),
      {
        ...CUATRO,
        ajustes: { p_recargo: 5000 },
      },
    );
    expect(totalEstimado(lineas)).toBe(18500 + 48000 + 5000);
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
  const LUGARES: LugarCobrable[] = [
    { area: "Balseros", predio: "Embalse", categoria: null, membresiaId: "m-area" },
  ];
  const OPCIONES: OpcionesItemsPorArancel = {
    anclas: { area: "m-area", cuota: "m-cuota" },
    miembros: 4,
  };

  it("área y cuota social no envían montoAplicado (el servidor usa el catálogo)", () => {
    const items = itemsPorArancel(CATALOGO, LUGARES, new Set(["a_balsa", "p_cuota"]), OPCIONES).map(
      lineaAPagoItem,
    );
    for (const item of items) {
      expect(item).not.toHaveProperty("montoAplicado");
    }
  });

  it("el recargo envía el importe tipeado", () => {
    const [l] = itemsPorArancel(CATALOGO, LUGARES, new Set(["p_recargo"]), {
      ...OPCIONES,
      ajustes: { p_recargo: 10000 },
    });
    expect(lineaAPagoItem(l!).montoAplicado).toBe(10000);
  });

  it("el servicio sin ajuste no envía montoAplicado (catálogo vigente del servidor)", () => {
    const [l] = itemsPorArancel(CATALOGO, LUGARES, new Set(["p_servicio"]), OPCIONES);
    expect(lineaAPagoItem(l!)).not.toHaveProperty("montoAplicado");
  });

  it("el servicio ajustado envía el importe solo para este cobro", () => {
    const [l] = itemsPorArancel(CATALOGO, LUGARES, new Set(["p_servicio"]), {
      ...OPCIONES,
      ajustes: { p_servicio: 9500 },
    });
    expect(lineaAPagoItem(l!).montoAplicado).toBe(9500);
  });

  it("preserva arancelId, membresiaId, nombre y concepto", () => {
    const [l] = itemsPorArancel(CATALOGO, LUGARES, new Set(["a_balsa"]), OPCIONES);
    expect(lineaAPagoItem(l!)).toEqual({
      arancelId: "a_balsa",
      membresiaId: "m-area",
      arancelNombre: "Cuota Balsa",
      concepto: "area",
    });
  });
});

describe("arancelPorConcepto (ReQ-002 / ReQ-008)", () => {
  const BASE: Arancel[] = [
    {
      id: "a_balsa",
      nombre: "Amarre",
      area: "Balseros",
      predio: "Embalse",
      monto: 18500,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "area",
    },
    {
      id: "p_cuota",
      nombre: "Cuota social",
      area: "Guardería",
      predio: "Almafuerte",
      monto: 12000,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "cuota social",
    },
    {
      id: "p_serv_balseros",
      nombre: "Servicio Balseros",
      area: "Balseros",
      predio: "Embalse",
      monto: 5000,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "servicio",
    },
    {
      id: "p_serv_cabaneros",
      nombre: "Servicio Cabañeros",
      area: "Cabañeros",
      predio: "Almafuerte",
      monto: 3000,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "servicio",
    },
  ];
  const BALSEROS: LugarCobro = { area: "Balseros", predio: "Embalse", categoria: null };
  const CABANEROS: LugarCobro = { area: "Cabañeros", predio: "Almafuerte", categoria: null };

  it("encuentra la cuota social POR CONCEPTO, no por su área placeholder", () => {
    const cuota = arancelPorConcepto(BASE, "cuota social");
    expect(cuota?.id).toBe("p_cuota");
    expect(cuota?.monto).toBe(12000);
  });

  it("resuelve el servicio por LUGAR: cada área cobra el suyo (ReQ-002)", () => {
    expect(arancelPorConcepto(BASE, "servicio", BALSEROS)?.id).toBe("p_serv_balseros");
    expect(arancelPorConcepto(BASE, "servicio", CABANEROS)?.id).toBe("p_serv_cabaneros");
  });

  it("el área se resuelve por lugar y exige uno", () => {
    expect(arancelPorConcepto(BASE, "area", BALSEROS)?.id).toBe("a_balsa");
    expect(arancelPorConcepto(BASE, "area")).toBeUndefined();
  });

  it("una fila sin concepto cuenta como área (default de la columna)", () => {
    const legacy: Arancel[] = [{ ...BASE[0]!, id: "a_legacy", concepto: undefined }];
    expect(arancelPorConcepto(legacy, "area", BALSEROS)?.id).toBe("a_legacy");
  });

  it("desempata por id ascendente, igual que el servidor", () => {
    const dos: Arancel[] = [
      { ...BASE[1]!, id: "p_zzz" },
      { ...BASE[1]!, id: "p_aaa" },
    ];
    expect(arancelPorConcepto(dos, "cuota social")?.id).toBe("p_aaa");
  });

  it("sin fila de servicio para el lugar devuelve undefined (ReQ-003)", () => {
    const guarderia: LugarCobro = { area: "Guardería", predio: "Almafuerte", categoria: null };
    expect(arancelPorConcepto(BASE, "servicio", guarderia)).toBeUndefined();
  });

  it("un servicio SIN lugar no resuelve nada (PR6 borró el fallback global)", () => {
    expect(arancelPorConcepto(BASE, "servicio")).toBeUndefined();
  });
});

describe("arancelesDisponibles (ReQ-001 / ReQ-003)", () => {
  const CATALOGO: Arancel[] = [
    {
      id: "a_balsa",
      nombre: "Amarre",
      area: "Balseros",
      predio: "Embalse",
      monto: 18500,
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
      id: "p_serv_luz",
      nombre: "Servicio (luz)",
      area: "Balseros",
      predio: "Embalse",
      monto: 5000,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "servicio",
    },
    {
      id: "p_serv_agua",
      nombre: "Servicio (agua)",
      area: "Balseros",
      predio: "Embalse",
      monto: 3000,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "servicio",
    },
    {
      id: "p_cuota",
      nombre: "Cuota social",
      area: "Guardería",
      predio: "Almafuerte",
      monto: 12000,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "cuota social",
    },
    {
      id: "p_recargo",
      nombre: "Recargo",
      area: "Guardería",
      predio: "Almafuerte",
      monto: 0,
      vigenteDesde: "2020-01-01",
      historico: [],
      concepto: "recargo",
    },
  ];
  const BALSEROS: LugarCobro = { area: "Balseros", predio: "Embalse", categoria: null };

  it("lista área + TODOS los servicios del lugar + cuota social y recargo (ReQ-001)", () => {
    const ids = arancelesDisponibles(CATALOGO, [BALSEROS]).map((a) => a.id);
    expect(ids).toContain("a_balsa");
    expect(ids).toContain("p_serv_luz");
    expect(ids).toContain("p_serv_agua");
    expect(ids).toContain("p_cuota");
    expect(ids).toContain("p_recargo");
  });

  it("un lugar sin fila SERVICIO no aporta línea de servicio (ReQ-003)", () => {
    const guarderia: LugarCobro = { area: "Guardería", predio: "Almafuerte", categoria: null };
    const ids = arancelesDisponibles(CATALOGO, [guarderia]).map((a) => a.id);
    expect(ids.some((id) => id.startsWith("p_serv_"))).toBe(false);
  });

  it("no duplica filas cuando el mismo lugar llega repetido", () => {
    const ids = arancelesDisponibles(CATALOGO, [BALSEROS, BALSEROS]).map((a) => a.id);
    expect(ids.filter((id) => id === "p_serv_luz")).toHaveLength(1);
    expect(ids.filter((id) => id === "p_serv_agua")).toHaveLength(1);
    expect(ids.filter((id) => id === "a_balsa")).toHaveLength(1);
  });

  it("la categoría exacta distingue la fila de área y cae al catch-all", () => {
    const esp: LugarCobro = { area: "Cabañeros", predio: "Almafuerte", categoria: "Especial" };
    const grande: LugarCobro = { area: "Cabañeros", predio: "Almafuerte", categoria: "Grande" };

    const deEsp = arancelesDisponibles(CATALOGO, [esp]).map((a) => a.id);
    expect(deEsp).toContain("a_cab_esp");
    expect(deEsp).not.toContain("a_cab_gen");

    const deGrande = arancelesDisponibles(CATALOGO, [grande]).map((a) => a.id);
    expect(deGrande).toContain("a_cab_gen");
    expect(deGrande).not.toContain("a_cab_esp");
  });

  it("sin lugares sólo lista los carriers de concepto (cuota social y recargo)", () => {
    expect(
      arancelesDisponibles(CATALOGO, [])
        .map((a) => a.id)
        .sort(),
    ).toEqual(["p_cuota", "p_recargo"]);
  });
});

describe("membresiaDeLugar (ReQ-004)", () => {
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

  const LUGAR: LugarCobro = { area: "Balseros", predio: "Embalse", categoria: null };

  it("devuelve la membresía de área que ancla el lugar", () => {
    expect(membresiaDeLugar([memb({ id: "m-balsa" })], LUGAR)?.id).toBe("m-balsa");
  });

  it("prefiere al Titular del lugar por sobre un integrante", () => {
    const memberships = [
      memb({ id: "m-int", rol: "Integrante" }),
      memb({ id: "m-tit", rol: "Titular" }),
    ];
    expect(membresiaDeLugar(memberships, LUGAR)?.id).toBe("m-tit");
  });

  it("una membresía de cuota social (sin área) nunca ancla un lugar", () => {
    const cuota = memb({ id: "m-cuota", area: null, predio: null, concepto: "cuota social" });
    expect(membresiaDeLugar([cuota], LUGAR)).toBeUndefined();
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

  const todas: UnidadGroup[] = [g("pV", "Inactiva"), g("pR", "A revisar"), g("pA", "Activa")];
  const estadoPorParcela: Record<string, EstadoSocio> = {
    pV: "Inactivo — revisar",
    pR: "Socio activo — revisar",
    pA: "Socio activo",
  };
  const estadoDe = (gr: UnidadGroup): EstadoSocio =>
    estadoPorParcela[gr.parcelaId ?? ""] ?? "Socio activo";

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
      parcela("p1", [miembro("m1", "Inactivo — revisar"), miembro("m2", "Socio activo — revisar")]),
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

describe("formatearAvisosCobro (ReQ-011)", () => {
  it("une los avisos del backend en un único texto legible", () => {
    expect(formatearAvisosCobro(["motivo uno", "motivo dos"])).toBe("motivo uno · motivo dos");
  });

  it("devuelve null sin avisos: undefined o array vacío", () => {
    expect(formatearAvisosCobro(undefined)).toBeNull();
    expect(formatearAvisosCobro(null)).toBeNull();
    expect(formatearAvisosCobro([])).toBeNull();
  });

  it("ignora avisos en blanco y recorta el texto", () => {
    expect(formatearAvisosCobro(["  motivo  ", "   "])).toBe("motivo");
    expect(formatearAvisosCobro(["  ", ""])).toBeNull();
  });
});
