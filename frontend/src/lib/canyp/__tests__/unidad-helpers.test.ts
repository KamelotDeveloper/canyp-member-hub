/**
 * Runtime + compile-time tests for the pure unidad-dialog helpers (PR 4).
 *
 * - `buildNuevaUnidadPayload` → RQ 6 / RQ 12: turns the "Nueva unidad" form
 *   into an ImportPayload (first socio = Titular, rest = Integrantes), so the
 *   backend creates the real Parcela + socios + membresías transactionally.
 * - `itemsParaMembresias` → RQ 14: one PagoItem per (membresía, arancel), each
 *   carrying its own membresiaId (never a shared id).
 */

import { describe, expect, it } from "vitest";
import {
  buildNuevaUnidadPayload,
  estadoCriticoDe,
  filtrarUnidades,
  itemsParaMembresias,
  ORDEN_ESTADOS,
} from "../unidad-helpers";
import type { Arancel, Membresia, UnidadGroup } from "../types";

describe("buildNuevaUnidadPayload", () => {
  it("builds a single-unit ImportPayload with first=Titular, rest=Integrantes", () => {
    const payload = buildNuevaUnidadPayload({
      nombre: "Cabaña E",
      tipo: "cabaña",
      categoria: "Mediana",
      predio: "Almafuerte",
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
        predio: "Almafuerte",
        vencimiento: "",
        socios: [{ nombre: "Ana", dni: "1" }],
      }),
    ).toBeNull();

    expect(
      buildNuevaUnidadPayload({
        nombre: "Cabaña E",
        tipo: "cabaña",
        predio: "Almafuerte",
        vencimiento: "",
        socios: [],
      }),
    ).toBeNull();

    expect(
      buildNuevaUnidadPayload({
        nombre: "Cabaña E",
        tipo: "cabaña",
        predio: "Almafuerte",
        vencimiento: "",
        socios: [{ nombre: "", dni: "1" }],
      }),
    ).toBeNull();
  });

  it("omits categoria and optional socio fields when absent", () => {
    const payload = buildNuevaUnidadPayload({
      nombre: "Balsa 1",
      tipo: "balsa",
      predio: "Almafuerte",
      vencimiento: "",
      socios: [{ nombre: "Luis", dni: "33" }],
    });
    expect(payload).not.toBeNull();
    const u = payload!.unidades[0]!;
    expect(u.categoria).toBeUndefined();
    expect(u.miembros[0]!.socio.telefono).toBeUndefined();
    expect(u.miembros[0]!.vencimiento).toBeUndefined();
  });
});

