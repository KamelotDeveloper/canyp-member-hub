import { useMemo, useState } from "react";
import { Check, ChevronsUpDown, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type { Socio } from "@/lib/canyp/types";

interface SocioComboboxProps {
  /** socioId seleccionado; "todos" (con allowEmpty) o "" sin selección. */
  value: string;
  /** Se llama con el socioId elegido ("todos" / "" al limpiar). */
  onChange: (value: string) => void;
  /** Lista completa de socios. */
  socios: Socio[];
  /** Placeholder cuando no hay socio seleccionado. */
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  /** Agrega un ítem inicial "todos" (value "todos") arriba de la lista. */
  allowEmpty?: boolean;
  /** Etiqueta del ítem "todos" (solo con allowEmpty). */
  emptyLabel?: string;
}

/** Lowercase sin acentos, para que "Nicolas" y "NICOLÁS" matcheen igual. */
function normalize(s: string): string {
  return s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

export function SocioCombobox({
  value,
  onChange,
  socios,
  placeholder = "Buscar socio...",
  disabled,
  className,
  allowEmpty = false,
  emptyLabel = "Todos los socios",
}: SocioComboboxProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const socioMap = useMemo(() => new Map(socios.map((s: Socio) => [s.id, s])), [socios]);

  const seleccionado = value && value !== "todos" ? socioMap.get(value) : undefined;
  const label = seleccionado
    ? seleccionado.dni
      ? `${seleccionado.nombre} — ${seleccionado.dni}`
      : seleccionado.nombre
    : allowEmpty && value === "todos"
      ? emptyLabel
      : placeholder;

  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) setQuery("");
      }}
    >
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className={cn("w-full justify-between font-normal", className)}
        >
          <span className="flex-1 truncate text-left">{label}</span>
          {seleccionado ? (
            <span
              role="button"
              tabIndex={-1}
              aria-label="Quitar socio"
              className="z-10 ml-2 shrink-0 cursor-pointer rounded-full p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
              onClick={(e) => {
                e.stopPropagation();
                e.preventDefault();
                onChange(allowEmpty ? "todos" : "");
              }}
            >
              <X className="size-3.5" />
            </span>
          ) : (
            <ChevronsUpDown className="ml-2 size-4 shrink-0 opacity-50" />
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[320px] p-0" align="start">
        <Command
          filter={(itemValue, search) => {
            const q = normalize(search.trim());
            if (!q) return 1;
            const v = normalize(itemValue);
            return q.split(/\s+/).every((term) => v.includes(term)) ? 1 : 0;
          }}
        >
          <CommandInput
            placeholder="Buscar por nombre o DNI..."
            value={query}
            onValueChange={setQuery}
          />
          <CommandList>
            <CommandEmpty>No se encontró ningún socio.</CommandEmpty>
            <CommandGroup>
              {allowEmpty && (
                <CommandItem
                  value="todos"
                  onSelect={() => {
                    onChange("todos");
                    setOpen(false);
                  }}
                >
                  <Check className={cn("size-4", value === "todos" ? "opacity-100" : "opacity-0")} />
                  <span className="flex-1 truncate">{emptyLabel}</span>
                </CommandItem>
              )}
              {socios.map((s: Socio) => (
                <CommandItem
                  key={s.id}
                  value={`${s.nombre} ${s.dni ?? ""}`}
                  onSelect={() => {
                    onChange(s.id);
                    setOpen(false);
                  }}
                >
                  <Check className={cn("size-4", value === s.id ? "opacity-100" : "opacity-0")} />
                  <span className="flex-1 truncate">{s.nombre}</span>
                  {s.dni && <span className="text-xs text-muted-foreground">{s.dni}</span>}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}