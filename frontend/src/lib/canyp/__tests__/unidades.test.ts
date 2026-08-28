/**
 * Runtime + compile-time tests for the UnidadesPanel grouping helper (PR 3).
 *
 * Validates design D4: grouping by parcelaId (rename-safe), the "Sin asignar"
 * group for memberships with null/unresolved parcelaId, and the aggregated
 * UnidadGroup shape (nombre, predio, categoria, members).
 */

import { describe, expect, it } from "vitest";
import { groupByParcelaId } from "../../../components/canyp/UnidadesPanel";
import type { Membresia, Area, CategoriaParcela, Predio } from "../types";

function memb(overrides: Partial<Membresia> & { id: string; area: Area }): Membresia {
  return {
    socioId: "s-x",
    predio: "Almafuerte",
    estado: "activa",
    vencimiento: "2099-01-01",
    ...overrides,
  };
}

type PlainParcela = {
  id: string;
  nombre: string;
  tipo: string;
  categoria?: CategoriaParcela;
  predio: Predio;
};

describe("groupByParcelaId", () => {
  it("groups memberships by parcelaId, not by name (rename-safe, D4)", () => {
    const membresias: Membresia[] = [
      memb({ id: "m1", area: "Cabañeros", parcelaId: "p1" }),
      memb({ id: "m2", area: "Cabañeros", parcelaId: "p1", socioId: "s2" }),
      memb({ id: "m3", area: "Cabañeros", parcelaId: "p2" }),
    ];
    // Renamed unit: name no longer matches anything, but parcelaId does.
    const parcelas: PlainParcela[] = [
      { id: "p1", nombre: "Parcela 1", tipo: "cabaña", categoria: "Mediana", predio: "Almafuerte" },
      { id: "p2", nombre: "Cabaña B", tipo: "cabaña", predio: "Almafuerte" },
    ];

    const groups = groupByParcelaId({ membresias, parcelas, area: "Cabañeros" });
    expect(groups).toHaveLength(2);
    const g1 = groups.find((g) => g.parcelaId === "p1");
    expect(g1?.nombre).toBe("Parcela 1");
    expect(g1?.members).toHaveLength(2);
    expect(g1?.categoria).toBe("Mediana");
  });

  it("puts memberships with null or unresolved parcelaId into 'Sin asignar'", () => {
    const membresias: Membresia[] = [
      memb({ id: "m1", area: "Cabañeros", parcelaId: "p1" }), // resolves
      memb({ id: "m2", area: "Cabañeros" }), // parcelaId undefined → null
      memb({ id: "m3", area: "Cabañeros", parcelaId: "p_noexiste" }), // unresolved
    ];
    const parcelas: PlainParcela[] = [
      { id: "p1", nombre: "Parcela 1", tipo: "cabaña", predio: "Almafuerte" },
    ];
    const groups = groupByParcelaId({ membresias, parcelas, area: "Cabañeros" });
    expect(groups).toHaveLength(2);
    const sinAsignar = groups.find((g) => g.parcelaId === null);
    expect(sinAsignar).toBeDefined();
    expect(sinAsignar?.nombre).toBe("Sin asignar");
    expect(sinAsignar?.members.map((m) => m.id)).toEqual(["m2", "m3"]);
    expect(sinAsignar?.categoria).toBeNull();
  });

  it("only includes memberships of the requested area", () => {
    const membresias: Membresia[] = [
      memb({ id: "m1", area: "Cabañeros", parcelaId: "p1" }),
      memb({ id: "m2", area: "Balseros", parcelaId: "p1" }),
    ];
    const groups = groupByParcelaId({ membresias, parcelas: [], area: "Balseros" });
    expect(groups).toHaveLength(1);
    expect(groups[0]?.members.map((m) => m.id)).toEqual(["m2"]);
  });
});
