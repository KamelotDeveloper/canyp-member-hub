/**
 * Management (Gestionar) + New-unit (Nueva unidad) dialogs for the
 * UnidadesPanel — RQ 5 / RQ 6 / RQ 7 / RQ 10 / RQ 12 / RQ 14.
 *
 * - `GestionarDialog`: rename unidad (PUT parcela), edit categoría (cabañas
 *   only), full socio list with roles, remove integrante (DELETE membresía,
 *   never the socio), add existing socio, add new socio inline, batch estado /
 *   vencimiento for ALL members, and a "Cobrar" that builds a single pago for
 *   the whole unit (one PagoItem per member) and redirects to /pagos with the
 *   Titular preselected.
 * - `NuevaUnidadDialog`: nombre, predio, categoría (cabañas only), fecha de
 *   vencimiento and dynamic socio rows (first = Titular). On confirm it builds
 *   an ImportPayload so the backend creates the real Parcela + socios +
 *   membresías transactionally.
 */

import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Check, ChevronsUpDown, Pencil, Trash2 } from "lucide-react";
import { useNavigate } from "@tanstack/react-router";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { buildUnitPago } from "@/lib/canyp/api";
import {
  arancelesDisponibles,
  buildNuevaUnidadPayload,
  conceptoDeMembresia,
  itemsPorArancel,
  lineaAPagoItem,
  membresiaDeLugar,
  predioDeTipo,
  totalEstimado,
  type LugarCobrable,
  type NuevaUnidadSocio,
} from "@/lib/canyp/unidad-helpers";
import {
  useSocios,
  useAranceles,
  useUpdateParcela,
  useDeleteParcela,
  useDeleteMembresia,
  useUpdateMembresia,
  useCreateMembresia,
  useCreateSocio,
  useSetBatchEstado,
  useSetBatchVencimiento,
  useCreatePago,
  useImportParcelas,
  useMembresias,
} from "@/lib/canyp/queries";
import { formatARS, formatFecha } from "@/lib/canyp/utils";
import type {
  Arancel,
  Area,
  CategoriaParcela,
  ConceptoCobro,
  EstadoMembresia,
  Membresia,
  Parcela,
  Rol,
  Socio,
  UnidadGroup,
} from "@/lib/canyp/types";

const CATEGORIAS_CABANA: CategoriaParcela[] = ["Chica", "Mediana", "Especial", "Grande"];
const ESTADOS: EstadoMembresia[] = ["activa", "suspendida", "vencida", "baja"];

/** Vencimiento más cercano de una unidad (o "hoy" si no hay datos). */
function vencimientoPorDefecto(members: Membresia[]): string {
  const min = members.reduce<string | null>(
    (acc, m) => (acc === null || m.vencimiento < acc ? m.vencimiento : acc),
    null,
  );
  return min ?? new Date().toISOString().slice(0, 10);
}

function tipoPorArea(area: Area): "cabaña" | "balsa" {
  return area === "Cabañeros" ? "cabaña" : "balsa";
}

// ---------------------------------------------------------------------------
// GestionarDialog
// ---------------------------------------------------------------------------

