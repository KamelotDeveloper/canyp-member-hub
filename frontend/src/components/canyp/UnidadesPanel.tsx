import { useMemo, useRef, useState, type ChangeEvent } from "react";
import { toast } from "sonner";
import { Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { EstadoBadge } from "@/components/canyp/EstadoBadge";
import {
  CobrarUnidadDialog,
  GestionarDialog,
  NuevaUnidadDialog,
} from "@/components/canyp/unidad-dialogs";
import { formatFecha } from "@/lib/canyp/utils";
import { estadoCriticoDe, filtrarUnidades } from "@/lib/canyp/unidad-helpers";
import { useMembresias, useParcelas, useSocios, useImportParcelas } from "@/lib/canyp/queries";
import type {
  Area,
  CategoriaParcela,
  ImportPayload,
  Membresia,
  Predio,
  Socio,
  UnidadFiltro,
  UnidadGroup,
} from "@/lib/canyp/types";

/** Agrupa membresías de un área por parcelaId. null → grupo "Sin asignar". */
export function groupByParcelaId(params: {
  membresias: Membresia[];
  parcelas: {
    id: string;
    nombre: string;
    tipo: string;
    categoria?: CategoriaParcela;
    predio: Predio;
  }[];
  area: Area;
}): UnidadGroup[] {
  const parcelaById = new Map(params.parcelas.map((p) => [p.id, p]));

  const map = new Map<string, Membresia[]>();
  for (const m of params.membresias) {
    if (m.area !== params.area) continue;
    // Se agrupa por parcelaId real. Sin parcelaId, o con un parcelaId que no
    // resuelve a una Parcela conocida → grupo "Sin asignar".
    let key = "";
    if (m.parcelaId && parcelaById.has(m.parcelaId)) {
      key = m.parcelaId;
    }
    map.set(key, [...(map.get(key) ?? []), m]);
  }

  const groups: UnidadGroup[] = [];
  for (const [key, members] of map.entries()) {
    if (!key) {
      groups.push({
        parcelaId: null,
        nombre: "Sin asignar",
        predio: members[0]?.predio ?? "Almafuerte",
        categoria: null,
        members,
      });
      continue;
    }
    const parcela = parcelaById.get(key)!;
    groups.push({
      parcelaId: key,
      nombre: parcela.nombre,
      predio: parcela.predio,
      categoria: parcela.categoria ?? null,
      members,
    });
  }
  return groups;
}

/** Iniciales para el avatar de un socio. */
function iniciales(nombre: string): string {
  const parts = nombre.trim().split(/\s+/).filter(Boolean);
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "";
  return (first + last).toUpperCase();
}

export function UnidadesPanel({ area, filtro }: { area: Area; filtro: UnidadFiltro }) {
  const { data: membresias = [] } = useMembresias();
  const { data: parcelas = [] } = useParcelas();
  const { data: socios = [] } = useSocios();
  const importParcelas = useImportParcelas();
  const fileRef = useRef<HTMLInputElement>(null);

  const [gestionando, setGestionando] = useState<UnidadGroup | null>(null);
  const [cobrando, setCobrando] = useState<UnidadGroup | null>(null);
  const [nuevaOpen, setNuevaOpen] = useState(false);

  const socioMap = useMemo(() => new Map(socios.map((s: Socio) => [s.id, s])), [socios]);

  function onImportFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result)) as ImportPayload;
        if (!parsed || !Array.isArray(parsed.unidades)) {
          throw new Error("formato inválido");
        }
        importParcelas.mutate(parsed, {
          onSuccess: (res) =>
            toast.success(
              `Importadas ${res.parcelas.length} unidades y ${res.membresias.length} membresías`,
            ),
          onError: () => toast.error("Error al importar unidades"),
        });
      } catch {
        toast.error("Archivo JSON inválido: debe contener un objeto con una lista 'unidades'");
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  }

  const grupos = useMemo(() => {
    const all = groupByParcelaId({ membresias, parcelas, area });
    return filtrarUnidades(all, filtro).sort((a, b) => {
      if (a.parcelaId === null) return 1;
      if (b.parcelaId === null) return -1;
      return a.nombre.localeCompare(b.nombre, "es");
    });
  }, [membresias, parcelas, area, filtro]);

  const totalSocios = grupos.reduce((s, g) => s + g.members.length, 0);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {grupos.length} unidades · {totalSocios} socios asociados
        </p>
        <div className="flex flex-wrap gap-2">
          <input
            ref={fileRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={onImportFile}
          />
          <Button size="sm" variant="outline" onClick={() => fileRef.current?.click()}>
            <Upload className="mr-1.5 size-4" /> Importar
          </Button>
          <Button size="sm" onClick={() => setNuevaOpen(true)}>
            + Nueva unidad
          </Button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {grupos.map((g) => (
          <UnidadCard
            key={g.parcelaId ?? "__sin_asignar__"}
            grupo={g}
            area={area}
            socioMap={socioMap}
            onGestionar={() => setGestionando(g)}
            onCobrar={() => setCobrando(g)}
          />
        ))}
        {grupos.length === 0 && (
          <Card className="p-10 text-center text-sm text-muted-foreground md:col-span-2 xl:col-span-3">
            No hay unidades con este filtro.
          </Card>
        )}
      </div>

      {gestionando && (
        <GestionarDialog
          key={gestionando.parcelaId ?? "__sin_asignar__"}
          grupo={gestionando}
          area={area}
          open={!!gestionando}
          onOpenChange={(o) => !o && setGestionando(null)}
        />
      )}
      <NuevaUnidadDialog area={area} open={nuevaOpen} onOpenChange={setNuevaOpen} />
      {cobrando && (
        <CobrarUnidadDialog
          grupo={cobrando}
          open={!!cobrando}
          onOpenChange={(o) => !o && setCobrando(null)}
        />
      )}
    </div>
  );
}

