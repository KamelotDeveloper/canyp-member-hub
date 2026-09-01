import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export interface EditableCellProps {
  /** Canonical field name (English), e.g. "nombre". */
  field: string;
  /** Current cell value (any primitive the backend row holds). */
  value: unknown;
  /** Validation error message for this cell, if any. */
  error?: string | undefined;
  disabled?: boolean;
  /** Called with the raw string typed by the user. */
  onChange: (field: string, value: string) => void;
  /** Render a multi-line Textarea instead of a single-line Input. */
  multiline?: boolean;
}

/**
 * Reusable inline-editable table cell for the import preview.
 *
 * Shows the current value in an Input (or Textarea), lets the user edit it in
 * place, and renders a destructive Tooltip with the field error when present.
 * Controlled: the parent owns row data; `onChange` reports edits upstream.
 */
export function EditableCell({
  field,
  value,
  error,
  disabled,
  onChange,
  multiline = false,
}: EditableCellProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {multiline ? (
          <textarea
            className={cn(
              "flex min-h-[56px] w-full rounded-md border px-2 py-1.5 text-sm shadow-sm",
              "bg-transparent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
              disabled && "opacity-50",
              error
                ? "border-danger text-danger focus-visible:ring-danger"
                : "border-input focus-visible:ring-ring",
            )}
            value={value == null ? "" : String(value)}
            disabled={disabled}
            onChange={(e) => onChange(field, e.target.value)}
          />
        ) : (
          <Input
            className={cn(
              "h-8 px-2 text-sm",
              error && "border-danger text-danger focus-visible:ring-danger",
            )}
            value={value == null ? "" : String(value)}
            disabled={disabled}
            onChange={(e) => onChange(field, e.target.value)}
          />
        )}
      </TooltipTrigger>
      {error ? (
        <TooltipContent className="max-w-xs border-danger/50 bg-destructive text-destructive-foreground">
          {error}
        </TooltipContent>
      ) : null}
    </Tooltip>
  );
}
