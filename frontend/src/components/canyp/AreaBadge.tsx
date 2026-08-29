import { cn } from "@/lib/utils";
import type { Area } from "@/lib/canyp/types";

const styles: Record<Area, string> = {
  Cabañeros: "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30",
  Balseros: "bg-sky-500/15 text-sky-700 dark:text-sky-300 border-sky-500/30",
  Guardería: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30",
  Windsurf: "bg-violet-500/15 text-violet-700 dark:text-violet-300 border-violet-500/30",
};

export function AreaBadge({ area, className }: { area: Area; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap",
        styles[area],
        className,
      )}
    >
      <span className="size-1.5 rounded-full bg-current" />
      {area}
    </span>
  );
}
