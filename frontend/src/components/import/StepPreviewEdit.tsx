import { useMemo, useState } from "react";
import { AlertTriangle, ChevronLeft, ChevronRight, Download, Inbox } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { EditableCell } from "@/components/import/EditableCell";
import { downloadCsv } from "@/components/import/downloads";
import type { FieldError, HeadersMapping, ImportStats, RowData } from "@/lib/canyp/types";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

export interface ImportColumnSpec {
  /** Spanish label to display in the UI. */
  label: string;
  /** Canonical English field, e.g. "nombre". */
  field: string;
}

export interface StepPreviewEditProps {
  resourceLabel: string;
  /** Canonical editable fields: Spanish label + English field (order + labels). */
  columnSpec: ImportColumnSpec[];
  /** Detected source header -> canonical field (from PreviewResult.columns). */
  columns: HeadersMapping;
  ignoredColumns: string[];
  stats: ImportStats;
  /** Edited rows (skip flag + canonical data). */
  rows: RowData[];
  /** Errors grouped by row array index -> per-field errors. */
  errorsByRow: Record<number, FieldError[]>;
  onToggleSkip: (index: number, skip: boolean) => void;
  onChange: (index: number, field: string, value: string) => void;
  onBack: () => void;
  onContinue: () => void;
}

/** Renders "Columna: campo" or similar label for a mapped header cell. */
export function StepPreviewEdit({
  resourceLabel,
  columnSpec,
  columns,
  ignoredColumns,
  stats,
  rows,
  errorsByRow,
  onToggleSkip,
  onChange,
  onBack,
  onContinue,
}: StepPreviewEditProps) {
  const [page, setPage] = useState(0);

  // Detect the Spanish source header for each canonical field.
  const fieldToSource = useMemo(() => {
    const map: Record<string, string> = {};
    for (const [source, field] of Object.entries(columns)) map[field] = source;
    return map;
  }, [columns]);

  // Fields actually detected by the backend (they appear as a mapping value).
  const detectedFields = useMemo(() => new Set(Object.values(columns)), [columns]);

  // Render only the canonical fields actually detected, in columnSpec order.
  const colSpec = useMemo(
    () => columnSpec.filter((spec) => detectedFields.has(spec.field)),
    [columnSpec, detectedFields],
  );
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageRows = rows.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);

  function errorFor(index: number, field: string): string | undefined {
    return (errorsByRow[index] ?? []).find((e) => e.campo === field)?.error;
  }
  function rowErrors(index: number): FieldError[] {
    return errorsByRow[index] ?? [];
  }

  function descargarErrores() {
    type ErrRow = { fila: number; campo: string; error: string; valor: unknown };
    const errRows: ErrRow[] = [];
    colSpec.forEach((spec) => {
      const field = spec.field;
      rows.forEach((row, i) => {
        const e = rowErrors(i).find((x) => x.campo === field);
        if (e)
          errRows.push({ fila: i + 1, campo: e.campo, error: e.error, valor: row.data[field] });
      });
    });
    errRows.sort((a, b) => a.fila - b.fila);
    downloadCsv(`${resourceLabel}_errores.csv`, ["fila", "campo", "error", "valor"], errRows);
  }

  return (
    <div className="space-y-4">
      {/* Stats banner */}
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge>Total: {stats.total}</Badge>
        <Badge variant="secondary">Válidas: {stats.validas}</Badge>
        <Badge variant="destructive">Con errores: {stats.conErrores}</Badge>
        <Badge variant="outline">A saltar: {stats.aSaltar}</Badge>
        <Button variant="ghost" size="sm" className="ml-auto" onClick={descargarErrores}>
          <Download className="size-4" />
          Descargar errores
        </Button>
      </div>

      {/* Ignored columns banner */}
      {ignoredColumns.length > 0 && (
        <div className="flex items-start gap-2 rounded-md border border-warning/50 bg-warning/10 p-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
          <p className="text-muted-foreground">
            Columnas ignoradas (no se importan):{" "}
            <span className="font-medium text-foreground">{ignoredColumns.join(", ")}</span>
          </p>
        </div>
      )}

      {/* Editable table */}
      <ScrollArea className="h-[420px] rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">
                <span className="sr-only">Omitir</span>
              </TableHead>
              {colSpec.map((spec) => (
                <TableHead key={spec.field} className="min-w-[140px] whitespace-nowrap">
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="cursor-help">{fieldToSource[spec.field] ?? spec.label}</span>
                    </TooltipTrigger>
                    <TooltipContent>{spec.field}</TooltipContent>
                  </Tooltip>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {pageRows.map((row, pageIdx) => {
              const index = safePage * PAGE_SIZE + pageIdx;
              const hasErrors = rowErrors(index).length > 0;
              const isSkipped = !!row.skip;
              return (
                <TableRow
                  key={index}
                  className={cn(
                    hasErrors && "bg-danger/5",
                    !hasErrors && !isSkipped && "bg-success/5",
                    isSkipped && "opacity-50",
                  )}
                >
                  <TableCell>
                    <Checkbox
                      aria-label={`Omitir fila ${index + 1}`}
                      checked={isSkipped}
                      onCheckedChange={(v) => onToggleSkip(index, v === true)}
                    />
                  </TableCell>
                  {colSpec.map((spec) => (
                    <TableCell key={spec.field}>
                      <EditableCell
                        field={spec.field}
                        value={row.data[spec.field]}
                        error={errorFor(index, spec.field)}
                        disabled={isSkipped}
                        onChange={(f, v) => onChange(index, f, v)}
                      />
                    </TableCell>
                  ))}
                </TableRow>
              );
            })}
            {rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={colSpec.length + 1} className="py-10 text-center">
                  <Inbox className="mx-auto mb-2 size-6 text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">No hay filas para revisar.</p>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </ScrollArea>

      {/* Pagination */}
      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>
          Página {safePage + 1} de {pageCount} · {rows.length} filas
        </span>
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="icon"
            className="size-8"
            disabled={safePage === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            <ChevronLeft className="size-4" />
          </Button>
          <Button
            variant="outline"
            size="icon"
            className="size-8"
            disabled={safePage >= pageCount - 1}
            onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
      </div>

      <Separator />

      <div className="flex items-center justify-end gap-2">
        <Button variant="outline" onClick={onBack}>
          Volver
        </Button>
        <Button onClick={onContinue} disabled={rows.length === 0}>
          Continuar
        </Button>
      </div>
    </div>
  );
}
