import { Database, Cloud } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { cn } from "@/lib/utils";
import { useSettings, useUpdateSettings } from "@/lib/canyp/queries";
import type { DataMode } from "@/lib/canyp/types";

/**
 * Wizard de primer uso: aparece una sola vez (hasta que se guarda la elección
 * del modo de datos). No se muestra si el backend no responde.
 */
export function DataModeWizard() {
  const { data, isLoading, isError } = useSettings();
  const updateSettings = useUpdateSettings();
  const [dismissed, setDismissed] = useState(false);
  const [mode, setMode] = useState<DataMode>("local");
  const [url, setUrl] = useState("");

  if (isLoading || isError || !data || data.configured) return null;

  const open = !dismissed;

  function guardar() {
    updateSettings.mutate(
      { dataMode: mode, ...(mode === "remoto" ? { databaseUrl: url.trim() } : {}) },
      {
        onSuccess: () => {
          setDismissed(true);
          toast.success("Preferencias guardadas");
        },
        onError: (e) => {
          toast.error(e.message || "No se pudieron guardar las preferencias");
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && setDismissed(true)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>¿Dónde querés guardar los datos?</DialogTitle>
          <DialogDescription>
            Elegí cómo CANYP almacena la información. Podés cambiarlo más tarde en Ajustes.
          </DialogDescription>
        </DialogHeader>

        <RadioGroup value={mode} onValueChange={(v) => setMode(v as DataMode)} className="gap-3">
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

        {mode === "remoto" && (
          <div className="space-y-2">
            <Label htmlFor="wizard-db-url">Cadena de conexión</Label>
            <Input
              id="wizard-db-url"
              type="password"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="postgresql://user:***@host:5432/db"
              autoComplete="off"
            />
            <p className="text-xs text-muted-foreground">
              La pega de tu base Supabase. Sin este dato no se puede usar el modo remoto.
            </p>
          </div>
        )}

        <Button onClick={guardar} disabled={updateSettings.isPending} className="w-full">
          Continuar
        </Button>
      </DialogContent>
    </Dialog>
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
        id={`mode-${title.toLowerCase()}`}
        className="mt-0.5"
      />
      <Label htmlFor={`mode-${title.toLowerCase()}`} className="flex items-start gap-2 font-medium">
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
