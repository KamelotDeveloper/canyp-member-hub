import { createFileRoute, Link, useNavigate, useSearch } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { EstadoBadge } from "@/components/canyp/EstadoBadge";
import { PageHeader } from "@/components/canyp/AppShell";
import { UnidadesPanel } from "@/components/canyp/UnidadesPanel";
import { estadoVisual, formatFecha } from "@/lib/canyp/utils";
import {
  useMembresias,
  useSocios,
  useUpdateMembresia,
  useParcelas,
  useUpdateParcela,
  useCreateParcela,
} from "@/lib/canyp/queries";
import type {
  Area,
  CategoriaParcela,
  Membresia,
  Parcela,
  Socio,
  UnidadFiltro,
} from "@/lib/canyp/types";

const AREAS: Area[] = ["Balseros", "Cabañeros", "Guardería", "Windsurf"];

export const Route = createFileRoute("/membresias")({
  validateSearch: (s: Record<string, unknown>): { area?: Area; filtro?: string } => ({
    ...(typeof s["area"] === "string" ? { area: s["area"] as Area } : {}),
    ...(typeof s["filtro"] === "string" ? { filtro: s["filtro"] as string } : {}),
  }),
  head: () => ({
    meta: [
      { title: "Membresías — CANYP Gestión" },
      {
        name: "description",
        content: "Membresías por área y predio, con cambio de estado y vencimientos editables.",
      },
      { property: "og:title", content: "Membresías — CANYP Gestión" },
      {
        property: "og:description",
        content: "Balseros, cabañeros, guardería y windsurf en una sola grilla operativa.",
      },
    ],
  }),
  component: MembresiasPage,
});

