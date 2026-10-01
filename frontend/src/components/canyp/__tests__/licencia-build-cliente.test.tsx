/**
 * BYPASS 1 + 4 en un BUILD DE CLIENTE.
 *
 * Contexto: la auditoría confirmó que un `settings.json` escrito a mano
 * (`{"dataMode":"local","databaseUrl":"","configured":false}`) abría la app
 * completa sin licencia. Los dos eslabones de la UI que lo permitían eran:
 *
 *   1. `LicenseGate` hacía passthrough de children con `configured:false`.
 *   4. `DataModeWizard` se podía cerrar, dejando ese mismo estado.
 *
 * Estos tests fijan el comportamiento NUEVO de ambos. Son la mitad de la
 * defensa: si el frontend se parchea, el backend sigue negando (ver
 * `backend/tests/test_activacion.py`). Lo que se verifica acá es que la UI no
 * invite a operar y que el diálogo no sea una salida.
 *
 * El gemelo en `licencia-build-dev.test.tsx` demuestra que el flujo de
 * desarrollo no cambia: ahí el passthrough de "sin configurar" es correcto,
 * porque es el flujo de dev.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// Un archivo por valor de CLIENT_BUILD, y `vi.mock` estático (hoisted), para no
// cargar dos copias de React en el mismo archivo de tests.
vi.mock("@/lib/canyp/build-flags", () => ({ CLIENT_BUILD: true }));

const mockQueries = vi.hoisted(() => ({
  useSettings: vi.fn(),
  useLicencia: vi.fn(),
  useActivacion: vi.fn(),
  useUpdateSettings: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

vi.mock("@/lib/canyp/queries", () => mockQueries);

vi.mock("@/lib/canyp/suscripcion", () => ({
  getClientId: () => "canyp_test",
  obtenerPlanes: vi.fn().mockResolvedValue({ ok: false, planes: [] }),
  crearPreferencia: vi.fn(),
  activarTrial: vi.fn(),
}));

const SIN_LICENCIA = {
  data: { ok: false, activo: false, error: "licencia_no_verificable" },
  isLoading: false,
  isError: false,
  refetch: vi.fn(),
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------

describe("LicenseGate en build de cliente", () => {
  it("BYPASS 1: con configured:false ya NO renderiza los children", async () => {
    // El estado exacto del bypass: nada configurado.
    mockQueries.useSettings.mockReturnValue({
      data: { dataMode: "local", databaseUrl: "", configured: false },
      error: null,
      isLoading: false,
    });
    mockQueries.useLicencia.mockReturnValue(SIN_LICENCIA);

    const { LicenseGate } = await import("../LicenseGate");
    render(
      <LicenseGate>
        <div>APP COMPLETA SIN LICENCIA</div>
      </LicenseGate>,
      { wrapper },
    );

    expect(screen.queryByText("APP COMPLETA SIN LICENCIA")).toBeNull();
  });

  it("sin settings y sin error tampoco renderiza children", async () => {
    // El caso más duro para el atajo: ni siquiera hay dato de `configured`.
    mockQueries.useSettings.mockReturnValue({
      data: undefined,
      error: null,
      isLoading: false,
    });
    mockQueries.useLicencia.mockReturnValue(SIN_LICENCIA);

    const { LicenseGate } = await import("../LicenseGate");
    render(
      <LicenseGate>
        <div>APP COMPLETA SIN LICENCIA</div>
      </LicenseGate>,
      { wrapper },
    );

    expect(screen.queryByText("APP COMPLETA SIN LICENCIA")).toBeNull();
  });

  it("settings en error tampoco renderiza children", async () => {
    mockQueries.useSettings.mockReturnValue({
      data: undefined,
      error: new Error("TypeError: failed to fetch"),
      isLoading: false,
    });
    mockQueries.useLicencia.mockReturnValue(SIN_LICENCIA);

    const { LicenseGate } = await import("../LicenseGate");
    render(
      <LicenseGate>
        <div>APP COMPLETA SIN LICENCIA</div>
      </LicenseGate>,
      { wrapper },
    );

    expect(screen.queryByText("APP COMPLETA SIN LICENCIA")).toBeNull();
  });

  it("muestra la pantalla de licencia (no la app) cuando no hay licencia", async () => {
    mockQueries.useSettings.mockReturnValue({
      data: { dataMode: "remoto", databaseUrl: "***@db", configured: true },
      error: null,
      isLoading: false,
    });
    mockQueries.useLicencia.mockReturnValue(SIN_LICENCIA);

    const { LicenseGate } = await import("../LicenseGate");
    render(
      <LicenseGate>
        <div>APP COMPLETA SIN LICENCIA</div>
      </LicenseGate>,
      { wrapper },
    );

    await waitFor(() => {
      expect(screen.getByText("Activar prueba gratis de 7 días")).toBeInTheDocument();
    });
    expect(screen.queryByText("APP COMPLETA SIN LICENCIA")).toBeNull();
  });

  it("con licencia válida SÍ renderiza los children", async () => {
    // El camino legitimate: no hay que romper la app que sí pagó.
    mockQueries.useSettings.mockReturnValue({
      data: { dataMode: "remoto", databaseUrl: "***@db", configured: true },
      error: null,
      isLoading: false,
    });
    mockQueries.useLicencia.mockReturnValue({
      data: { ok: true, activo: true, tipo: "licencia" },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    const { LicenseGate } = await import("../LicenseGate");
    render(
      <LicenseGate>
        <div>APP CON LICENCIA</div>
      </LicenseGate>,
      { wrapper },
    );

    expect(screen.getByText("APP CON LICENCIA")).toBeInTheDocument();
  });
});

describe("DataModeWizard en build de cliente", () => {
  it("BYPASS 4: el diálogo no se puede cerrar", async () => {
    mockQueries.useSettings.mockReturnValue({
      data: { dataMode: "local", databaseUrl: "", configured: false },
      error: null,
      isLoading: false,
    });

    const { DataModeWizard } = await import("../DataModeWizard");
    const { rerender } = render(<DataModeWizard />, { wrapper });

    expect(screen.getByText("¿Dónde querés guardar los datos?")).toBeInTheDocument();

    // Simula el gesto de cerrar: Escape / clic afuera / la X.
    const dialog = screen.getByRole("dialog");
    dialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    rerender(<DataModeWizard />);

    expect(screen.getByText("¿Dónde querés guardar los datos?")).toBeInTheDocument();
  });

  it("el build de cliente no ofrece la opción local", async () => {
    mockQueries.useSettings.mockReturnValue({
      data: { dataMode: "local", databaseUrl: "", configured: false },
      error: null,
      isLoading: false,
    });

    const { DataModeWizard } = await import("../DataModeWizard");
    render(<DataModeWizard />, { wrapper });

    expect(screen.queryByText("Local")).toBeNull();
    expect(screen.getByText("Remoto")).toBeInTheDocument();
  });
});

afterEach(() => {
  // El vitest de este proyecto corre con `globals: false`, así que el
  // auto-cleanup de Testing Library NO está registrado: sin esto, el DOM del
  // test anterior ensucia las búsquedas del siguiente.
  cleanup();
  vi.unstubAllGlobals();
});
