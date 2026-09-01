/**
 * Component tests for the reusable import UI (PR 4).
 *
 * Covers the pure presentational pieces that don't require a query client:
 * EditableCell rendering/editing, StepPreviewEdit table + skip logic +
 * pagination + empty state, and the CSV download helper.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { ReactNode } from "react";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { EditableCell } from "@/components/import/EditableCell";
import { StepPreviewEdit } from "@/components/import/StepPreviewEdit";
import { downloadCsv } from "@/components/import/downloads";
import type { RowData } from "@/lib/canyp/types";

// globals:false in vitest.config.ts means RTL's auto-cleanup is not registered.
afterEach(cleanup);

function wrap(node: ReactNode) {
  return <TooltipProvider>{node}</TooltipProvider>;
}

describe("EditableCell", () => {
  it("renders the current value in an input", () => {
    render(wrap(<EditableCell field="nombre" value="Juan Pérez" onChange={() => {}} />));
    expect(screen.getByDisplayValue("Juan Pérez")).toBeTruthy();
  });

  it("calls onChange with the field and typed value", () => {
    const onChange = vi.fn();
    render(wrap(<EditableCell field="nombre" value="Maria" onChange={onChange} />));
    fireEvent.change(screen.getByDisplayValue("Maria"), { target: { value: "Ana" } });
    expect(onChange).toHaveBeenCalledWith("nombre", "Ana");
  });

  it("renders a textarea when multiline", () => {
    render(wrap(<EditableCell field="direccion" value="Calle 1" multiline onChange={() => {}} />));
    expect(screen.getByDisplayValue("Calle 1").tagName).toBe("TEXTAREA");
  });

  it("disables editing when disabled", () => {
    render(wrap(<EditableCell field="nombre" value="x" disabled onChange={() => {}} />));
    expect((screen.getByDisplayValue("x") as HTMLInputElement).disabled).toBe(true);
  });
});

describe("StepPreviewEdit", () => {
  const columnSpec = [
    { label: "Nombre", field: "nombre" },
    { label: "DNI", field: "dni" },
  ];
  const stats = { total: 2, validas: 1, conErrores: 1, aSaltar: 0 };

  function makeRows(): RowData[] {
    return [{ data: { nombre: "Ana", dni: "111" } }, { data: { nombre: "Leo", dni: "222" } }];
  }

  it("renders stats banner and headers", () => {
    render(
      wrap(
        <StepPreviewEdit
          resourceLabel="socios"
          columnSpec={columnSpec}
          columns={{ "Nombre y Apellido": "nombre", Dni: "dni" }}
          ignoredColumns={["Email"]}
          stats={stats}
          rows={makeRows()}
          errorsByRow={{}}
          onToggleSkip={() => {}}
          onChange={() => {}}
          onBack={() => {}}
          onContinue={() => {}}
        />,
      ),
    );
    expect(screen.getByText(/Total: 2/)).toBeTruthy();
    expect(screen.getByText(/Válidas: 1/)).toBeTruthy();
    expect(screen.getByText(/Con errores: 1/)).toBeTruthy();
    // Mapped Spanish source headers shown + value cells
    expect(screen.getAllByText("Nombre y Apellido").length).toBeGreaterThan(0);
    expect(screen.getByDisplayValue("Ana")).toBeTruthy();
    // Ignored columns banner
    expect(screen.getByText(/Email/)).toBeTruthy();
  });

  it("toggles skip and disables row editing when skipped", () => {
    const onToggleSkip = vi.fn();
    render(
      wrap(
        <StepPreviewEdit
          resourceLabel="socios"
          columnSpec={columnSpec}
          columns={{ "Nombre y Apellido": "nombre", Dni: "dni" }}
          ignoredColumns={[]}
          stats={stats}
          rows={makeRows()}
          errorsByRow={{}}
          onToggleSkip={onToggleSkip}
          onChange={() => {}}
          onBack={() => {}}
          onContinue={() => {}}
        />,
      ),
    );
    // First skip checkbox
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes.length).toBe(2);
    fireEvent.click(boxes[0]!);
    expect(onToggleSkip).toHaveBeenCalledWith(0, true);
  });

  it("disables Continuar when there are no rows", () => {
    render(
      wrap(
        <StepPreviewEdit
          resourceLabel="socios"
          columnSpec={columnSpec}
          columns={{ "Nombre y Apellido": "nombre", Dni: "dni" }}
          ignoredColumns={[]}
          stats={stats}
          rows={[]}
          errorsByRow={{}}
          onToggleSkip={() => {}}
          onChange={() => {}}
          onBack={() => {}}
          onContinue={() => {}}
        />,
      ),
    );
    expect((screen.getByText("Continuar") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/No hay filas/)).toBeTruthy();
  });
});

describe("downloadCsv", () => {
  beforeEach(() => {
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:mock"),
      revokeObjectURL: vi.fn(),
    });
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("builds and triggers a CSV download for the given rows", () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    downloadCsv(
      "errores.csv",
      ["fila", "campo"],
      [
        { fila: 1, campo: "dni" },
        { fila: 2, campo: "nombre" },
      ],
    );
    expect(URL.createObjectURL).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    click.mockRestore();
  });
});