function UnidadCard({
  grupo,
  area,
  socioMap,
  onGestionar,
  onCobrar,
}: {
  grupo: UnidadGroup;
  area: Area;
  socioMap: Map<string, Socio>;
  onGestionar: () => void;
  onCobrar: () => void;
}) {
  const estado = estadoCriticoDe(grupo);
  const vencimientoComun = grupo.members.reduce<string | null>(
    (min, m) => (min === null || m.vencimiento < min ? m.vencimiento : min),
    null,
  );
  const esCabaña = area === "Cabañeros";
  const avatares = grupo.members.slice(0, 3);

  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-base font-semibold">{grupo.nombre}</p>
          <p className="text-xs text-muted-foreground">
            {grupo.predio}
            {vencimientoComun && ` · vence ${formatFecha(vencimientoComun)}`}
          </p>
          {esCabaña && grupo.categoria && (
            <span className="mt-1 inline-block rounded border border-border bg-secondary/40 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
              {grupo.categoria}
            </span>
          )}
        </div>
        <EstadoBadge estado={estado} />
      </div>

      <div className="flex items-center justify-between rounded-md border border-border bg-secondary/40 p-2.5">
        <div className="flex -space-x-1.5">
          {avatares.map((m) => {
            const s = socioMap.get(m.socioId);
            return (
              <Avatar
                key={m.id}
                className="size-7 border-2 border-background"
                title={s?.nombre ?? m.socioId}
              >
                <AvatarFallback className="text-[10px] font-semibold">
                  {s ? iniciales(s.nombre) : "?"}
                </AvatarFallback>
              </Avatar>
            );
          })}
          {grupo.members.length > 3 && (
            <span className="flex size-7 items-center justify-center rounded-full border-2 border-background bg-muted text-[10px] font-semibold text-muted-foreground">
              +{grupo.members.length - 3}
            </span>
          )}
        </div>
        <p className="text-xs font-semibold text-muted-foreground">
          {grupo.members.length} socio{grupo.members.length === 1 ? "" : "s"}
        </p>
      </div>

      <div className="mt-auto flex gap-2">
        <Button size="sm" variant="outline" className="flex-1" onClick={onGestionar}>
          Gestionar
        </Button>
        <Button size="sm" className="flex-1" onClick={onCobrar}>
          Cobrar
        </Button>
      </div>
    </Card>
  );
}