export function GestionarDialog({
  grupo,
  area,
  open,
  onOpenChange,
}: {
  grupo: UnidadGroup;
  area: Area;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const { data: socios = [] } = useSocios();

  const updateParcela = useUpdateParcela();
  const deleteParcela = useDeleteParcela();
  const deleteMembresia = useDeleteMembresia();
  const updateMembresia = useUpdateMembresia();
  const createMembresia = useCreateMembresia();
  const createSocio = useCreateSocio();
  const setBatchEstado = useSetBatchEstado();
  const setBatchVencimiento = useSetBatchVencimiento();

  const socioMap = useMemo(() => new Map(socios.map((s: Socio) => [s.id, s])), [socios]);
  const esCabaña = area === "Cabañeros";
  const conParcela = grupo.parcelaId !== null;

  const [nombre, setNombre] = useState(grupo.nombre);
  const [categoria, setCategoria] = useState<CategoriaParcela | "">(grupo.categoria ?? "");
  const [estadoBatch, setEstadoBatch] = useState<EstadoMembresia | "">("");
  const [vencBatch, setVencBatch] = useState("");
  const [socioAAgregar, setSocioAAgregar] = useState("");
  const [nuevoNombre, setNuevoNombre] = useState("");
  const [nuevoDni, setNuevoDni] = useState("");
  const [nuevoTel, setNuevoTel] = useState("");
  const [nuevoMail, setNuevoMail] = useState("");
  const [cobrando, setCobrando] = useState(false);
  const [confirmEliminar, setConfirmEliminar] = useState(false);
  const [editando, setEditando] = useState<Membresia | null>(null);

  // Socios que aún no integran la unidad (para "Agregar existente").
  const agregables = socios.filter((s: Socio) => !grupo.members.some((m) => m.socioId === s.id));

  function guardarUnidad() {
    if (!grupo.parcelaId) return;
    const data: { nombre?: string; categoria?: CategoriaParcela | null } = {};
    if (nombre.trim() && nombre.trim() !== grupo.nombre) data.nombre = nombre.trim();
    if (categoria !== (grupo.categoria ?? "")) data.categoria = categoria ? categoria : null;
    if (Object.keys(data).length === 0) return;
    updateParcela.mutate(
      { id: grupo.parcelaId, data: data as Partial<Parcela> },
      {
        onSuccess: () => toast.success("Unidad actualizada"),
        onError: () => toast.error("Error al guardar la unidad"),
      },
    );
  }

  function agregarExistente() {
    if (!socioAAgregar || !grupo.parcelaId) return;
    const tieneTitular = grupo.members.some((m) => m.rol === "Titular");
    createMembresia.mutate(
      {
        socioId: socioAAgregar,
        area,
        predio: grupo.predio,
        estado: "activa",
        vencimiento: vencimientoPorDefecto(grupo.members),
        rol: tieneTitular ? "Integrante" : "Titular",
        parcelaId: grupo.parcelaId,
      },
      {
        onSuccess: () => {
          setSocioAAgregar("");
          toast.success(`${tieneTitular ? "Integrante" : "Titular"} agregado a la unidad`);
        },
        onError: () => toast.error("Error al agregar el integrante"),
      },
    );
  }

  function agregarNuevo() {
    if (!nuevoNombre.trim() || !nuevoDni.trim()) {
      toast.error("Completá nombre y DNI del nuevo socio");
      return;
    }
    const tieneTitular = grupo.members.some((m) => m.rol === "Titular");
    createSocio.mutate(
      {
        nombre: nuevoNombre.trim(),
        dni: nuevoDni.trim(),
        telefono: nuevoTel.trim(),
        email: nuevoMail.trim(),
        direccion: "",
        activo: true,
        numeroSocio: null,
        tieneFoto: false,
      },
      {
        onSuccess: (socio) => {
          if (grupo.parcelaId) {
            createMembresia.mutate(
              {
                socioId: socio.id,
                area,
                predio: grupo.predio,
                estado: "activa",
                vencimiento: vencimientoPorDefecto(grupo.members),
                rol: tieneTitular ? "Integrante" : "Titular",
                parcelaId: grupo.parcelaId,
              },
              {
                onSuccess: () =>
                  toast.success(
                    `${tieneTitular ? "Integrante" : "Titular"} creado y agregado a la unidad`,
                  ),
                onError: () => toast.error("Socio creado, pero no se pudo agregar a la unidad"),
              },
            );
          } else {
            toast.success("Socio creado");
          }
          setNuevoNombre("");
          setNuevoDni("");
          setNuevoTel("");
          setNuevoMail("");
        },
        onError: () => toast.error("Error al crear el socio"),
      },
    );
  }

  function aplicarEstado() {
    if (!grupo.parcelaId || !estadoBatch) return;
    setBatchEstado.mutate(
      { parcelaId: grupo.parcelaId, estado: estadoBatch },
      {
        onSuccess: () => {
          setEstadoBatch("");
          toast.success("Estado aplicado a todos los integrantes");
        },
        onError: () => toast.error("Error al cambiar el estado"),
      },
    );
  }

  function aplicarVencimiento() {
    if (!grupo.parcelaId || !vencBatch) return;
    setBatchVencimiento.mutate(
      // El lote de una unidad toca SOLO el área (CBM-06): la cuota social queda
      // intacta. Siempre se envía el concepto para no mezclar ambos.
      { parcelaId: grupo.parcelaId, vencimiento: vencBatch, concepto: "area" },
      {
        onSuccess: () => {
          setVencBatch("");
          toast.success("Vencimiento aplicado a todos los integrantes");
        },
        onError: () => toast.error("Error al cambiar el vencimiento"),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Gestionar unidad</DialogTitle>
          <DialogDescription>
            {grupo.nombre} · {grupo.predio}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6">
          {conParcela && (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <Label>Nombre de la unidad</Label>
                  <Input
                    className="mt-1.5"
                    value={nombre}
                    onChange={(e) => setNombre(e.target.value)}
                  />
                </div>
                {esCabaña && (
                  <div>
                    <Label>Categoría (cabañas)</Label>
                    <Select
                      value={categoria}
                      onValueChange={(v) => setCategoria(v as CategoriaParcela)}
                    >
                      <SelectTrigger className="mt-1.5">
                        <SelectValue placeholder="Sin categoría" />
                      </SelectTrigger>
                      <SelectContent>
                        {CATEGORIAS_CABANA.map((c) => (
                          <SelectItem key={c} value={c}>
                            {c}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </div>
              <div className="flex justify-end">
                <Button size="sm" onClick={guardarUnidad}>
                  Guardar unidad
                </Button>
              </div>
            </div>
          )}

          {/* Socios de la unidad */}
          <div>
            <Label className="text-sm font-semibold">Socios ({grupo.members.length})</Label>
            <ul className="mt-2 space-y-2">
              {grupo.members.map((m) => {
                const s = socioMap.get(m.socioId);
                return (
                  <li
                    key={m.id}
                    className="flex items-center justify-between gap-3 rounded-md border border-border p-2.5"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{s?.nombre ?? m.socioId}</p>
                      <p className="text-xs text-muted-foreground">
                        Vence {formatFecha(m.vencimiento)}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant={m.rol === "Titular" ? "default" : "secondary"}>
                        {m.rol ?? "—"}
                      </Badge>
                      <Select
                        value={m.rol ?? "Integrante"}
                        onValueChange={(v) =>
                          updateMembresia.mutate(
                            { id: m.id, data: { rol: v as Rol } },
                            {
                              onSuccess: () => toast.success(`Rol actualizado a ${v}`),
                              onError: () => toast.error("Error al cambiar el rol"),
                            },
                          )
                        }
                      >
                        <SelectTrigger className="h-7 w-28" aria-label="Cambiar rol">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="Titular">Titular</SelectItem>
                          <SelectItem value="Integrante">Integrante</SelectItem>
                        </SelectContent>
                      </Select>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setEditando(m)}
                        aria-label={`Editar a ${s?.nombre ?? m.socioId}`}
                      >
                        <Pencil className="size-3.5" />
                        <span className="sr-only">Editar</span>
                      </Button>
                    </div>
                  </li>
                );
              })}
              {grupo.members.length === 0 && (
                <li className="text-xs text-muted-foreground">Sin socios cargados.</li>
              )}
            </ul>
          </div>

          {/* Agregar socio existente */}
          {conParcela && (
            <div className="rounded-md border border-border p-3">
              <Label>Agregar socio existente</Label>
              <div className="mt-1.5 flex gap-2">
                <Select value={socioAAgregar} onValueChange={setSocioAAgregar}>
                  <SelectTrigger className="flex-1">
                    <SelectValue placeholder="Elegir socio" />
                  </SelectTrigger>
                  <SelectContent>
                    {agregables.map((s: Socio) => (
                      <SelectItem key={s.id} value={s.id}>
                        {s.nombre} — {s.dni}
                      </SelectItem>
                    ))}
                    {agregables.length === 0 && (
                      <SelectItem value="__ninguno__" disabled>
                        No quedan socios por agregar
                      </SelectItem>
                    )}
                  </SelectContent>
                </Select>
                <Button onClick={agregarExistente} disabled={!socioAAgregar}>
                  Agregar
                </Button>
              </div>
            </div>
          )}

          {/* Agregar nuevo socio */}
          {conParcela && (
            <div className="rounded-md border border-border p-3">
              <Label>Agregar nuevo socio</Label>
              <div className="mt-1.5 grid gap-2 sm:grid-cols-2">
                <Input
                  placeholder="Nombre y apellido"
                  value={nuevoNombre}
                  onChange={(e) => setNuevoNombre(e.target.value)}
                />
                <Input
                  placeholder="DNI"
                  value={nuevoDni}
                  onChange={(e) => setNuevoDni(e.target.value)}
                />
                <Input
                  placeholder="Teléfono (opcional)"
                  value={nuevoTel}
                  onChange={(e) => setNuevoTel(e.target.value)}
                />
                <Input
                  placeholder="Email (opcional)"
                  value={nuevoMail}
                  onChange={(e) => setNuevoMail(e.target.value)}
                />
              </div>
              <div className="mt-2 flex justify-end">
                <Button size="sm" onClick={agregarNuevo}>
                  Crear y agregar
                </Button>
              </div>
            </div>
          )}

          {/* Batch estado / vencimiento */}
          {conParcela && (
            <div className="grid gap-3 rounded-md border border-border p-3 sm:grid-cols-2">
              <div>
                <Label>Estado (todos los integrantes)</Label>
                <div className="mt-1.5 flex gap-2">
                  <Select
                    value={estadoBatch}
                    onValueChange={(v) => setEstadoBatch(v as EstadoMembresia)}
                  >
                    <SelectTrigger className="flex-1">
                      <SelectValue placeholder="Estado..." />
                    </SelectTrigger>
                    <SelectContent>
                      {ESTADOS.map((e) => (
                        <SelectItem key={e} value={e}>
                          {e}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button onClick={aplicarEstado} disabled={!estadoBatch}>
                    Aplicar
                  </Button>
                </div>
              </div>
              <div>
                <Label>Vencimiento (todos los integrantes)</Label>
                <div className="mt-1.5 flex gap-2">
                  <Input
                    type="date"
                    className="flex-1"
                    value={vencBatch}
                    onChange={(e) => setVencBatch(e.target.value)}
                  />
                  <Button onClick={aplicarVencimiento} disabled={!vencBatch}>
                    Aplicar
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>

        <DialogFooter className="gap-2 sm:justify-between">
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              className="text-destructive hover:bg-destructive hover:text-destructive-foreground"
              onClick={() => setConfirmEliminar(true)}
            >
              <Trash2 className="mr-1.5 size-4" /> Eliminar unidad
            </Button>
            <Button
              variant="outline"
              onClick={() => setCobrando(true)}
              disabled={grupo.members.length === 0}
            >
              Cobrar unidad
            </Button>
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cerrar
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>

      <AlertDialog open={confirmEliminar} onOpenChange={setConfirmEliminar}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar unidad</AlertDialogTitle>
            <AlertDialogDescription>
              {grupo.parcelaId ? (
                <>
                  ¿Seguro que querés eliminar la unidad <strong>{grupo.nombre}</strong>? Se borrarán
                  la parcela y todas las membresías asociadas. Los socios se mantienen en el padrón
                  sin unidad asignada.
                </>
              ) : (
                <>
                  ¿Seguro que querés eliminar el grupo <strong>{grupo.nombre}</strong>? Se van a
                  eliminar las {grupo.members.length} membresías de este grupo. Los socios se
                  mantienen en el padrón sin unidad asignada.
                  {grupo.members.some((m) => m.rol === "Titular")
                    ? " Una de las membresías tiene rol Titular."
                    : ""}
                </>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (grupo.parcelaId) {
                  deleteParcela.mutate(grupo.parcelaId, {
                    onSuccess: () => {
                      setConfirmEliminar(false);
                      onOpenChange(false);
                      toast.success(`Unidad ${grupo.nombre} eliminada`);
                    },
                    onError: () => toast.error("Error al eliminar la unidad"),
                  });
                  return;
                }
                if (grupo.members.length === 0) {
                  setConfirmEliminar(false);
                  onOpenChange(false);
                  return;
                }
                Promise.all(grupo.members.map((m) => deleteMembresia.mutateAsync(m.id)))
                  .then(() => {
                    setConfirmEliminar(false);
                    onOpenChange(false);
                    toast.success(`Grupo ${grupo.nombre} eliminado`);
                  })
                  .catch(() => toast.error("Error al eliminar el grupo"));
              }}
            >
              Eliminar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <CobrarUnidadDialog grupo={grupo} open={cobrando} onOpenChange={setCobrando} />

      {editando && (
        <EditarIntegranteDialog
          key={editando.id}
          membresia={editando}
          grupo={grupo}
          socios={socios}
          open={!!editando}
          onOpenChange={(o) => !o && setEditando(null)}
        />
      )}
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// EditarIntegranteDialog — full edit of a single unit member (RQ 10/12/14)
// ---------------------------------------------------------------------------

function EditarIntegranteDialog({
  membresia,
  grupo,
  socios,
  open,
  onOpenChange,
}: {
  membresia: Membresia;
  grupo: UnidadGroup;
  socios: Socio[];
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const updateMembresia = useUpdateMembresia();
  const deleteMembresia = useDeleteMembresia();

  const socioMap = useMemo(() => new Map(socios.map((s) => [s.id, s])), [socios]);
  const esTitular = membresia.rol === "Titular";
  const hayOtrosMiembros = grupo.members.length > 1;

  // Socio actual de la fila + socios que todavía no integran la unidad.
  const reemplazables = useMemo(
    () =>
      socios.filter(
        (s) => s.id === membresia.socioId || !grupo.members.some((m) => m.socioId === s.id),
      ),
    [socios, grupo.members, membresia.socioId],
  );

  const [socioId, setSocioId] = useState(membresia.socioId);
  const [estado, setEstado] = useState<EstadoMembresia>(membresia.estado);
  const [vencimiento, setVencimiento] = useState(membresia.vencimiento);
  const [detalle, setDetalle] = useState(membresia.detalle ?? "");
  const [confirmQuitar, setConfirmQuitar] = useState(false);

  function guardar() {
    const data: Partial<Membresia> = {};
    if (socioId !== membresia.socioId) data.socioId = socioId;
    if (estado !== membresia.estado) data.estado = estado;
    if (vencimiento !== membresia.vencimiento) data.vencimiento = vencimiento;
    if (detalle !== (membresia.detalle ?? "")) data.detalle = detalle;
    if (Object.keys(data).length === 0) {
      onOpenChange(false);
      return;
    }
    updateMembresia.mutate(
      { id: membresia.id, data },
      {
        onSuccess: () => {
          onOpenChange(false);
          toast.success("Integrante actualizado");
        },
        onError: () => toast.error("Error al guardar los cambios"),
      },
    );
  }

  function quitar() {
    deleteMembresia.mutate(membresia.id, {
      onSuccess: () => {
        onOpenChange(false);
        toast.success("Integrante quitado de la unidad");
      },
      onError: () => toast.error("Error al quitar el integrante"),
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Editar integrante</DialogTitle>
          <DialogDescription>
            {socioMap.get(membresia.socioId)?.nombre ?? membresia.socioId} · {grupo.nombre}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <Label>Socio</Label>
            <Select value={socioId} onValueChange={setSocioId}>
              <SelectTrigger className="mt-1.5">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {reemplazables.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.nombre} — {s.dni}
                  </SelectItem>
                ))}
                {reemplazables.length === 0 && (
                  <SelectItem value="__ninguno__" disabled>
                    No quedan socios por elegir
                  </SelectItem>
                )}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Estado</Label>
            <Select value={estado} onValueChange={(v) => setEstado(v as EstadoMembresia)}>
              <SelectTrigger className="mt-1.5">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ESTADOS.map((e) => (
                  <SelectItem key={e} value={e}>
                    {e}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
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
            <Label>Detalle (opcional)</Label>
            <Input
              className="mt-1.5"
              value={detalle}
              onChange={(e) => setDetalle(e.target.value)}
            />
          </div>
        </div>

        <div className="border-t border-border pt-4">
          <Button
            variant="outline"
            className="w-full text-destructive hover:bg-destructive hover:text-destructive-foreground"
            onClick={() => setConfirmQuitar(true)}
          >
            <Trash2 className="mr-1.5 size-4" /> Quitar de la unidad
          </Button>
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button onClick={guardar} disabled={updateMembresia.isPending}>
            Guardar
          </Button>
        </DialogFooter>
      </DialogContent>

      <AlertDialog open={confirmQuitar} onOpenChange={setConfirmQuitar}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Quitar de la unidad</AlertDialogTitle>
            <AlertDialogDescription>
              {esTitular
                ? hayOtrosMiembros
                  ? "Esta persona es la Titular: al quitarla, el primer integrante pasa a Titular automáticamente."
                  : "Esta persona es la única Titular: la unidad quedaría sin titular."
                : "La membresía se elimina. La persona se mantiene en el padrón, sin unidad asignada."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                setConfirmQuitar(false);
                quitar();
              }}
            >
              Quitar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// NuevaUnidadDialog
// ---------------------------------------------------------------------------

export function NuevaUnidadDialog({
  area,
  open,
  onOpenChange,
}: {
  area: Area;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const importParcelas = useImportParcelas();
  const { data: socios = [] } = useSocios();
  const { data: aranceles = [] } = useAranceles();
  const esCabaña = area === "Cabañeros";
  const tipo = tipoPorArea(area);

  const [nombre, setNombre] = useState("");
  const [categoria, setCategoria] = useState<CategoriaParcela | "">("");
  const [vencimiento, setVencimiento] = useState("");
  const [arancelId, setArancelId] = useState("");
  const [filas, setFilas] = useState<NuevaUnidadSocio[]>([{ nombre: "", dni: "" }]);
  const [pickerOpen, setPickerOpen] = useState(false);

  // Socios que todavía no están en el formulario (por DNI, en caso de coincidencia).
  const disponibles = useMemo(() => {
    const dnis = new Set(filas.map((f) => f.dni.trim()).filter(Boolean));
    return socios.filter((s: Socio) => !s.dni || !dnis.has(s.dni));
  }, [socios, filas]);

  // Aranceles del área+predio; para cabañas con categoría elegida, solo los de esa categoría.
  const arancelesUnidad = useMemo(
    () =>
      aranceles.filter(
        (a) =>
          a.area === area &&
          a.predio === predioDeTipo(tipo) &&
          (!esCabaña || !categoria || a.categoria === categoria),
      ),
    [aranceles, area, tipo, esCabaña, categoria],
  );

  function actualizarFila(i: number, campo: keyof NuevaUnidadSocio, valor: string) {
    setFilas((prev) => prev.map((f, idx) => (idx === i ? { ...f, [campo]: valor } : f)));
  }

  function agregarExistente(socio: Socio) {
    setFilas((prev) => {
      // Si la primera fila está vacía, el socio cargado ocupa esa posición y
      // queda como Titular (índice 0 = titular). Si ya hay alguien cargado,
      // se anexa al final como Integrante.
      const primera = prev[0];
      const primeraVacia = primera && !primera.nombre.trim() && !primera.dni.trim();
      if (primeraVacia) {
        return [{ nombre: socio.nombre, dni: socio.dni ?? "" }, ...prev.slice(1)];
      }
      return [...prev, { nombre: socio.nombre, dni: socio.dni ?? "" }];
    });
    setPickerOpen(false);
  }

  function crear() {
    const payload = buildNuevaUnidadPayload({
      nombre,
      tipo,
      ...(categoria ? { categoria } : {}),
      vencimiento,
      socios: filas,
      ...(arancelId ? { arancelId } : {}),
    });
    if (!payload) {
      toast.error("Completá el nombre de la unidad y al menos un socio (nombre y DNI)");
      return;
    }
    importParcelas.mutate(payload, {
      onSuccess: () => {
        onOpenChange(false);
        setNombre("");
        setCategoria("");
        setVencimiento("");
        setArancelId("");
        setFilas([{ nombre: "", dni: "" }]);
        toast.success("Unidad creada con sus socios");
      },
      onError: () => toast.error("Error al crear la unidad"),
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Nueva unidad</DialogTitle>
          <DialogDescription>
            La primera fila de socios es la Titular; el resto, integrantes.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <Label>Nombre de la unidad</Label>
              <Input
                className="mt-1.5"
                value={nombre}
                onChange={(e) => setNombre(e.target.value)}
                placeholder="Ej. Cabaña E"
              />
            </div>
            <div>
              <Label>Predio</Label>
              <div className="mt-1.5 flex h-9 items-center rounded-md border border-input bg-muted/40 px-3 text-sm text-muted-foreground">
                {predioDeTipo(tipo)}
              </div>
            </div>
            {esCabaña && (
              <div>
                <Label>Categoría (cabañas)</Label>
                <Select
                  value={categoria}
                  onValueChange={(v) => {
                    setCategoria(v as CategoriaParcela);
                    setArancelId("");
                  }}
                >
                  <SelectTrigger className="mt-1.5">
                    <SelectValue placeholder="Sin categoría" />
                  </SelectTrigger>
                  <SelectContent>
                    {CATEGORIAS_CABANA.map((c) => (
                      <SelectItem key={c} value={c}>
                        {c}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
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
                  {arancelesUnidad.map((a) => (
                    <SelectItem key={a.id} value={a.id}>
                      {a.nombre} — ${a.monto.toLocaleString("es-AR")}
                      {a.categoria ? ` (categoría: ${a.categoria})` : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Fecha de vencimiento</Label>
              <Input
                type="date"
                className="mt-1.5"
                value={vencimiento}
                onChange={(e) => setVencimiento(e.target.value)}
              />
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between">
              <Label className="text-sm font-semibold">Socios</Label>
              <div className="flex items-center gap-2">
                <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
                  <PopoverTrigger asChild>
                    <Button
                      size="sm"
                      variant="outline"
                      role="combobox"
                      aria-expanded={pickerOpen}
                      disabled={disponibles.length === 0}
                    >
                      <ChevronsUpDown className="mr-1 size-3.5" />
                      Agregar existente
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-[280px] p-0" align="end">
                    <Command>
                      <CommandInput placeholder="Buscar por nombre o DNI..." />
                      <CommandList>
                        <CommandEmpty>No se encontró ningún socio.</CommandEmpty>
                        <CommandGroup>
                          {disponibles.map((s: Socio) => (
                            <CommandItem
                              key={s.id}
                              value={`${s.nombre} ${s.dni ?? ""}`}
                              onSelect={() => agregarExistente(s)}
                            >
                              <Check className="size-4 opacity-0" />
                              <span className="flex-1 truncate">{s.nombre}</span>
                              <span className="text-xs text-muted-foreground">{s.dni}</span>
                            </CommandItem>
                          ))}
                        </CommandGroup>
                      </CommandList>
                    </Command>
                  </PopoverContent>
                </Popover>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setFilas((prev) => [...prev, { nombre: "", dni: "" }])}
                >
                  + Agregar fila
                </Button>
              </div>
            </div>
            <ul className="mt-2 space-y-2">
              {filas.map((f, i) => (
                <li
                  key={i}
                  className="flex flex-wrap items-center gap-2 rounded-md border border-border p-2.5"
                >
                  <Badge variant={i === 0 ? "default" : "secondary"}>
                    {i === 0 ? "Titular" : "Integrante"}
                  </Badge>
                  <Input
                    className="min-w-0 flex-1"
                    placeholder="Nombre y apellido"
                    value={f.nombre}
                    onChange={(e) => actualizarFila(i, "nombre", e.target.value)}
                  />
                  <Input
                    className="w-[120px]"
                    placeholder="DNI"
                    value={f.dni}
                    onChange={(e) => actualizarFila(i, "dni", e.target.value)}
                  />
                  {filas.length > 1 && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setFilas((prev) => prev.filter((_, idx) => idx !== i))}
                    >
                      Quitar
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button onClick={crear} disabled={importParcelas.isPending}>
            Crear unidad
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// CobrarUnidadDialog — cobro por unidad con una línea por arancel (ReQ-012)
// ---------------------------------------------------------------------------

/** Fecha de hoy en ISO corto, el default del cobro (PAG-02). */
function hoyIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function CobrarUnidadDialog({
  grupo,
  open,
  onOpenChange,
}: {
  grupo: UnidadGroup;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const navigate = useNavigate();
  const { data: aranceles = [] } = useAranceles();
  const { data: socios = [] } = useSocios();
  const { data: membresias = [] } = useMembresias();
  const createPago = useCreatePago();
  const [medio, setMedio] = useState("Transferencia");
  const [nota, setNota] = useState("");
  const [fecha, setFecha] = useState(hoyIso);
  const [marcas, setMarcas] = useState<Set<string>>(new Set());
  const [ajustes, setAjustes] = useState<Record<string, string>>({});

  const socioMap = useMemo(() => new Map(socios.map((s) => [s.id, s])), [socios]);
  const titular = grupo.members.find((m) => m.rol === "Titular") ?? grupo.members[0];

  /**
   * Membresía de cuota social del titular: ancla de esa línea, y la única forma
   * de ofrecerla con honestidad — sin ella el servidor rechaza el cobro (422).
   */
  const cuotaTitular = useMemo(
    () =>
      titular
        ? membresias.find(
            (m) => m.socioId === titular.socioId && conceptoDeMembresia(m) === "cuota social",
          )
        : undefined,
    [membresias, titular],
  );

  /**
   * Lugar de la unidad, derivado de SU membresía de área — nunca del titular
   * (ReQ-004): el titular puede no tener área (cuota social) y el bug viejo
   * tomaba su pareja area+predio como si fuera la de la unidad.
   */
  const lugar = useMemo<LugarCobrable | undefined>(() => {
    const area = grupo.members.find((m) => conceptoDeMembresia(m) === "area" && m.area && m.predio);
    if (!area?.area || !area.predio) return undefined;
    const ancla = membresiaDeLugar(grupo.members, {
      area: area.area,
      predio: area.predio,
      categoria: grupo.categoria,
    });
    if (!ancla) return undefined;
    return {
      area: area.area,
      predio: area.predio,
      categoria: grupo.categoria,
      membresiaId: ancla.id,
    };
  }, [grupo.members, grupo.categoria]);

  // Filas que este cobro puede tikear: el área del lugar, TODOS sus apartes de
  // servicio y los carriers por concepto (ReQ-001). La cuota social sólo se
  // ofrece si el titular la tiene: sin ella el servidor rechaza (422).
  const disponibles = useMemo(
    () =>
      arancelesDisponibles(aranceles, lugar ? [lugar] : []).filter((a) =>
        conceptoDeArancel(a) === "cuota social" ? Boolean(cuotaTitular) : true,
      ),
    [aranceles, lugar, cuotaTitular],
  );

  // Aviso ReQ-003: un lugar sin fila de servicio no calla, lo dice.
  const hayServicio = useMemo(
    () => disponibles.some((a) => conceptoDeArancel(a) === "servicio"),
    [disponibles],
  );

  const ajustesNum = useMemo(() => {
    const out: Record<string, number> = {};
    for (const [id, valor] of Object.entries(ajustes)) {
      const n = Number(valor);
      if (valor.trim() !== "" && Number.isFinite(n)) out[id] = n;
    }
    return out;
  }, [ajustes]);

  const lineas = useMemo(
    () =>
      itemsPorArancel(aranceles, lugar ? [lugar] : [], marcas, {
        anclas: { area: lugar?.membresiaId, cuota: cuotaTitular?.id },
        miembros: grupo.members.length,
        ajustes: ajustesNum,
      }),
    [aranceles, lugar, marcas, cuotaTitular, grupo.members.length, ajustesNum],
  );

  const total = totalEstimado(lineas);

  function alternar(arancelId: string) {
    setMarcas((prev) => {
      const next = new Set(prev);
      if (next.has(arancelId)) next.delete(arancelId);
      else next.add(arancelId);
      return next;
    });
  }

  function ajustar(arancelId: string, valor: string) {
    setAjustes((prev) => ({ ...prev, [arancelId]: valor }));
  }

  function confirmar() {
    if (!titular) {
      toast.error("La unidad no tiene socios");
      return;
    }
    const payload = buildUnitPago({
      titular: { socioId: titular.socioId, membresiaId: titular.id },
      integrantes: grupo.members
        .filter((m) => m.id !== titular.id)
        .map((m) => ({ membresiaId: m.id })),
      medio,
      fecha,
      ...(nota.trim() ? { nota: nota.trim() } : {}),
      items: lineas.map(lineaAPagoItem),
    });
    if (!payload) {
      toast.error("Elegí al menos un arancel para cobrar");
      return;
    }
    createPago.mutate(payload, {
      onSuccess: (pago) => {
        onOpenChange(false);
        // Total y desglose son los que resolvió el servidor. Nada de "renovadas
        // por 12 meses": qué se renueva depende de los conceptos marcados y
        // cuánto dura lo define el servidor (PAG-01, REN-01).
        toast.success(
          `Unidad cobrada: ${pago.items.map((i) => i.nombre).join(" + ")} · ${formatARS(pago.total)}`,
        );
        navigate({ to: "/pagos" });
      },
      onError: () => toast.error("Error al cobrar la unidad"),
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Cobrar unidad</DialogTitle>
          <DialogDescription>
            {grupo.nombre} · {grupo.predio}
            {grupo.categoria ? ` · ${grupo.categoria}` : ""}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <Label>Socios ({grupo.members.length})</Label>
            <ul className="mt-1.5 space-y-1">
              {grupo.members.map((m) => {
                const s = socioMap.get(m.socioId);
                return (
                  <li key={m.id} className="flex items-center justify-between text-sm">
                    <span>{s?.nombre ?? m.socioId}</span>
                    <span className="text-xs text-muted-foreground">{m.rol ?? "—"}</span>
                  </li>
                );
              })}
            </ul>
          </div>

          <div>
            <Label>Aranceles</Label>
            <ul className="mt-1.5 space-y-2">
              {disponibles.map((a) => {
                const concepto = conceptoDeArancel(a);
                const editable = concepto === "servicio" || concepto === "recargo";
                return (
                  <li
                    key={a.id}
                    className="flex items-center gap-3 rounded-md border border-border p-3"
                  >
                    <Checkbox checked={marcas.has(a.id)} onCheckedChange={() => alternar(a.id)} />
                    <div className="flex-1">
                      <p className="text-sm font-medium">{a.nombre}</p>
                      <p className="text-xs text-muted-foreground">
                        {detalleArancel(a, grupo.members.length)}
                      </p>
                    </div>
                    {editable && marcas.has(a.id) && (
                      <Input
                        type="number"
                        min={0}
                        step={100}
                        className="w-[110px]"
                        aria-label={`Importe de ${a.nombre}`}
                        value={ajustes[a.id] ?? ""}
                        onChange={(e) => ajustar(a.id, e.target.value)}
                        placeholder={String(a.monto || "")}
                      />
                    )}
                  </li>
                );
              })}
            </ul>
            {lugar && !hayServicio && (
              <p className="mt-2 text-xs text-muted-foreground">
                Sin arancel de servicio para esta área.
              </p>
            )}
          </div>

          {lineas.length > 0 && (
            <div className="rounded-md bg-secondary p-3">
              <p className="text-xs font-semibold tracking-wide uppercase">Ítems a cobrar</p>
              <ul className="mt-2 space-y-1 text-sm">
                {lineas.map((l) => (
                  <li key={l.arancelId} className="flex justify-between">
                    <span>
                      {l.arancelNombre}
                      {l.factor > 1 && <span className="text-muted-foreground"> ×{l.factor}</span>}
                    </span>
                    <span className="tabular-nums">{formatARS(l.monto)}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-2 flex justify-between border-t border-border pt-2 text-sm font-bold">
                <span>Total estimado</span>
                <span className="tabular-nums">{formatARS(total)}</span>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                Estimación del cliente: el importe final lo calcula el servidor.
              </p>
            </div>
          )}

          <div>
            <Label>Medio de pago</Label>
            <Select value={medio} onValueChange={setMedio}>
              <SelectTrigger className="mt-1.5">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="Transferencia">Transferencia</SelectItem>
                <SelectItem value="Efectivo">Efectivo</SelectItem>
                <SelectItem value="Débito">Débito</SelectItem>
                <SelectItem value="Crédito">Crédito</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div>
            <Label htmlFor="unidad-fecha">Fecha del cobro</Label>
            <Input
              id="unidad-fecha"
              type="date"
              className="mt-1.5"
              value={fecha}
              onChange={(e) => setFecha(e.target.value)}
            />
          </div>

          <div>
            <Label htmlFor="unidad-nota">Nota (opcional)</Label>
            <Textarea
              id="unidad-nota"
              value={nota}
              onChange={(e) => setNota(e.target.value)}
              placeholder="Texto que se muestra en el comprobante"
              className="mt-1.5"
              rows={3}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            El comprobante queda a nombre del titular. Solo renuevan las membresías cuyo concepto
            esté marcado.
          </p>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button onClick={confirmar} disabled={createPago.isPending || lineas.length === 0}>
            Confirmar pago
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Concepto de una fila de catálogo; sin `concepto` servido, una fila es de área. */
function conceptoDeArancel(a: Arancel): ConceptoCobro {
  return a.concepto ?? "area";
}

/**
 * Texto auxiliar de una fila de catálogo: cuánto costaría y por qué se multiplica.
 * Es sólo la estimación del cliente; el servidor re-resuelve cada línea (PAG-01).
 */
function detalleArancel(a: Arancel, miembros: number): string {
  const concepto = conceptoDeArancel(a);
  if (concepto === "cuota social") return `${formatARS(a.monto)} × ${miembros} miembros`;
  if (concepto === "servicio") return `Catálogo ${formatARS(a.monto)} (ajustable)`;
  if (concepto === "recargo") return "Importe que defina el operador";
  return formatARS(a.monto);
}
