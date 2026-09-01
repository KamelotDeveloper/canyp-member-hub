import { useMemo, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { StepFileSelect } from "@/components/import/StepFileSelect";
import { StepPreviewEdit, type ImportColumnSpec } from "@/components/import/StepPreviewEdit";
import { StepConfirmResult } from "@/components/import/StepConfirmResult";
import { usePreviewImport, useExecuteImport } from "@/lib/canyp/queries";
import type { ExecuteResult, FieldError, PreviewResult, RowData } from "@/lib/canyp/types";
import { cn } from "@/lib/utils";

const STEPS = ["Subir archivo", "Revisar y editar", "Confirmar"];

export interface ImportModalProps {
  /** Slash-less plural resource name, e.g. "socios". */
  resource: string;
  /** Human label for the modal, e.g. "socios". */
  resourceLabel: string;
  /** Editable column spec: Spanish label + English canonical field. */
  columnSpec: ImportColumnSpec[];
  /** Controls the Dialog open state (parent-driven). */
  open?: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after a successful import so the page can refetch. */
  onImportComplete?: () => void;
}

/**
 * Top-level reusable modal for the generic 3-step data import flow.
 *
 * Steps:
 *   1. StepFileSelect — pick a file, server-side preview.
 *   2. StepPreviewEdit — review/edit rows, flag skips, export errors.
 *   3. StepConfirmResult — execute the batch, show the outcome.
 *
 * The parent controls the Dialog open state; this component owns the step
 * state machine, the preview/execute mutations and the edited rows.
 */
export function ImportModal({
  resource,
  resourceLabel,
  columnSpec,
  open,
  onOpenChange,
  onImportComplete,
}: ImportModalProps) {
  const previewMutation = usePreviewImport();
  const executeMutation = useExecuteImport();

  const [step, setStep] = useState(0);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [rows, setRows] = useState<RowData[]>([]);
  const [executeResult, setExecuteResult] = useState<ExecuteResult | null>(null);
  const [executeError, setExecuteError] = useState<string | null>(null);

  // Errors grouped by row array index -> per-field errors (fila is 1-based).
  const errorsByRow = useMemo(() => {
    const map: Record<number, FieldError[]> = {};
    for (const e of preview?.errors ?? []) {
      const idx = e.fila - 1;
      (map[idx] ??= []).push(e);
    }
    return map;
  }, [preview]);

  function handleFile(file: File) {
    previewMutation.mutate(
      { resource, file },
      {
        onSuccess: (p) => {
          setPreview(p);
          setRows(p.rows.map((data) => ({ skip: false, data })));
          setExecuteResult(null);
          setExecuteError(null);
          setStep(1);
        },
      },
    );
  }

  function handleChangeIndex(index: number, field: string, value: string) {
    setRows((prev) =>
      prev.map((r, i) => (i === index ? { ...r, data: { ...r.data, [field]: value } } : r)),
    );
  }

  function handleToggleSkip(index: number, skip: boolean) {
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, skip } : r)));
  }

  function handleExecute() {
    setExecuteResult(null);
    setExecuteError(null);
    executeMutation.mutate(
      { resource, rows },
      {
        onSuccess: (res) => {
          setExecuteResult(res);
          setStep(2);
        },
        onError: (err) => {
          setExecuteError(err instanceof Error ? err.message : "Error al importar");
        },
      },
    );
  }

  function goToConfirm() {
    setStep(2);
  }

  function handleFinalize() {
    onImportComplete?.();
    onOpenChange(false);
  }

  return (
    <Dialog open={open ?? true} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>{`Importar ${resourceLabel}`}</DialogTitle>
          <DialogDescription>
            Cargá un archivo .csv o .xlsx, revisá los datos y confirmá la importación.
          </DialogDescription>
        </DialogHeader>

        {/* Lightweight step indicator */}
        <div className="flex items-center gap-2">
          {STEPS.map((label, i) => (
            <div key={label} className="flex items-center gap-2">
              <div
                className={cn(
                  "flex items-center gap-1.5",
                  i === step && "text-primary",
                  i < step && "text-muted-foreground",
                  i > step && "text-muted-foreground/50",
                )}
              >
                <span
                  className={cn(
                    "flex size-5 items-center justify-center rounded-full text-xs font-semibold",
                    i === step && "bg-primary text-primary-foreground",
                    i < step && "bg-accent",
                    i > step && "bg-muted",
                  )}
                >
                  {i + 1}
                </span>
                <span className="text-xs font-medium">{label}</span>
              </div>
              {i < STEPS.length - 1 && <Separator className="w-6" />}
            </div>
          ))}
        </div>

        <Separator />

        {step === 0 && (
          <StepFileSelect
            resource={resource}
            resourceLabel={resourceLabel}
            loading={previewMutation.isPending}
            onFile={handleFile}
            onBack={() => onOpenChange(false)}
          />
        )}

        {step === 1 && preview && (
          <StepPreviewEdit
            resourceLabel={resourceLabel}
            columnSpec={columnSpec}
            columns={preview.columns}
            ignoredColumns={preview.ignoredColumns}
            stats={preview.stats}
            rows={rows}
            errorsByRow={errorsByRow}
            onToggleSkip={handleToggleSkip}
            onChange={handleChangeIndex}
            onBack={() => setStep(0)}
            onContinue={goToConfirm}
          />
        )}

        {step === 2 && (
          <StepConfirmResult
            resourceLabel={resourceLabel}
            isExecuting={executeMutation.isPending}
            result={executeResult}
            error={executeError}
            onExecute={handleExecute}
            onFinalize={handleFinalize}
            onBack={() => {
              setExecuteResult(null);
              setExecuteError(null);
              setStep(1);
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
