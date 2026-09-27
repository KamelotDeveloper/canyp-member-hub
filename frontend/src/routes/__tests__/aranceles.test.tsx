/**
 * UI contract tests for `/aranceles` — `cobro-aranceles-flexibles` PR4.
 *
 * The real route component is rendered in jsdom with the query layer mocked, so
 * these prove the wiring the pure helpers cannot: the `Concepto` column really
 * shows (ReQ-013), the forms really send the concepto, and a 409 really reaches
 * the toast with the backend `detail` instead of a generic sentence
 * (ReQ-006/ReQ-007).
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/canyp/api";
import type { Arancel } from "@/lib/canyp/types";
import { ArancelesPage } from "../aranceles";

const h = vi.hoisted(() => ({
  aranceles: [] as unknown as Arancel[],
  toastError: vi.fn(),
  mutate: { create: vi.fn(), update: vi.fn(), delete: vi.fn() },
}));

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: unknown) => options,
}));

vi.mock("sonner", () => ({
  toast: { error: h.toastError, success: vi.fn() },
}));

vi.mock("@/lib/canyp/queries", () => ({
  useAranceles: () => ({ data: h.aranceles, isLoading: false }),
  useCreateArancel: () => ({ isPending: false, mutate: h.mutate.create }),
  useUpdateArancel: () => ({ isPending: false, mutate: h.mutate.update }),
  useDeleteArancel: () => ({ isPending: false, mutate: h.mutate.delete }),
}));

const FILAS: Arancel[] = [
  {
    id: "a1",
    nombre: "Amarre",
    area: "Balseros",
    predio: "Embalse",
    monto: 18500,
    concepto: "area",
    vigenteDesde: "2026-06-01",
    historico: [],
  },
  {
    id: "a15",
    nombre: "Cuota social",
    area: "Guardería",
    predio: "Almafuerte",
    monto: 10000,
    concepto: "cuota social",
    vigenteDesde: "2026-08-01",
    historico: [],
  },
];

const DUPLICADO =
  "Ya existe un arancel con area=Balseros, predio=Embalse, categoria=—, concepto=servicio (id=a_serv_balseros)";
const BLOQUEADO = "No se puede eliminar el arancel a1: 2 pago_items (pi1, pi4)";

beforeEach(() => {
  // Radix (Select / Dialog / AlertDialog) needs APIs que jsdom no implementa.
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.scrollIntoView = () => {};
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  h.aranceles = FILAS;
  h.toastError.mockReset();
  for (const m of Object.values(h.mutate)) m.mockReset();
});

// `globals: false` means testing-library does not auto-cleanup: without this the
// portal of an open dialog stays in document.body and the `pointer-events: none`
// Radix sets on the body breaks the next test's click.
afterEach(cleanup);

/** `getAllByRole` returns `T | undefined` under `noUncheckedIndexedAccess`. */
function at<T>(items: T[], i: number): T {
  const item = items[i];
  if (item === undefined) throw new Error(`no element at index ${i}`);
  return item;
}

/** The concepto trigger, found through the label it is associated with. */

async function elegirConcepto(
  user: ReturnType<typeof userEvent.setup>,
  dlg: HTMLElement,
  opcion: string,
) {
  await user.click(within(dlg).getByRole("combobox", { name: "Concepto" }));
  await user.click(await screen.findByRole("option", { name: opcion }));
}

describe("columna Concepto (ReQ-013)", () => {
  it("shows each row's concepto, not just the name", () => {
    render(<ArancelesPage />);
    expect(screen.getByRole("columnheader", { name: "Concepto" })).toBeInTheDocument();

    const filas = screen.getAllByRole("row");
    const amarre = at(filas, 1);
    const cuotaSocial = at(filas, 2);
    // Column 0 = Ítem (the name), column 1 = Concepto (the badge).
    const celdas = within(amarre).getAllByRole("cell");
    expect(celdas[0]).toHaveTextContent("Amarre");
    expect(celdas[1]).toHaveTextContent("Cuota de la unidad");

    // The case that motivated the column: "Cuota social" as name AND as concepto,
    // but the price comes from the second one.
    const cuota = within(cuotaSocial).getAllByRole("cell");
    expect(cuota[0]).toHaveTextContent("Cuota social");
    expect(cuota[1]).toHaveTextContent("Cuota social");
  });
});

