import { cn } from "@/lib/utils";
import { CONCEPTO_LABELS } from "@/lib/canyp/arancel-helpers";
import type { ConceptoCobro } from "@/lib/canyp/types";

const styles: Record<ConceptoCobro, string> = {
  area: "bg-sky-500/15 text-sky-700 dark:text-sky-300 border-sky-500/30",
  servicio: "bg-cyan-500/15 text-cyan-700 dark:text-cyan-300 border-cyan-500/30",
  "cuota social": "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30",
  recargo: "bg-rose-500/15 text-rose-700 dark:text-rose-300 border-rose-500/30",
};

/**
 * Concepto que precio la fila del catálogo (ReQ-013).
 *
 * Sin concepto se muestra "—" en vez de asumir `area`: la columna es NOT NULL
 * en el backend, así que un "—" es una respuesta vieja, y taparla con un
 * `area` inventado reproduciría la ambigüedad que esta columna existe para
 * evitar.
 */
export function ConceptoBadge({
  concepto,
  className,
}: {
  concepto: ConceptoCobro | undefined;
  className?: string;
}) {
  if (!concepto) {
    return <span className={cn("text-xs text-muted-foreground", className)}>—</span>;
  }
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap",
        styles[concepto],
        className,
      )}
    >
      <span className="size-1.5 rounded-full bg-current" />
      {CONCEPTO_LABELS[concepto]}
    </span>
  );
}
