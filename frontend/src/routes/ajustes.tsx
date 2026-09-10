import { createFileRoute } from "@tanstack/react-router";
import { AlertCircle, CheckCircle2, Database, Cloud } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { DataModeBadge } from "@/components/canyp/DataModeBadge";
import { PageHeader } from "@/components/canyp/AppShell";
import { cn } from "@/lib/utils";
import { useSettings, useUpdateSettings } from "@/lib/canyp/queries";
import type { DataMode } from "@/lib/canyp/types";

export const Route = createFileRoute("/ajustes")({
  head: () => ({
    meta: [
      { title: "Ajustes — CANYP Gestión" },
      {
        name: "description",
        content: "Modo de datos (local o remoto) y base compartida en Supabase.",
      },
      { property: "og:title", content: "Ajustes — CANYP Gestión" },
      {
        property: "og:description",
        content: "Elegí dónde se guardan los datos y configurá la conexión remota.",
      },
    ],
  }),
  component: AjustesPage,
});

function AjustesPage() {
  const { data: settings, isLoading } = useSettings();
  const updateSettings = useUpdateSettings();
  const [mode, setMode] = useState<DataMode>("local");
  const [url, setUrl] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings) {
      setMode(settings.dataMode);
      setUrl(settings.databaseUrl);
      setSaved(false);
    }
  }, [settings]);

  function guardar() {
    updateSettings.mutate(
      { dataMode: mode, ...(mode === "remoto" ? { databaseUrl: url.trim() } : {}) },
      {
        onSuccess: () => {
          setSaved(true);
          toast.success("Ajustes guardados");
        },
        onError: (e) => toast.error(e.message || "No se pudieron guardar los ajustes"),
      },
    );
  }

  if (isLoading) {
    return (
      <>
        <PageHeader title="Ajustes" subtitle="Cargando..." />
        <Card className="p-10 text-center text-sm text-muted-foreground">Cargando ajustes...</Card>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Ajustes"
        subtitle="Modo de datos del sistema"
        actions={
          <span className="text-xs text-muted-foreground">
            Modo actual: <DataModeBadge />
          </span>
        }
      />

      <Card className="max-w-2xl space-y-6 p-6">
        <div>
          <Label className="text-sm font-semibold">Dónde se guardan los datos</Label>
          <RadioGroup
            value={mode}
            onValueChange={(v) => setMode(v as DataMode)}
            className="mt-3 gap-3"
          >
            <ModeOption
              selected={mode === "local"}
              icon={<Database className="size-4 text-muted-foreground" />}
              title="Local"
              description="Funciona sin internet. Los datos quedan solo en esta PC."
            />
            <ModeOption
              selected={mode === "remoto"}
              icon={<Cloud className="size-4 text-sky-600" />}
              title="Remoto"
              description="Base compartida en Supabase: varias PCs ven lo mismo."
            />
          </RadioGroup>
        </div>

        {mode === "remoto" && (
          <div className="space-y-2">
            <Label htmlFor="ajustes-db-url">Cadena de conexión (Supabase)</Label>
            <Input
              id="ajustes-db-url"
              type="password"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="postgresql://user:***@host:5432/db"
              autoComplete="off"
            />
            <p className="text-xs text-muted-foreground">
              Usá la cadena de tu base Supabase (session pooler). Sin este dato no se puede pasarse
              al modo remoto.
            </p>
          </div>
        )}

        <div className="flex items-center gap-3">
          <Button onClick={guardar} disabled={updateSettings.isPending}>
            Guardar
          </Button>
          {saved && (
            <p className="flex items-center gap-1.5 text-sm text-warning-foreground">
              <AlertCircle className="size-4" />
              El cambio se aplica al reiniciar la aplicación.
            </p>
          )}
        </div>

        {settings?.configured && mode === settings.dataMode && !saved && (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <CheckCircle2 className="size-4 text-success" />
            Modo confirmado:{" "}
            {mode === "local" ? "datos locales (SQLite)" : "base remota (PostgreSQL)"}.
          </p>
        )}
      </Card>
    </>
  );
}

function ModeOption({
  selected,
  icon,
  title,
  description,
}: {
  selected: boolean;
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div
      className={cn(
        "flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors",
        selected
          ? "border-primary bg-accent/50"
          : "border-border hover:border-primary/40 hover:bg-accent/30",
      )}
    >
      <RadioGroupItem
        value={title.toLowerCase()}
        id={`ajustes-mode-${title.toLowerCase()}`}
        className="mt-0.5"
      />
      <Label
        htmlFor={`ajustes-mode-${title.toLowerCase()}`}
        className="flex items-start gap-2 font-medium"
      >
        {icon}
        <span>
          {title}
          <span className="mt-0.5 block text-xs font-normal text-muted-foreground">
            {description}
          </span>
        </span>
      </Label>
    </div>
  );
}