describe("alta de arancel (2.2)", () => {
  it("shows área, predio and categoría for area; hides them for cuota social", async () => {
    const user = userEvent.setup();
    render(<ArancelesPage />);
    await user.click(screen.getByRole("button", { name: /Nuevo ítem de arancel/ }));
    const dlg = await screen.findByRole("dialog");

    expect(within(dlg).getByLabelText("Área")).toBeInTheDocument();
    expect(within(dlg).getByLabelText("Predio")).toBeInTheDocument();
    expect(within(dlg).getByLabelText("Categoría (opcional)")).toBeInTheDocument();

    await elegirConcepto(user, dlg, "Cuota social");
    expect(within(dlg).queryByLabelText("Área")).not.toBeInTheDocument();
    expect(within(dlg).queryByLabelText("Predio")).not.toBeInTheDocument();
    expect(within(dlg).queryByLabelText("Categoría (opcional)")).not.toBeInTheDocument();
    expect(within(dlg).getByRole("combobox", { name: "Concepto" })).toHaveTextContent(
      "Cuota social",
    );
  });

  it("sends the chosen concepto in the POST (ReQ-005)", async () => {
    const user = userEvent.setup();
    render(<ArancelesPage />);
    await user.click(screen.getByRole("button", { name: /Nuevo ítem de arancel/ }));
    const dlg = await screen.findByRole("dialog");
    await user.type(within(dlg).getByLabelText("Nombre del ítem"), "Cuota social");

    await elegirConcepto(user, dlg, "Cuota social");
    await user.type(within(dlg).getByLabelText("Monto"), "10000");
    await user.click(within(dlg).getByRole("button", { name: "Crear ítem" }));

    const [payload] = h.mutate.create.mock.calls.at(-1) as [Record<string, unknown>];
    expect(payload).toMatchObject({
      nombre: "Cuota social",
      concepto: "cuota social",
      monto: 10000,
      // Not place-priced: the placeholder travels and the categoría is nulled.
      area: "Guardería",

      predio: "Almafuerte",
      categoria: null,
    });
  });

  it("a duplicate-tuple 409 is shown in full and keeps the form open", async () => {
    const user = userEvent.setup();
    h.mutate.create.mockImplementation((_p: unknown, opts: { onError: (e: unknown) => void }) =>
      opts.onError(new ApiError(409, DUPLICADO)),
    );
    render(<ArancelesPage />);
    await user.click(screen.getByRole("button", { name: /Nuevo ítem de arancel/ }));
    const dlg = await screen.findByRole("dialog");
    await user.type(within(dlg).getByLabelText("Nombre del ítem"), "Servicio");
    await user.click(within(dlg).getByRole("button", { name: "Crear ítem" }));

    expect(h.toastError).toHaveBeenCalledWith(DUPLICADO);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("edición de arancel (2.3)", () => {
  it("re-tags the concepto and nulls the categoría the new one does not use", async () => {
    const user = userEvent.setup();
    render(<ArancelesPage />);
    await user.click(at(screen.getAllByRole("button", { name: "Editar" }), 0));
    const dlg = await screen.findByRole("dialog");

    await elegirConcepto(user, dlg, "Servicio");
    expect(within(dlg).getByLabelText("Área")).toBeInTheDocument();
    expect(within(dlg).queryByLabelText("Categoría (opcional)")).not.toBeInTheDocument();

    await user.click(within(dlg).getByRole("button", { name: "Guardar cambios" }));

    const [{ id, data }] = h.mutate.update.mock.calls.at(-1) as [
      { id: string; data: Record<string, unknown> },
    ];
    expect(id).toBe("a1");
    expect(data).toMatchObject({ concepto: "servicio", area: "Balseros", categoria: null });
  });

  it("a duplicate-tuple 409 while editing is shown in full", async () => {
    const user = userEvent.setup();
    h.mutate.update.mockImplementation((_p: unknown, opts: { onError: (e: unknown) => void }) =>
      opts.onError(new ApiError(409, DUPLICADO)),
    );
    render(<ArancelesPage />);
    await user.click(at(screen.getAllByRole("button", { name: "Editar" }), 0));
    const dlg = await screen.findByRole("dialog");
    await user.click(within(dlg).getByRole("button", { name: "Guardar cambios" }));

    expect(h.toastError).toHaveBeenCalledWith(DUPLICADO);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("borrado bloqueado (2.4)", () => {
  it("shows the 409 with the blocking counts and leaves the table standing", async () => {
    const user = userEvent.setup();
    h.mutate.delete.mockImplementation((_id: unknown, opts: { onError: (e: unknown) => void }) =>
      opts.onError(new ApiError(409, BLOQUEADO)),
    );
    render(<ArancelesPage />);
    await user.click(at(screen.getAllByRole("button", { name: "Eliminar" }), 0));
    const dlg = await screen.findByRole("alertdialog");
    await user.click(within(dlg).getByRole("button", { name: "Eliminar" }));

    expect(h.mutate.delete).toHaveBeenCalledWith("a1", expect.anything());
    expect(h.toastError).toHaveBeenCalledWith(BLOQUEADO);

    // After closing the alert the table is still whole: the 409 did not tear it down.
    await user.keyboard("{Escape}");

    expect(screen.getAllByRole("row")).toHaveLength(FILAS.length + 1);
  });
});
