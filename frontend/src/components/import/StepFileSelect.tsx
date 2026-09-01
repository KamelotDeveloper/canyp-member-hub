import { useRef, useState } from "react";
import { toast } from "sonner";
import { Upload, FileSpreadsheet, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { getImportTemplate } from "@/lib/canyp/api";
import { downloadBlob } from "@/components/import/downloads";
import { cn } from "@/lib/utils";

const MAX_FILE_BYTES = 10 * 1024 * 1024; // 10MB
const ALLOWED_EXTENSIONS = [".csv", ".xlsx", ".xls"];

export interface StepFileSelectProps {
  /** Slash-less resource name, e.g. "socios". Used for the template download. */
  resource: string;
  /** Human label for the resource, e.g. "socios". */
  resourceLabel: string;
  /** True while the parent runs the preview mutation. */
  loading?: boolean;
  /** Called with a valid file so the parent can run previewImport. */
  onFile: (file: File) => void;
  /** Called when the user wants to start over (step 1 back). */
  onBack?: () => void;
}

/**
 * Step 1 — file selection: drag-and-drop + browse.
 *
 * Validates extension (.csv/.xlsx/.xls) and size (≤10MB) before handing the
 * file to `onFile`, which triggers the server-side preview. Also offers the
 * "Descargar plantilla" template download.
 */
export function StepFileSelect({
  resource,
  resourceLabel,
  loading,
  onFile,
  onBack,
}: StepFileSelectProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function acceptFile(file: File | undefined | null) {
    if (!file) return;
    const ext = "." + (file.name.split(".").pop() ?? "").toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      toast.error("Formato no válido. Subí un archivo .csv o .xlsx");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      toast.error("El archivo supera el límite de 10 MB");
      return;
    }
    onFile(file);
  }

  return (
    <div className="space-y-4">
      <Label>{`Importar ${resourceLabel}`}</Label>

      <div
        role="button"
        tabIndex={0}
        aria-label="Subir archivo"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          acceptFile(e.dataTransfer.files?.[0]);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-10 text-center transition-colors",
          dragging ? "border-primary bg-primary/5" : "border-border bg-muted/30 hover:bg-muted/50",
        )}
      >
        {loading ? (
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        ) : (
          <Upload className="size-6 text-muted-foreground" />
        )}
        <p className="text-sm font-medium">
          {loading ? "Analizando archivo…" : "Arrastrá tu archivo acá o hacé clic para elegir"}
        </p>
        <p className="text-xs text-muted-foreground">Formato .csv o .xlsx · Máximo 10 MB</p>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".csv,.xlsx,.xls"
        className="hidden"
        disabled={loading}
        onChange={(e) => {
          acceptFile(e.target.files?.[0]);
          e.target.value = "";
        }}
      />

      <div className="flex items-center justify-between border-t border-border pt-4">
        <Button variant="ghost" size="sm" onClick={onBack}>
          Cancelar
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={async () => {
            try {
              const blob = await getImportTemplate(resource);
              downloadBlob(blob, `${resource}_import_template.xlsx`);
              toast.success("Plantilla descargada");
            } catch {
              toast.error("No se pudo descargar la plantilla");
            }
          }}
        >
          <FileSpreadsheet className="size-4" />
          Descargar plantilla
        </Button>
      </div>
    </div>
  );
}
