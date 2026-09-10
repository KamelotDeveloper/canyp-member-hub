import { cn } from "@/lib/utils";
import type { DataMode } from "@/lib/canyp/types";
import { useSettings } from "@/lib/canyp/queries";

const styles: Record<DataMode, string> = {
  local: "bg-muted text-muted-foreground border-border",
  remoto: "bg-sky-500/15 text-sky-700 dark:text-sky-300 border-sky-500/30",
};

const labels: Record<DataMode, string> = {
  local: "LOCAL",
  remoto: "NUBE",
};

/** Badge persistente en la app: muestra el modo de datos actual. */
export function DataModeBadge({ className }: { className?: string }) {
  const { data } = useSettings();
  if (!data) return null;
  const mode = data.dataMode;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] font-bold tracking-widest whitespace-nowrap",
        styles[mode],
        className,
      )}
    >
      <span className="size-1.5 rounded-full bg-current" />
      {labels[mode]}
    </span>
  );
}
