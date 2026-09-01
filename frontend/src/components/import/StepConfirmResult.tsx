import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, Download, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { downloadJson } from "@/components/import/downloads";
import type { ExecuteResult } from "@/lib/canyp/types";

export interface StepConfirmResultProps {
  resourceLabel: string;
  /** True while the execute mutation is in flight. */
  isExecuting: boolean;
  /** Result after execution completes (null while running / on error). */
  result: ExecuteResult | null;
  /** Human-readable error when execution failed entirely. */
  error?: string | null;
  /** Invoked once on mount to run the import. */
  onExecute: () => void;
  /** Close the modal and let the caller refresh. */
  onFinalize: () => void;
  /** Go back to the edit step (available when nothing was imported). */
  onBack: () => void;
}

/**
 * Step 3 — confirm/result: triggers the execute mutation on mount, shows a
 * simulated progress bar while it runs, then summarizes importados/fallidos/
 * omitidos with a per-row error list and a downloadable JSON log.
 */
export function StepConfirmResult({
  resourceLabel,
  isExecuting,
  result,
  error,
  onExecute,
  onFinalize,
  onBack,
}: StepConfirmResultProps) {
  const fired = useRef(false);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    if (fired.current) return;
    fired.current = true;
    onExecute();
  }, [onExecute]);

  // Simulated progress while the backend processes the batch.
  useEffect(() => {
    if (!isExecuting) return;
    setProgress(8);
    const id = setInterval(() => {
      setProgress((p) => Math.min(92, p + Math.random() * 14));
    }, 250);
    return () => clearInterval(id);
  }, [isExecuting]);

  useEffect(() => {
    if (result) {
      setProgress(100);
      if (result.fallidos > 0) toast.warning("Importación con algunos errores");
      else toast.success("Importación finalizada");
    }
  }, [result]);

  function descargarLog() {
    downloadJson(`${resourceLabel}_import_log.json`, result);
  }

  if (error) {
    return (
      <Alert variant="destructive">
        <XCircle className="size-4" />
        <AlertTitle>No se pudo importar</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={onBack}>
            Volver a editar
          </Button>
        </div>
      </Alert>
    );
  }

  if (isExecuting || !result) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <div className="animate-spin rounded-full border-2 border-primary border-t-transparent size-4" />
          <p className="text-sm text-muted-foreground">Procesando importación…</p>
        </div>
        <Progress value={progress} />
      </div>
    );
  }

  const allErrored = result.importados === 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <CheckCircle2 className="size-4 text-success" />
        <p className="text-sm font-medium">Importación finalizada</p>
      </div>

      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="rounded-md border border-border bg-muted/30 p-3">
          <p className="text-xl font-semibold text-success">{result.importados}</p>
          <p className="text-xs text-muted-foreground">Importados</p>
        </div>
        <div className="rounded-md border border-border bg-muted/30 p-3">
          <p className="text-xl font-semibold text-danger">{result.fallidos}</p>
          <p className="text-xs text-muted-foreground">Fallidos</p>
        </div>
        <div className="rounded-md border border-border bg-muted/30 p-3">
          <p className="text-xl font-semibold">{result.omitidos}</p>
          <p className="text-xs text-muted-foreground">Omitidos</p>
        </div>
      </div>

      <Separator />

      {result.fallidos > 0 && (
        <div className="space-y-2">
          <p className="text-sm font-medium">Errores por fila</p>
          <div className="max-h-40 space-y-1.5 overflow-y-auto rounded-md border border-border p-2">
            {result.rows
              .filter((r) => r.outcome === "fallido")
              .map((r, i) => (
                <div key={i} className="flex items-start gap-2 text-sm">
                  <Badge variant="destructive" className="shrink-0">
                    Fila {r.fila}
                  </Badge>
                  <span className="text-muted-foreground">
                    {r.errores?.map((e) => `${e.campo}: ${e.error}`).join(" · ") ?? "Error"}
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}

      <div className="flex items-center justify-end gap-2">
        <Button variant="outline" onClick={descargarLog}>
          <Download className="size-4" />
          Descargar log
        </Button>
        {allErrored && (
          <Button variant="outline" onClick={onBack}>
            Volver a editar
          </Button>
        )}
        <Button onClick={onFinalize}>Finalizar</Button>
      </div>
    </div>
  );
}
