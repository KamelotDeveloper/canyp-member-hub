import { cn } from "@/lib/utils";
import { estadoLabel, type EstadoVisual } from "@/lib/canyp/utils";

const styles: Record<EstadoVisual, string> = {
  activa: "bg-success/12 text-success border-success/30",
  por_vencer: "bg-warning/20 text-warning-foreground border-warning/50",
  vencida: "bg-danger/12 text-danger border-danger/30",
  suspendida: "bg-info/12 text-info border-info/30",
  baja: "bg-muted text-muted-foreground border-border",
};

export function EstadoBadge({ estado, className }: { estado: EstadoVisual; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap",
        styles[estado],
        className,
      )}
    >
      <span className="size-1.5 rounded-full bg-current" />
      {estadoLabel[estado]}
    </span>
  );
}