describe("itemsParaMembresias", () => {
  function memb(
    membresiaId: string,
    area: Membresia["area"],
    predio: Membresia["predio"],
  ): Membresia {
    return {
      id: membresiaId,
      socioId: "s",
      area,
      predio,
      estado: "activa",
      vencimiento: "2099-01-01",
    };
  }

  const aranceles: Arancel[] = [
    {
      id: "a1",
      nombre: "Cabaña",
      area: "Cabañeros",
      predio: "Almafuerte",
      monto: 100,
      vigenteDesde: "2020-01-01",
      historico: [],
    },
    {
      id: "a2",
      nombre: "Balsa",
      area: "Balseros",
      predio: "Almafuerte",
      monto: 150,
      vigenteDesde: "2020-01-01",
      historico: [],
    },
  ];

  it("creates one item per (membresia, arancel) with the correct membresiaId", () => {
    const items = itemsParaMembresias(
      [memb("m1", "Cabañeros", "Almafuerte"), memb("m2", "Cabañeros", "Almafuerte")],
      aranceles,
    );
    expect(items).toHaveLength(2);
    expect(items[0]!.membresiaId).toBe("m1");
    expect(items[1]!.membresiaId).toBe("m2");
    expect(items.every((i) => i.arancelId === "a1")).toBe(true);
  });

  it("matches by area+predio, ignoring non-matching aranceles", () => {
    const items = itemsParaMembresias([memb("m1", "Balseros", "Almafuerte")], aranceles);
    expect(items).toHaveLength(1);
    expect(items[0]!.arancelId).toBe("a2");
    expect(items[0]!.membresiaId).toBe("m1");
    expect(items[0]!.montoAplicado).toBe(150);
  });

  it("returns an empty array when there are no members or aranceles", () => {
    expect(itemsParaMembresias([], aranceles)).toHaveLength(0);
    expect(itemsParaMembresias([memb("m1", "Cabañeros", "Almafuerte")], [])).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// estadoCriticoDe (RQ 3) — estado visual más crítico de una unidad
// ---------------------------------------------------------------------------

/** Fecha ISO relativa a hoy (offset en días). */
function iso(offsetDays: number): string {
  const d = new Date();
  d.setHours(12, 0, 0, 0);
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

/** Membresía mínima para un estado visual concreto. */
function membEstado(id: string, visual: string): Membresia {
  let estado: Membresia["estado"] = "activa";
  let vencimiento = iso(365);
  if (visual === "baja") {
    estado = "baja";
    vencimiento = iso(365);
  } else if (visual === "suspendida") {
    estado = "suspendida";
    vencimiento = iso(365);
  } else if (visual === "vencida") {
    estado = "activa";
    vencimiento = iso(-10);
  } else if (visual === "por_vencer") {
    estado = "activa";
    vencimiento = iso(10);
  }
  return {
    id,
    socioId: `s-${id}`,
    area: "Cabañeros",
    predio: "Almafuerte",
    estado,
    vencimiento,
  };
}

function grupo(members: Membresia[]): UnidadGroup {
  return { parcelaId: "p1", nombre: "Cabaña A", predio: "Almafuerte", categoria: null, members };
}

describe("estadoCriticoDe (RQ 3)", () => {
  it("ORDEN_ESTADOS ranks most critical first: vencida > por_vencer > suspendida > baja > activa", () => {
    expect(ORDEN_ESTADOS).toEqual(["vencida", "por_vencer", "suspendida", "baja", "activa"]);
  });

  it.each(["vencida", "por_vencer", "suspendida", "baja", "activa"] as const)(
    "single member with state %s yields that estado",
    (visual) => {
      expect(estadoCriticoDe(grupo([membEstado("m1", visual)]))).toBe(visual);
    },
  );

  it("picks the most critical estado across mixed members (vencida wins)", () => {
    const g = grupo([
      membEstado("m1", "activa"),
      membEstado("m2", "por_vencer"),
      membEstado("m3", "vencida"),
    ]);
    expect(estadoCriticoDe(g)).toBe("vencida");
  });

  it("por_vencer beats suspendida, baja and activa in mixed group", () => {
    const g = grupo([
      membEstado("m1", "activa"),
      membEstado("m2", "suspendida"),
      membEstado("m3", "por_vencer"),
    ]);
    expect(estadoCriticoDe(g)).toBe("por_vencer");
  });

  it("suspendida beats baja and activa when no date-based state present", () => {
    const g = grupo([membEstado("m1", "baja"), membEstado("m2", "suspendida")]);
    expect(estadoCriticoDe(g)).toBe("suspendida");
  });

  it("baja beats activa when that is the most critical present", () => {
    const g = grupo([membEstado("m1", "baja"), membEstado("m2", "activa")]);
    expect(estadoCriticoDe(g)).toBe("baja");
  });

  it("defaults to activa for an empty group (tie/edge case)", () => {
    expect(estadoCriticoDe(grupo([]))).toBe("activa");
  });
});

// ---------------------------------------------------------------------------
// filtrarUnidades (RQ 4) — filtros Todas / Por vencer / Vencidas / Alertas
// ---------------------------------------------------------------------------

describe("filtrarUnidades (RQ 4)", () => {
  // 5 unidades con estados críticos mixtos:
  //   uV1, uV2 → vencidas; uPV → por_vencer; uAct → activa; uSus → suspendida
  const todas = [
    { ...grupo([membEstado("mv1", "vencida")]), parcelaId: "pV1", nombre: "Vencida 1" },
    { ...grupo([membEstado("mv2", "vencida")]), parcelaId: "pV2", nombre: "Vencida 2" },
    { ...grupo([membEstado("mpv", "por_vencer")]), parcelaId: "pPV", nombre: "Por vencer" },
    { ...grupo([membEstado("mac", "activa")]), parcelaId: "pAct", nombre: "Activa" },
    { ...grupo([membEstado("msu", "suspendida")]), parcelaId: "pSus", nombre: "Suspendida" },
  ] as UnidadGroup[];

  it("'todas' returns every unit unchanged", () => {
    expect(filtrarUnidades(todas, "todas")).toHaveLength(5);
    expect(filtrarUnidades(todas, "todas")).toEqual(todas);
  });

  it("'vencidas' returns only the vencida units", () => {
    const result = filtrarUnidades(todas, "vencidas");
    expect(result).toHaveLength(2);
    expect(result.map((g) => g.nombre)).toEqual(["Vencida 1", "Vencida 2"]);
  });

  it("'por_vencer' returns only the por_vencer unit", () => {
    const result = filtrarUnidades(todas, "por_vencer");
    expect(result).toHaveLength(1);
    expect(result[0]!.nombre).toBe("Por vencer");
  });

  it("'alertas' combines vencida + por_vencer, excluding activa/suspendida", () => {
    const result = filtrarUnidades(todas, "alertas");
    const names = result.map((g) => g.nombre);
    expect(result).toHaveLength(3);
    expect(names).toContain("Vencida 1");
    expect(names).toContain("Vencida 2");
    expect(names).toContain("Por vencer");
    expect(names).not.toContain("Activa");
    expect(names).not.toContain("Suspendida");
  });

  it("returns an empty array when no unit matches the filter", () => {
    // Ninguna suspendida cumple 'vencidas' → vacío.
    expect(filtrarUnidades([grupo([membEstado("m1", "suspendida")])], "vencidas")).toHaveLength(0);
  });
});
