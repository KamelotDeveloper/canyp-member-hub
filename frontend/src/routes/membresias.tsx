import { createFileRoute, Link, useNavigate, useSearch } from "@tanstack/react-router";
import { Pencil, Plus, Trash2, Upload } from "lucide-react";
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
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
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
import { ExportButton } from "@/components/export";
import { UnidadesPanel } from "@/components/canyp/UnidadesPanel";
import { SocioCombobox } from "@/components/canyp/SocioCombobox";
import { ImportModal, type ImportColumnSpec } from "@/components/import";
import {
  EditarVencimientoMembresia,
  EditarVencimientoLote,
} from "@/components/canyp/VencimientoEditor";
import { formatFecha } from "@/lib/canyp/utils";
import {
  useMembresias,
  useSocios,
  useUpdateMembresia,
  useDeleteMembresia,
  useParcelas,
  useUpdateParcela,
  useCreateParcela,
  useCreateMembresia,
  useAranceles,
} from "@/lib/canyp/queries";
import type {
  Arancel,
  Area,
  CategoriaParcela,
  Membresia,
  Parcela,
  Socio,
  UnidadFiltro,
} from "@/lib/canyp/types";

const AREAS: Area[] = ["Balseros", "Cabañeros", "Guardería", "Windsurf"];

