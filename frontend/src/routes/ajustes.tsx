import { createFileRoute } from "@tanstack/react-router";
import { Cloud, FolderOpen } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/canyp/AppShell";

export const Route = createFileRoute("/ajustes")({
  head: () => ({
    meta: [
      { title: "Ajustes — CANYP Gestión" },
      {
        name: "description",
        content: "Diagnóstico y registros del sistema.",
      },
      { property: "og:title", content: "Ajustes — CANYP Gestión" },
      {
        property: "og:description",
        content: "Diagnóstico y registros del sistema.",
      },
    ],
  }),
  component: AjustesPage,
});

function AjustesPage() {
  return (
    <>
      <PageHeader
        title="Ajustes"
        subtitle="Base de datos compartida"
        actions={
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Cloud className="size-4 text-sky-600" />
            Remoto (Supabase)
          </span>
        }
      />

      <DiagnosticoCard />
    </>
  );
}

/** Abre la carpeta de logs del sistema en el explorador (solo escritorio). */
async function abrirCarpetaLogs(): Promise<void> {
  const inTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
  if (!inTauri) {
    toast.info("Disponible solo en la aplicación de escritorio");
    return;
  }
  try {
    const internals = (
      window as unknown as { __TAURI_INTERNALS__: { invoke: (c: string) => Promise<unknown> } }
    ).__TAURI_INTERNALS__;
    await internals.invoke("open_logs_folder");
  } catch (e) {
    toast.error(e instanceof Error ? e.message : "No se pudo abrir la carpeta de registros");
  }
}

function DiagnosticoCard() {
  return (
    <Card className="max-w-2xl space-y-3 p-6">
      <div>
        <Label className="text-sm font-semibold">Diagnóstico</Label>
        <p className="mt-1 text-xs text-muted-foreground">
          Si algo falla, abrí esta carpeta y adjuntá el archivo <code>CANYP Gestion.log</code> al
          reporte para que podamos ver qué pasó.
        </p>
      </div>
      <Button variant="outline" onClick={() => void abrirCarpetaLogs()}>
        <FolderOpen className="size-4" />
        Abrir carpeta de registros
      </Button>
    </Card>
  );
}
