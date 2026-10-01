/**
 * Regression tests: a write must invalidate every cache whose data the server
 * DERIVES from what that write changed.
 *
 * The 4 socio states are not stored. `services/estado_socio` recomputes them
 * from the stored `estado`/`vencimiento` of the cuota social and área
 * memberships on every read (EST-01/EST-02), so the padrón (`Socio.estado`) and
 * the dashboard cards (`estados`) are projections of a membership write.
 *
 * Two bugs of the same class are pinned here:
 *
 * 1. `useUpdateMembresia` — the mutation behind the `estado` selector of the
 *    socio ficha and of the membresías table — used to invalidate
 *    `["membresias"]` only. The lista showed the new `estado` next to a stale
 *    badge and the dashboard card kept counting the old bucket, so flipping a
 *    membership to `vencida` looked like it had done nothing.
 * 2. `useCreatePago` — the SAME derivation, reached through a different door.
 *    A charge renews (`renovar_membresias` rewrites `vencimiento` and forces
 *    `estado = 'activa'`), so it moves a socio out of 🔴/⚠️ exactly like an
 *    operator flipping the flag by hand, and it used to invalidate
 *    `["membresias"]` only. The operator charged somebody and the padrón kept
 *    showing them as a debtor until the 15s poll happened to land.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import {
  useCreateMembresia,
  useCreatePago,
  useCreateSocio,
  useDeleteMembresia,
  useDeleteParcela,
  useDeleteSocio,
  useExecuteImport,
  useImportParcelas,
  useSetBatchEstado,
  useSetBatchVencimiento,
  useUpdateMembresia,
  useUpdateMembresiaVencimiento,
  useUpdateSocio,
} from "../queries";

const mockApi = vi.hoisted(() => ({
  createMembresia: vi.fn(),
  updateMembresia: vi.fn(),
  deleteMembresia: vi.fn(),
  setBatchEstado: vi.fn(),
  setBatchVencimiento: vi.fn(),
  updateMembresiaVencimiento: vi.fn(),
  deleteParcela: vi.fn(),
  importParcelas: vi.fn(),
  createSocio: vi.fn(),
  updateSocio: vi.fn(),
  deleteSocio: vi.fn(),
  createPago: vi.fn(),
  executeImport: vi.fn(),
}));

vi.mock("../api", () => mockApi);

let invalidated: { queryKey?: unknown[] }[];
let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** Top-level segment of every `invalidateQueries` call the mutation made. */
function invalidatedRoots(): string[] {
  return invalidated
    .map((filters) => filters.queryKey?.[0])
    .filter((root): root is string => typeof root === "string");
}