/** Editable columns shown in the membresías import preview. */
const importColumns: ImportColumnSpec[] = [
  { label: "DNI", field: "dni" },
  { label: "Área", field: "area" },
  { label: "Predio", field: "predio" },
  { label: "Vencimiento", field: "vencimiento" },
  { label: "Estado", field: "estado" },
  { label: "Arancel", field: "arancel" },
  { label: "Detalle", field: "detalle" },
];

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
  const { data: membresias = [], isLoading, refetch: refetchMembresias } = useMembresias();
  const { data: socios = [] } = useSocios();
  const { data: parcelas = [] } = useParcelas();
  const updateMembresia = useUpdateMembresia();
  const deleteMembresia = useDeleteMembresia();
  const updateParcela = useUpdateParcela();
  const createParcela = useCreateParcela();
  const createMembresia = useCreateMembresia();
  const { data: aranceles = [] } = useAranceles();
  const [editando, setEditando] = useState<Membresia | null>(null);
  const [editandoFull, setEditandoFull] = useState<Membresia | null>(null);
  const [eliminando, setEliminando] = useState<Membresia | null>(null);
  const [nuevaOpen, setNuevaOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [loteOpen, setLoteOpen] = useState(false);
  const [nueva, setNueva] = useState<{
    socioId: string;
    vencimiento: string;
    detalle: string;
    arancelId: string;
  }>({
    socioId: "",
    vencimiento: new Date(Date.now() + 365 * 86400000).toISOString().slice(0, 10),
    detalle: "",
    arancelId: "",
  });

  const socioMap = new Map(socios.map((s: Socio) => [s.id, s]));

  /** Estado SERVIDO del socio dueño de una membresía (EST-01): no se deriva. */
  const estadoDe = (m: Membresia) => socioMap.get(m.socioId)?.estado;
  const estadoBadgeDe = (m: Membresia) => {
    const e = estadoDe(m);
    return e ? <EstadoBadge estado={e} /> : null;
  };

  const areaActiva = search.area ?? "Balseros";
  const filtro = search.filtro ?? "todas";

  const arancelesArea = aranceles.filter(
    (a: Arancel) => a.area === areaActiva && a.predio === "Almafuerte",
  );

  const lista = membresias
    .filter((m: Membresia) => m.area === areaActiva)
    .filter((m: Membresia) => {
      const e = estadoDe(m);
      if (filtro === "vencidas") return e === "Inactivo — revisar";
      if (filtro === "alertas") return e === "Inactivo — revisar" || e === "Socio activo — revisar";
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
          <>
            <ExportButton resource="membresias" label="membresías" />
            <Button size="sm" variant="outline" onClick={() => setLoteOpen(true)}>
              Vencimiento por lote
            </Button>
            <div className="flex gap-1 rounded-md border border-border bg-card p-1">
              {[
                { k: "todas", l: "Todas" },
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
          </>
        }
      />

      <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {AREAS.map((a) => {
          const total = membresias.filter((m: Membresia) => m.area === a).length;
          const alertas = membresias.filter((m: Membresia) => {
            if (m.area !== a) return false;
            const e = estadoDe(m);
            return e === "Inactivo — revisar" || e === "Socio activo — revisar";
          }).length;
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
        <>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-muted-foreground">
              {lista.length} membresías en {areaActiva}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => setImportOpen(true)}>
                <Upload className="mr-1.5 size-4" /> Importar
              </Button>
              <Button size="sm" onClick={() => setNuevaOpen(true)}>
                <Plus className="mr-1.5 size-4" /> Nueva membresía
              </Button>
            </div>
          </div>
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
                    <TableCell>{estadoBadgeDe(m)}</TableCell>
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
                        <Button size="sm" variant="outline" onClick={() => setEditando(m)}>
                          Vencimiento
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => setEditandoFull(m)}>
                          <Pencil className="mr-1.5 size-3.5" /> Editar
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="text-destructive hover:text-destructive"
                          onClick={() => setEliminando(m)}
                        >
                          <Trash2 className="mr-1.5 size-3.5" /> Eliminar
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
        </>
      )}

      <Dialog open={nuevaOpen} onOpenChange={setNuevaOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Nueva membresía — {areaActiva}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4">
            <div>
              <Label>Socio</Label>
              <SocioCombobox
                className="mt-1.5"
                placeholder="Elegí un socio..."
                value={nueva.socioId}
                onChange={(v) => setNueva((p) => ({ ...p, socioId: v }))}
                socios={socios}
              />
            </div>
            <div>
              <Label>Vencimiento</Label>
              <Input
                type="date"
                className="mt-1.5"
                value={nueva.vencimiento}
                onChange={(e) => setNueva((p) => ({ ...p, vencimiento: e.target.value }))}
              />
            </div>
            <div>
              <Label>Detalle (box, locker, tabla...)</Label>
              <Input
                value={nueva.detalle}
                onChange={(e) => setNueva((p) => ({ ...p, detalle: e.target.value }))}
                className="mt-1.5"
              />
            </div>
            <div>
              <Label>Arancel</Label>
              <Select
                value={nueva.arancelId}
                onValueChange={(v) =>
                  setNueva((p) => ({ ...p, arancelId: v === "__ninguno__" ? "" : v }))
                }
              >
                <SelectTrigger className="mt-1.5">
                  <SelectValue placeholder="Seleccionar arancel" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__ninguno__">Sin arancel</SelectItem>
                  {arancelesArea.map((a) => (
                    <SelectItem key={a.id} value={a.id}>
                      {a.nombre} — ${a.monto.toLocaleString("es-AR")}
                      {a.categoria ? ` (categoría: ${a.categoria})` : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setNuevaOpen(false)}>
              Cancelar
            </Button>
            <Button
              disabled={!nueva.socioId}
              onClick={() => {
                const socio = socios.find((s: Socio) => s.id === nueva.socioId);
                if (!socio) return;
                createMembresia.mutate(
                  {
                    socioId: nueva.socioId,
                    area: areaActiva,
                    predio: "Almafuerte",
                    estado: "activa",
                    vencimiento: nueva.vencimiento,
                    detalle: nueva.detalle.trim(),
                    ...(nueva.arancelId ? { arancelId: nueva.arancelId } : {}),
                  },
                  {
                    onSuccess: () => {
                      setNuevaOpen(false);
                      setNueva({
                        socioId: "",
                        vencimiento: new Date(Date.now() + 365 * 86400000)
                          .toISOString()
                          .slice(0, 10),
                        detalle: "",
                        arancelId: "",
                      });
                      toast.success("Membresía creada");
                    },
                    onError: () => toast.error("No se pudo crear la membresía"),
                  },
                );
              }}
            >
              Crear membresía
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {editando && (
        <EditarVencimientoMembresia membresia={editando} onClose={() => setEditando(null)} />
      )}

      {loteOpen && <EditarVencimientoLote parcelas={parcelas} onClose={() => setLoteOpen(false)} />}

      {editandoFull && (
        <EditarMembresiaDialog
          membresia={editandoFull}
          arancelesArea={arancelesArea}
          onClose={() => setEditandoFull(null)}
        />
      )}

      <AlertDialog open={!!eliminando} onOpenChange={(o) => !o && setEliminando(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar membresía</AlertDialogTitle>
            <AlertDialogDescription>
              Se va a eliminar la membresía de{" "}
              <span className="font-medium text-foreground">
                {eliminando ? (socioMap.get(eliminando.socioId)?.nombre ?? "este socio") : ""}
              </span>{" "}
              ({eliminando?.area} · {eliminando?.predio}). Esta acción no se puede deshacer.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (!eliminando) return;
                const id = eliminando.id;
                setEliminando(null);
                deleteMembresia.mutate(id, {
                  onSuccess: () => toast.success("Membresía eliminada"),
                  onError: () => toast.error("No se pudo eliminar la membresía"),
                });
              }}
            >
              Eliminar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <ImportModal
        resource="membresias"
        resourceLabel="membresías"
        columnSpec={importColumns}
        open={importOpen}
        onOpenChange={setImportOpen}
        onImportComplete={() => refetchMembresias()}
      />
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
        predio: m.predio ?? "Almafuerte",
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

/**
 * Dialog de edición completa de una membresía (Guardería/Windsurf): vencimiento,
 * detalle, arancel asignado y estado. Recibe la membresía actual y arranca sus
 * controles con esos valores; al guardar solo envía los campos modificados.
 */
function EditarMembresiaDialog({
  membresia,
  arancelesArea,
  onClose,
}: {
  membresia: Membresia;
  arancelesArea: Arancel[];
  onClose: () => void;
}) {
  const updateMembresia = useUpdateMembresia();
  const [vencimiento, setVencimiento] = useState(membresia.vencimiento);
  const [detalle, setDetalle] = useState(membresia.detalle ?? "");
  const [arancelId, setArancelId] = useState(membresia.arancelId ?? "");
  const [estado, setEstado] = useState(membresia.estado);

  function guardar() {
    const data: Partial<Membresia> = {};
    if (vencimiento !== membresia.vencimiento) data.vencimiento = vencimiento;
    if (detalle !== (membresia.detalle ?? "")) data.detalle = detalle;
    if (arancelId !== (membresia.arancelId ?? "")) data.arancelId = arancelId;
    if (estado !== membresia.estado) data.estado = estado;
    if (Object.keys(data).length === 0) {
      onClose();
      return;
    }
    updateMembresia.mutate(
      { id: membresia.id, data },
      {
        onSuccess: () => {
          onClose();
          toast.success("Membresía actualizada");
        },
        onError: () => toast.error("No se pudo actualizar la membresía"),
      },
    );
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Editar membresía</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4">
          <div>
            <Label>Vencimiento</Label>
            <Input
              type="date"
              className="mt-1.5"
              value={vencimiento}
              onChange={(e) => setVencimiento(e.target.value)}
            />
          </div>
          <div>
            <Label>Detalle (box, locker, tabla...)</Label>
            <Input
              value={detalle}
              onChange={(e) => setDetalle(e.target.value)}
              className="mt-1.5"
            />
          </div>
          <div>
            <Label>Arancel</Label>
            <Select
              value={arancelId}
              onValueChange={(v) => setArancelId(v === "__ninguno__" ? "" : v)}
            >
              <SelectTrigger className="mt-1.5">
                <SelectValue placeholder="Seleccionar arancel" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__ninguno__">Sin arancel</SelectItem>
                {arancelesArea.map((a) => (
                  <SelectItem key={a.id} value={a.id}>
                    {a.nombre} — ${a.monto.toLocaleString("es-AR")}
                    {a.categoria ? ` (categoría: ${a.categoria})` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Estado</Label>
            <Select value={estado} onValueChange={(v) => setEstado(v as Membresia["estado"])}>
              <SelectTrigger className="mt-1.5">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="activa">Activa</SelectItem>
                <SelectItem value="suspendida">Suspendida</SelectItem>
                <SelectItem value="vencida">Vencida</SelectItem>
                <SelectItem value="baja">Baja</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancelar
          </Button>
          <Button onClick={guardar} disabled={updateMembresia.isPending}>
            Guardar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
