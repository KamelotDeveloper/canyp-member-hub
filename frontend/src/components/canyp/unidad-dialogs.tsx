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
import { useNavigate } from "@tanstack/react-router";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import { buildUnitPago } from "@/lib/canyp/api";
import {
  itemsParaMembresias,
  buildNuevaUnidadPayload,
  type NuevaUnidadSocio,
} from "@/lib/canyp/unidad-helpers";
import {
  useSocios,
  useAranceles,
  useUpdateParcela,
  useDeleteMembresia,
  useCreateMembresia,
  useCreateSocio,
  useSetBatchEstado,
  useSetBatchVencimiento,
  useCreatePago,
  useImportParcelas,
} from "@/lib/canyp/queries";
import { formatFecha } from "@/lib/canyp/utils";
import type {
  Area,
  CategoriaParcela,
  EstadoMembresia,
  Membresia,
  Parcela,
  Predio,
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
  const navigate = useNavigate();
  const { data: socios = [] } = useSocios();
  const { data: aranceles = [] } = useAranceles();

  const updateParcela = useUpdateParcela();
  const deleteMembresia = useDeleteMembresia();
  const createMembresia = useCreateMembresia();
  const createSocio = useCreateSocio();
  const setBatchEstado = useSetBatchEstado();
  const setBatchVencimiento = useSetBatchVencimiento();
  const createPago = useCreatePago();

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

  function quitarIntegrante(m: Membresia) {
    deleteMembresia.mutate(m.id, {
      onSuccess: () =>
        toast.success(
          `Se quitó ${socioMap.get(m.socioId)?.nombre ?? "el integrante"} de la unidad`,
        ),
      onError: () => toast.error("Error al quitar el integrante"),
    });
  }

  function agregarExistente() {
    if (!socioAAgregar || !grupo.parcelaId) return;
    createMembresia.mutate(
      {
        socioId: socioAAgregar,
        area,
        predio: grupo.predio,
        estado: "activa",
        vencimiento: vencimientoPorDefecto(grupo.members),
        rol: "Integrante",
        parcelaId: grupo.parcelaId,
      },
      {
        onSuccess: () => {
          setSocioAAgregar("");
          toast.success("Integrante agregado a la unidad");
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
    createSocio.mutate(
      {
        nombre: nuevoNombre.trim(),
        dni: nuevoDni.trim(),
        telefono: nuevoTel.trim(),
        email: nuevoMail.trim(),
        direccion: "",
        activo: true,
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
                rol: "Integrante",
                parcelaId: grupo.parcelaId,
              },
              {
                onSuccess: () => toast.success("Nuevo socio creado y agregado a la unidad"),
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
      { parcelaId: grupo.parcelaId, vencimiento: vencBatch },
      {
        onSuccess: () => {
          setVencBatch("");
          toast.success("Vencimiento aplicado a todos los integrantes");
        },
        onError: () => toast.error("Error al cambiar el vencimiento"),
      },
    );
  }

  function cobrarUnidad() {
    const titular = grupo.members.find((m) => m.rol === "Titular") ?? grupo.members[0];
    if (!titular) {
      toast.error("La unidad no tiene socios");
      return;
    }
    const items = itemsParaMembresias(grupo.members, aranceles);
    const payload = buildUnitPago({
      titular: { socioId: titular.socioId, membresiaId: titular.id },
      integrantes: grupo.members
        .filter((m) => m.id !== titular.id)
        .map((m) => ({ membresiaId: m.id })),
      medio: "Transferencia",
      items,
    });
    if (!payload) {
      toast.error("No hay aranceles para cobrar esta unidad");
      return;
    }
    createPago.mutate(payload, {
      onSuccess: () => {
        onOpenChange(false);
        toast.success("Unidad cobrada: membresías renovadas por 12 meses.");
        navigate({ to: "/pagos", search: { nuevo: "1", socioId: titular.socioId } });
      },
      onError: () => toast.error("Error al cobrar la unidad"),
    });
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
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{s?.nombre ?? m.socioId}</p>
                      <p className="text-xs text-muted-foreground">
                        Vence {formatFecha(m.vencimiento)}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant={m.rol === "Titular" ? "default" : "secondary"}>
                        {m.rol ?? "—"}
                      </Badge>
                      {m.rol !== "Titular" && (
                        <Button size="sm" variant="ghost" onClick={() => quitarIntegrante(m)}>
                          Quitar
                        </Button>
                      )}
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
          <Button variant="outline" onClick={cobrarUnidad} disabled={grupo.members.length === 0}>
            Cobrar unidad
          </Button>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cerrar
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// NuevaUnidadDialog
// ---------------------------------------------------------------------------

const PREDIOS: Predio[] = ["Almafuerte", "Embalse"];

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
  const esCabaña = area === "Cabañeros";
  const tipo = tipoPorArea(area);

  const [nombre, setNombre] = useState("");
  const [predio, setPredio] = useState<Predio>("Almafuerte");
  const [categoria, setCategoria] = useState<CategoriaParcela | "">("");
  const [vencimiento, setVencimiento] = useState("");
  const [filas, setFilas] = useState<NuevaUnidadSocio[]>([{ nombre: "", dni: "" }]);

  function actualizarFila(i: number, campo: keyof NuevaUnidadSocio, valor: string) {
    setFilas((prev) => prev.map((f, idx) => (idx === i ? { ...f, [campo]: valor } : f)));
  }

  function crear() {
    const payload = buildNuevaUnidadPayload({
      nombre,
      tipo,
      ...(categoria ? { categoria } : {}),
      predio,
      vencimiento,
      socios: filas,
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
              <Select value={predio} onValueChange={(v) => setPredio(v as Predio)}>
                <SelectTrigger className="mt-1.5">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PREDIOS.map((p) => (
                    <SelectItem key={p} value={p}>
                      {p}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
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
              <Button
                size="sm"
                variant="outline"
                onClick={() => setFilas((prev) => [...prev, { nombre: "", dni: "" }])}
              >
                + Agregar fila
              </Button>
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
