import { cn } from "@/lib/utils";
import type { EstadoSocio } from "@/lib/canyp/types";

/**
 * Badge de los 4 estados de socio SERVIDOS por el backend (EST-01, UI-04).
 *
 * El `estado` ES la nominación exacta que sirvió el servidor (em dash incluido):
 * este componente la muestra tal cual, sin parafrasear ni re-derivar nada.
 */
const styles: Record<EstadoSocio, string> = {
  "Socio activo": "bg-success/12 text-success border-success/30",
  "Socio activo — revisar": "bg-warning/20 text-warning-foreground border-warning/50",
  "Inactivo — revisar": "bg-danger/12 text-danger border-danger/30",
  "Solo cuota social": "bg-muted text-muted-foreground border-border",
};

export function EstadoBadge({ estado, className }: { estado: EstadoSocio; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap",
        styles[estado],
        className,
      )}
    >
      <span className="size-1.5 rounded-full bg-current" />
      {estado}
    </span>
  );
}