function MembresiasPage() {
  const search = useSearch({ from: "/membresias" });
  const navigate = useNavigate();
  const { data: membresias = [], isLoading } = useMembresias();
  const { data: socios = [] } = useSocios();
  const { data: parcelas = [] } = useParcelas();
  const updateMembresia = useUpdateMembresia();
  const updateParcela = useUpdateParcela();
  const createParcela = useCreateParcela();
  const [editando, setEditando] = useState<{ id: string; fecha: string } | null>(null);

  const socioMap = new Map(socios.map((s: Socio) => [s.id, s]));

  const areaActiva = search.area ?? "Balseros";
  const filtro = search.filtro ?? "todas";

  const lista = membresias
    .filter((m: Membresia) => m.area === areaActiva)
    .filter((m: Membresia) => {
      const e = estadoVisual(m);
      if (filtro === "vencidas") return e === "vencida";
      if (filtro === "por_vencer") return e === "por_vencer";
      if (filtro === "alertas") return e === "vencida" || e === "por_vencer";
      return true;
    });

  if (isLoading) {
    return (
      <>
        <PageHeader title="Gestión de membresías" subtitle="Cargando..." />
        <Card className="p-10 text-center text-sm text-muted-foreground">
          Cargando membresías...
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Gestión de membresías"
        subtitle="Elegí el área para trabajar sobre sus membresías."
        actions={
          <div className="flex gap-1 rounded-md border border-border bg-card p-1">
            {[
              { k: "todas", l: "Todas" },
              { k: "por_vencer", l: "Por vencer" },
              { k: "vencidas", l: "Vencidas" },
              { k: "alertas", l: "Alertas" },
            ].map((f) => (
              <button
                key={f.k}
                onClick={() =>
                  navigate({ to: "/membresias", search: { area: areaActiva, filtro: f.k } })
                }
                className={cn(
                  "rounded px-3 py-1.5 text-xs font-medium transition-colors",
                  filtro === f.k
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-secondary",
                )}
              >
                {f.l}
              </button>
            ))}
          </div>
        }
      />

      <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {AREAS.map((a) => {
          const total = membresias.filter((m: Membresia) => m.area === a).length;
          const alertas = membresias.filter(
            (m: Membresia) => m.area === a && ["vencida", "por_vencer"].includes(estadoVisual(m)),
          ).length;
          return (
            <button
              key={a}
              onClick={() => navigate({ to: "/membresias", search: { area: a, filtro } })}
              className={cn(
                "rounded-lg border p-4 text-left transition-colors",
                a === areaActiva
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card hover:border-primary/40",
              )}
            >
              <p className="text-sm font-semibold">{a}</p>
              <p
                className={cn(
                  "mt-1 text-xs",
                  a === areaActiva ? "text-primary-foreground/80" : "text-muted-foreground",
                )}
              >
                {total} membresías · {alertas} a revisar
              </p>
            </button>
          );
        })}
      </div>

      {areaActiva === "Cabañeros" || areaActiva === "Balseros" ? (
        <UnidadesPanel area={areaActiva} filtro={filtro as UnidadFiltro} />
      ) : (
        <Card className="overflow-hidden p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Socio</TableHead>
                <TableHead>Predio</TableHead>
                {areaActiva === "Guardería" && <TableHead>Categoría</TableHead>}
                <TableHead>Detalle</TableHead>
                <TableHead>Vencimiento</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead className="text-right">Acciones</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {lista.map((m) => (
                <TableRow key={m.id}>
                  <TableCell className="font-medium">
                    <Link
                      to="/socios/$socioId"
                      params={{ socioId: m.socioId }}
                      className="hover:underline"
                    >
                      {socioMap.get(m.socioId)?.nombre}
                    </Link>
                  </TableCell>
                  <TableCell className="text-xs">{m.predio}</TableCell>
                  {areaActiva === "Guardería" && (
                    <TableCell>
                      <GuarderiaCategoriaCell
                        m={m}
                        nombreSocio={socioMap.get(m.socioId)?.nombre}
                        parcelas={parcelas}
                        updateParcela={updateParcela}
                        createParcela={createParcela}
                        updateMembresia={updateMembresia}
                      />
                    </TableCell>
                  )}
                  <TableCell className="text-xs text-muted-foreground">{m.detalle}</TableCell>
                  <TableCell className="text-xs tabular-nums">
                    {formatFecha(m.vencimiento)}
                  </TableCell>
                  <TableCell>
                    <EstadoBadge estado={estadoVisual(m)} />
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Select
                        value={m.estado}
                        onValueChange={(v) => {
                          updateMembresia.mutate(
                            { id: m.id, data: { estado: v as Membresia["estado"] } },
                            { onSuccess: () => toast.success("Estado actualizado") },
                          );
                        }}
                      >
                        <SelectTrigger className="w-[140px]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="activa">Activar</SelectItem>
                          <SelectItem value="suspendida">Suspender</SelectItem>
                          <SelectItem value="vencida">Marcar vencida</SelectItem>
                          <SelectItem value="baja">Dar de baja</SelectItem>
                        </SelectContent>
                      </Select>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setEditando({ id: m.id, fecha: m.vencimiento })}
                      >
                        Vencimiento
                      </Button>
                      <Button
                        size="sm"
                        onClick={() =>
                          navigate({ to: "/pagos", search: { nuevo: "1", socioId: m.socioId } })
                        }
                      >
                        Cobrar
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {lista.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={areaActiva === "Guardería" ? 7 : 6}
                    className="py-10 text-center text-sm text-muted-foreground"
                  >
                    No hay membresías con este filtro.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </Card>
      )}

      <Dialog open={!!editando} onOpenChange={(o) => !o && setEditando(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Editar vencimiento</DialogTitle>
          </DialogHeader>
          <div>
            <Label>Nueva fecha</Label>
            <Input
              type="date"
              className="mt-1.5"
              value={editando?.fecha ?? ""}
              onChange={(e) =>
                setEditando((prev) => (prev ? { ...prev, fecha: e.target.value } : prev))
              }
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditando(null)}>
              Cancelar
            </Button>
            <Button
              onClick={() => {
                if (editando)
                  updateMembresia.mutate(
                    { id: editando.id, data: { vencimiento: editando.fecha } },
                    {
                      onSuccess: () => {
                        setEditando(null);
                        toast.success("Vencimiento actualizado");
                      },
                    },
                  );
              }}
            >
              Guardar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/**
 * Selector de categoría (Chica/Grande) por socio de Guardería — RQ 11.
 *
 * La categoría se persiste en la Parcela asociada (tipo "guardería"). Si la
 * membresía aún no tiene Parcela, se crea una guardería con el nombre del socio
 * y se la vincula a la membresía (el backend valida que la parcela exista antes
 * de setear parcelaId). Solo se renderiza para el área Guardería, por lo que la
 * vista de Windsurf queda intacta.
 */
function GuarderiaCategoriaCell({
  m,
  nombreSocio,
  parcelas,
  updateParcela,
  createParcela,
  updateMembresia,
}: {
  m: Membresia;
  nombreSocio: string | undefined;
  parcelas: Parcela[];
  updateParcela: ReturnType<typeof useUpdateParcela>;
  createParcela: ReturnType<typeof useCreateParcela>;
  updateMembresia: ReturnType<typeof useUpdateMembresia>;
}) {
  const guarderias = parcelas.filter((p: Parcela) => p.tipo === "guardería");
  const parcela =
    guarderias.find((p) => p.id === m.parcelaId) ??
    guarderias.find((p) => p.nombre === `Guardería ${nombreSocio ?? ""}`);
  const value = (parcela?.categoria ?? "") as CategoriaParcela | "";

  function onSelect(cat: CategoriaParcela) {
    if (parcela) {
      updateParcela.mutate(
        { id: parcela.id, data: { categoria: cat } },
        {
          onSuccess: () => toast.success("Categoría de Guardería actualizada"),
          onError: () => toast.error("Error al actualizar la categoría"),
        },
      );
      return;
    }
    createParcela.mutate(
      {
        id: `g${Date.now()}`,
        nombre: `Guardería ${nombreSocio ?? m.socioId}`,
        tipo: "guardería",
        categoria: cat,
        predio: m.predio,
      },
      {
        onSuccess: (p) => {
          updateMembresia.mutate({ id: m.id, data: { parcelaId: p.id } });
          toast.success("Categoría de Guardería guardada");
        },
        onError: () => toast.error("Error al crear la categoría"),
      },
    );
  }

  return (
    <Select value={value} onValueChange={(v) => onSelect(v as CategoriaParcela)}>
      <SelectTrigger className="w-[120px]">
        <SelectValue placeholder="Sin definir" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="Chica">Chica</SelectItem>
        <SelectItem value="Grande">Grande</SelectItem>
      </SelectContent>
    </Select>
  );
}
