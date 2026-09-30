/**
 * El gemelo de `licencia-build-cliente.test.tsx`: en DESARROLLO (sin
 * `CANYP_CLIENT_BUILD=1`) el comportamiento tiene que ser EXACTAMENTE el de
 * antes.
 *
 * Esto es el riesgo #1 del trabajo: una defensa de licencias que rompa el flujo
 * de desarrollo es un desastre operacional, porque nadie puede trabajar en el
 * proyecto ni probar sus propias fixes. Por eso hay un archivo de tests
 * espejo que afirma lo contrario del anterior, en el mismo commit.
 *
 * Lo que debe seguir funcionando en dev:
 *   - `configured:false` abre la app (SQLite local es el modo de dev).
 *   - El wizard se puede cerrar.
 *   - El wizard ofrece la opción "Local".
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("@/lib/canyp/build-flags", () => ({ CLIENT_BUILD: false }));

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

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const SIN_CONFIGURAR = {
  data: { dataMode: "local", databaseUrl: "", configured: false },
  error: null,
  isLoading: false,
};

// `globals: false` en vitest.config.ts => sin auto-cleanup de Testing Library.
afterEach(cleanup);

describe("LicenseGate en desarrollo", () => {
  it("configured:false abre la app (SQLite local es el modo de dev)", async () => {
    mockQueries.useSettings.mockReturnValue(SIN_CONFIGURAR);
    mockQueries.useLicencia.mockReturnValue({
      data: { ok: false, activo: false },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    const { LicenseGate } = await import("../LicenseGate");
    render(
      <LicenseGate>
        <div>APP DE DESARROLLO</div>
      </LicenseGate>,
      { wrapper },
    );

    expect(screen.getByText("APP DE DESARROLLO")).toBeInTheDocument();
  });

  it("settings en error también abre la app en dev", async () => {
    mockQueries.useSettings.mockReturnValue({
      data: undefined,
      error: new Error("TypeError: failed to fetch"),
      isLoading: false,
    });
    mockQueries.useLicencia.mockReturnValue({
      data: { ok: false, activo: false },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    const { LicenseGate } = await import("../LicenseGate");
    render(
      <LicenseGate>
        <div>APP DE DESARROLLO</div>
      </LicenseGate>,
      { wrapper },
    );

    expect(screen.getByText("APP DE DESARROLLO")).toBeInTheDocument();
  });

  it("configurado y sin licencia SÍ muestra la pantalla de planes", async () => {
    // El gate de licencia de dev tiene que seguir haciendo su trabajo.
    mockQueries.useSettings.mockReturnValue({
      data: { dataMode: "local", databaseUrl: "", configured: true },
      error: null,
      isLoading: false,
    });
    mockQueries.useLicencia.mockReturnValue({
      data: { ok: false, activo: false },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    const { LicenseGate } = await import("../LicenseGate");
    render(
      <LicenseGate>
        <div>APP DE DESARROLLO</div>
      </LicenseGate>,
      { wrapper },
    );

    expect(screen.getByText("Activar prueba gratis de 7 días")).toBeInTheDocument();
    expect(screen.queryByText("APP DE DESARROLLO")).toBeNull();
  });
});

describe("DataModeWizard en desarrollo", () => {
  it("ofrece la opción Local", async () => {
    mockQueries.useSettings.mockReturnValue(SIN_CONFIGURAR);

    const { DataModeWizard } = await import("../DataModeWizard");
    render(<DataModeWizard />, { wrapper });

    expect(screen.getByText("Local")).toBeInTheDocument();
    expect(screen.getByText("Remoto")).toBeInTheDocument();
  });

  it("el diálogo se puede cerrar en dev", async () => {
    // Descartar el asistente es un flujo legítimo de desarrollo: se entra a la
    // app con SQLite sin configurar nada. Sólo se cerró el loophole en cliente.
    mockQueries.useSettings.mockReturnValue(SIN_CONFIGURAR);

    const { DataModeWizard } = await import("../DataModeWizard");
    const { rerender } = render(<DataModeWizard />, { wrapper });

    expect(screen.getByText("¿Dónde querés guardar los datos?")).toBeInTheDocument();

    const dialog = screen.getByRole("dialog");
    dialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    rerender(<DataModeWizard />);

    expect(screen.queryByText("¿Dónde querés guardar los datos?")).toBeNull();
  });
});