beforeEach(() => {
  for (const fn of Object.values(mockApi)) fn.mockReset().mockResolvedValue({});
  client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  // Record every invalidation while still letting the real one run, so the
  // assertions describe the actual calls and not a stubbed behaviour.
  invalidated = [];
  const original = client.invalidateQueries.bind(client);
  client.invalidateQueries = ((...args: [{ queryKey?: unknown[] }]) => {
    invalidated.push(args[0]);
    return original(...args);
  }) as typeof client.invalidateQueries;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("membership writes invalidate the derived socio-state caches", () => {
  it("useUpdateMembresia (the ficha's estado selector) invalidates socios + dashboard", async () => {
    const { result } = renderHook(() => useUpdateMembresia(), { wrapper });

    result.current.mutate({ id: "m1", data: { estado: "vencida" } });

    await waitFor(() => expect(mockApi.updateMembresia).toHaveBeenCalled());
    await waitFor(() => expect(invalidated.length).toBeGreaterThan(0));

    const roots = invalidatedRoots();
    expect(roots).toContain("membresias");
    expect(roots).toContain("socios");
    expect(roots).toContain("dashboard");
  });

  it("useCreateMembresia invalidates socios + dashboard", async () => {
    const { result } = renderHook(() => useCreateMembresia(), { wrapper });

    result.current.mutate({ socioId: "s1", area: "Balseros" } as never);

    await waitFor(() => expect(invalidated.length).toBeGreaterThan(0));
    const roots = invalidatedRoots();
    expect(roots).toEqual(expect.arrayContaining(["membresias", "socios", "dashboard"]));
  });

  it("useDeleteMembresia invalidates socios + dashboard", async () => {
    const { result } = renderHook(() => useDeleteMembresia(), { wrapper });

    result.current.mutate("m1");

    await waitFor(() => expect(invalidated.length).toBeGreaterThan(0));
    const roots = invalidatedRoots();
    expect(roots).toEqual(expect.arrayContaining(["membresias", "socios", "dashboard"]));
  });

  it("useSetBatchEstado invalidates socios + dashboard (unit-wide estado change)", async () => {
    const { result } = renderHook(() => useSetBatchEstado(), { wrapper });

    result.current.mutate({ parcelaId: "p1", estado: "vencida" });

    await waitFor(() => expect(invalidated.length).toBeGreaterThan(0));
    const roots = invalidatedRoots();
    expect(roots).toEqual(expect.arrayContaining(["membresias", "socios", "dashboard"]));
  });

  it("useSetBatchVencimiento keeps invalidating socios + dashboard", async () => {
    const { result } = renderHook(() => useSetBatchVencimiento(), { wrapper });

    result.current.mutate({ parcelaId: "p1", vencimiento: "2020-01-01", concepto: "area" });

    await waitFor(() => expect(invalidated.length).toBeGreaterThan(0));
    const roots = invalidatedRoots();
    expect(roots).toEqual(expect.arrayContaining(["membresias", "socios", "dashboard"]));
  });

  it("useUpdateMembresiaVencimiento keeps invalidating socios + dashboard", async () => {
    const { result } = renderHook(() => useUpdateMembresiaVencimiento(), { wrapper });

    result.current.mutate({ id: "m1", vencimiento: "2020-01-01" });

    await waitFor(() => expect(invalidated.length).toBeGreaterThan(0));
    const roots = invalidatedRoots();
    expect(roots).toEqual(expect.arrayContaining(["membresias", "socios", "dashboard"]));
  });

  it("useDeleteParcela invalidates socios + dashboard (removes the unit's área rows)", async () => {
    const { result } = renderHook(() => useDeleteParcela(), { wrapper });

    result.current.mutate("p1");

    await waitFor(() => expect(invalidated.length).toBeGreaterThan(0));
    const roots = invalidatedRoots();
    expect(roots).toEqual(
      expect.arrayContaining(["parcelas", "membresias", "socios", "dashboard"]),
    );
  });

  it("useImportParcelas invalidates dashboard (it writes socios and memberships)", async () => {
    const { result } = renderHook(() => useImportParcelas(), { wrapper });

    result.current.mutate({} as never);

    await waitFor(() => expect(invalidated.length).toBeGreaterThan(0));
    const roots = invalidatedRoots();
    expect(roots).toEqual(
      expect.arrayContaining(["parcelas", "membresias", "socios", "dashboard"]),
    );
  });

  it("does not invalidate a cache the write cannot affect", async () => {
    const { result } = renderHook(() => useUpdateMembresia(), { wrapper });

    result.current.mutate({ id: "m1", data: { estado: "vencida" } });

    await waitFor(() => expect(invalidated.length).toBeGreaterThan(0));
    expect(invalidatedRoots()).not.toContain("pagos");
    expect(invalidatedRoots()).not.toContain("aranceles");
  });
});

describe("a charge invalidates the derived socio-state caches too", () => {
  it("useCreatePago invalidates socios + dashboard (the renewal rewrites estado/vencimiento)", async () => {
    const { result } = renderHook(() => useCreatePago(), { wrapper });

    result.current.mutate({ socioId: "s1" } as never);

    await waitFor(() => expect(mockApi.createPago).toHaveBeenCalled());
    await waitFor(() => expect(invalidated.length).toBeGreaterThan(0));

    const roots = invalidatedRoots();
    expect(roots).toContain("pagos");
    expect(roots).toContain("membresias");
    expect(roots).toContain("socios");
    expect(roots).toContain("dashboard");
  });

  it("useCreatePago still invalidates the catalog and the receipts", async () => {
    const { result } = renderHook(() => useCreatePago(), { wrapper });

    result.current.mutate({ socioId: "s1" } as never);

    await waitFor(() => expect(invalidated.length).toBeGreaterThan(0));
    const roots = invalidatedRoots();
    expect(roots).toEqual(expect.arrayContaining(["pagos", "aranceles"]));
  });
});

describe("a socio write that changes who exists invalidates the counts", () => {
  it("useCreateSocio invalidates membresias + dashboard (the server provisions its cuota)", async () => {
    const { result } = renderHook(() => useCreateSocio(), { wrapper });

    result.current.mutate({ nombre: "Nuevo" } as never);

    await waitFor(() => expect(invalidated.length).toBeGreaterThan(0));
    expect(invalidatedRoots()).toEqual(
      expect.arrayContaining(["membresias", "socios", "dashboard"]),
    );
  });

  it("useDeleteSocio invalidates membresias + dashboard (its memberships go with it)", async () => {
    const { result } = renderHook(() => useDeleteSocio(), { wrapper });

    result.current.mutate("s1");

    await waitFor(() => expect(invalidated.length).toBeGreaterThan(0));
    expect(invalidatedRoots()).toEqual(
      expect.arrayContaining(["membresias", "socios", "dashboard"]),
    );
  });

  it("useUpdateSocio leaves the dashboard alone (socio columns cannot move a bucket)", async () => {
    const { result } = renderHook(() => useUpdateSocio(), { wrapper });

    result.current.mutate({ id: "s1", data: { nombre: "Nuevo nombre" } });

    await waitFor(() => expect(invalidated.length).toBeGreaterThan(0));
    const roots = invalidatedRoots();
    expect(roots).toContain("socios");
    expect(roots).not.toContain("dashboard");
    expect(roots).not.toContain("membresias");
  });

  it("useExecuteImport invalidates dashboard (imports move the same buckets)", async () => {
    const { result } = renderHook(() => useExecuteImport(), { wrapper });

    result.current.mutate({ resource: "socios", rows: [] });

    await waitFor(() => expect(invalidated.length).toBeGreaterThan(0));
    expect(invalidatedRoots()).toEqual(
      expect.arrayContaining(["membresias", "socios", "dashboard"]),
    );
  });
});
