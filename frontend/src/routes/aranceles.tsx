import { createFileRoute } from "@tanstack/react-router";
import { History, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PageHeader } from "@/components/canyp/AppShell";
import { ExportButton } from "@/components/export";
import { AreaBadge } from "@/components/canyp/AreaBadge";
import { ConceptoBadge } from "@/components/canyp/ConceptoBadge";
import { formatARS, formatFecha } from "@/lib/canyp/utils";
import {
  ARANCEL_FORM_VACIO,
  CONCEPTO_AYUDA,
  CONCEPTO_LABELS,
  CONCEPTOS,
  esPorLugar,
  formDeArancel,
  mensajeDeError,
  payloadArancel,
  usaCategoria,
  type ArancelForm,
} from "@/lib/canyp/arancel-helpers";
import {
  useAranceles,
  useCreateArancel,
  useDeleteArancel,
  useUpdateArancel,
} from "@/lib/canyp/queries";
import type { Area, CategoriaParcela, ConceptoCobro, Predio } from "@/lib/canyp/types";

export const Route = createFileRoute("/aranceles")({
  head: () => ({
    meta: [
      { title: "Aranceles — CANYP Gestión" },
      {
        name: "description",
        content: "Catálogo de precios por área con monto vigente e histórico de actualizaciones.",
      },
      { property: "og:title", content: "Aranceles — CANYP Gestión" },
      {
        property: "og:description",
        content: "Actualizá montos sin perder el histórico de valores anteriores.",
      },
    ],
  }),
  component: ArancelesPage,
});

/** Estado del dialog de edición: la fila completa, editable (ReQ-005). */
type EditarEstado = ArancelForm & { id: string; vigenteDesde: string };

const CATEGORIAS: CategoriaParcela[] = ["Chica", "Mediana", "Especial", "Grande"];
const AREAS: Area[] = ["Balseros", "Cabañeros", "Guardería", "Windsurf"];
const PREDIOS: Predio[] = ["Embalse", "Almafuerte"];

/**
 * Selects del catálogo.
 *
 * Son los mismos campos en el alta y en la edición, así que viven una vez: la
 * diferencia entre ambos formularios NO es qué campos existen sino cuáles aplican
 * al concepto elegido (`esPorLugar` / `usaCategoria`).
 */
function ConceptoSelect({
  id,
  value,
  onChange,
}: {
  id: string;
  value: ConceptoCobro;
  onChange: (v: ConceptoCobro) => void;
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as ConceptoCobro)}>
      <SelectTrigger id={id} className="mt-1.5">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {CONCEPTOS.map((c) => (
          <SelectItem key={c} value={c}>
            {CONCEPTO_LABELS[c]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function AreaSelect({
  id,
  value,
  onChange,
}: {
  id: string;
  value: Area;
  onChange: (v: Area) => void;
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as Area)}>
      <SelectTrigger id={id} className="mt-1.5">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {AREAS.map((a) => (
          <SelectItem key={a} value={a}>
            {a}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function PredioSelect({
  id,
  value,
  onChange,
}: {
  id: string;
  value: Predio;
  onChange: (v: Predio) => void;
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as Predio)}>
      <SelectTrigger id={id} className="mt-1.5">
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
  );
}

function CategoriaSelect({
  id,
  value,
  onChange,
}: {
  id: string;
  value: CategoriaParcela | null;
  onChange: (v: CategoriaParcela | null) => void;
}) {
  return (
    <Select
      value={value ?? "sin-categoria"}
      onValueChange={(v) => onChange(v === "sin-categoria" ? null : (v as CategoriaParcela))}
    >
      <SelectTrigger id={id} className="mt-1.5">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="sin-categoria">Sin categoría</SelectItem>
        {CATEGORIAS.map((c) => (
          <SelectItem key={c} value={c}>
            {c}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/**
 * Los campos de lugar y categoría que el concepto elegido necesita.
 *
 * `idPrefix` mantiene los `id` únicos entre el alta y la edición: los `Label`
 * apuntan con `htmlFor` a su control, así que el lector de pantalla anuncia
 * qué está por completar y no sólo un texto suelto al lado.
 */
function CamposDeConcepto({
  form,
  set,
  idPrefix,
}: {
  form: ArancelForm;
  /** Parche del form: el alta y la edición comparten los mismos campos. */
  set: (patch: Partial<ArancelForm>) => void;
  idPrefix: string;
}) {
  return (
    <>
      <div>
        <Label htmlFor={`${idPrefix}-concepto`}>Concepto</Label>
        <ConceptoSelect
          id={`${idPrefix}-concepto`}
          value={form.concepto}
          onChange={(concepto) => set({ concepto })}
        />
        <p className="mt-1.5 text-xs text-muted-foreground">{CONCEPTO_AYUDA[form.concepto]}</p>
      </div>
      {esPorLugar(form.concepto) ? (
        <>
          <div>
            <Label htmlFor={`${idPrefix}-area`}>Área</Label>
            <AreaSelect
              id={`${idPrefix}-area`}
              value={form.area}
              onChange={(area) => set({ area })}
            />
          </div>
          <div>
            <Label htmlFor={`${idPrefix}-predio`}>Predio</Label>
            <PredioSelect
              id={`${idPrefix}-predio`}
              value={form.predio}
              onChange={(predio) => set({ predio })}
            />
          </div>
        </>
      ) : (
        <div className="sm:col-span-3 text-xs text-muted-foreground">
          Este concepto se resuelve por concepto, no por lugar: el área y el predio del ítem no
          definen su precio.
        </div>
      )}
      {usaCategoria(form.concepto) && (
        <div>
          <Label htmlFor={`${idPrefix}-categoria`}>Categoría (opcional)</Label>
          <CategoriaSelect
            id={`${idPrefix}-categoria`}
            value={form.categoria}
            onChange={(categoria) => set({ categoria })}
          />
        </div>
      )}
    </>
  );
}

export function ArancelesPage() {
  const { data: aranceles = [], isLoading } = useAranceles();
  const createMutation = useCreateArancel();
  const updateMutation = useUpdateArancel();
  const deleteMutation = useDeleteArancel();
  const [editar, setEditar] = useState<EditarEstado | null>(null);
  const [eliminar, setEliminar] = useState<string | null>(null);
  const [historial, setHistorial] = useState<string | null>(null);
  const [nuevoOpen, setNuevoOpen] = useState(false);
  const [nuevo, setNuevo] = useState<ArancelForm>(ARANCEL_FORM_VACIO);

  const arancelHist = aranceles.find((a) => a.id === historial);
  const arancelEliminar = aranceles.find((a) => a.id === eliminar);

  if (isLoading) {
    return (
      <>
        <PageHeader title="Aranceles" subtitle="Cargando..." />
        <Card className="p-10 text-center text-sm text-muted-foreground">
          Cargando aranceles...
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Aranceles"
        subtitle="Montos vigentes por área. Al cargar un nuevo monto, el anterior queda como histórico."
        actions={
          <>
            <ExportButton resource="aranceles" label="aranceles" />
            <Button onClick={() => setNuevoOpen(true)}>
              <Plus className="mr-2 size-4" /> Nuevo ítem de arancel
            </Button>
          </>
        }
      />

      <Card className="overflow-hidden p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Ítem</TableHead>
              <TableHead>Concepto</TableHead>
              <TableHead>Área</TableHead>
              <TableHead>Predio</TableHead>
              <TableHead>Categoría</TableHead>
              <TableHead>Vigente desde</TableHead>
              <TableHead className="text-right">Monto vigente</TableHead>
              <TableHead className="text-right">Acciones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {aranceles.map((a) => (
              <TableRow key={a.id}>
                <TableCell className="font-medium">{a.nombre}</TableCell>
                <TableCell className="text-xs">
                  <ConceptoBadge concepto={a.concepto} />
                </TableCell>
                <TableCell className="text-xs">
                  <AreaBadge area={a.area} />
                </TableCell>
                <TableCell className="text-xs">{a.predio}</TableCell>
                <TableCell className="text-xs">{a.categoria ?? "—"}</TableCell>
                <TableCell className="text-xs tabular-nums">
                  {formatFecha(a.vigenteDesde)}
                </TableCell>
                <TableCell className="text-right text-base font-semibold tabular-nums">
                  {formatARS(a.monto)}
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-2">
                    <Button size="sm" variant="ghost" onClick={() => setHistorial(a.id)}>
                      <History className="mr-1.5 size-3.5" /> Histórico ({a.historico.length})
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setEditar(formDeArancel(a))}>
                      <Pencil className="mr-1.5 size-3.5" /> Editar
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setEliminar(a.id)}>
                      <Trash2 className="mr-1.5 size-3.5" /> Eliminar
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <Dialog open={!!editar} onOpenChange={(o) => !o && setEditar(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Editar ítem de arancel</DialogTitle>
            <DialogDescription>
              Editá nombre, concepto, área, predio o monto. Al cambiar el monto, el anterior queda
              en el histórico. Si el concepto nuevo deja la tupla repetida, el catálogo lo rechaza y
              te dice contra qué ítem choca.
            </DialogDescription>
          </DialogHeader>
          {editar && (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <Label htmlFor="editar-nombre">Nombre del ítem</Label>
                <Input
                  id="editar-nombre"
                  className="mt-1.5"
                  value={editar.nombre}
                  onChange={(e) => setEditar({ ...editar, nombre: e.target.value })}
                />
              </div>
              <CamposDeConcepto
                form={editar}
                set={(patch) => setEditar({ ...editar, ...patch })}
                idPrefix="editar"
              />
              <div>
                <Label htmlFor="editar-monto">Monto</Label>
                <Input
                  id="editar-monto"
                  type="number"
                  className="mt-1.5"
                  value={editar.monto}
                  onChange={(e) => setEditar({ ...editar, monto: e.target.value })}
                />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditar(null)}>
              Cancelar
            </Button>
            <Button
              disabled={updateMutation.isPending}
              onClick={() => {
                if (!editar) return;
                updateMutation.mutate(
                  { id: editar.id, data: payloadArancel(editar, editar.vigenteDesde) },
                  {
                    onSuccess: () => {
                      setEditar(null);
                      toast.success("Arancel actualizado");
                    },
                    // El 409 de tupla duplicada se muestra entero y el form queda
                    // abierto para corregir la tupla (ReQ-006).
                    onError: (e) =>
                      toast.error(mensajeDeError(e, "No se pudo actualizar el arancel.")),
                  },
                );
              }}
            >
              Guardar cambios
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={!!eliminar} onOpenChange={(o) => !o && setEliminar(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Eliminar este ítem de arancel?</AlertDialogTitle>
            <AlertDialogDescription>
              Se va a eliminar “{arancelEliminar?.nombre}”. Esta acción no se puede deshacer. Los
              pagos ya emitidos conservan el monto y nombre guardados en su comprobante. Si el ítem
              sigue referenciado por pagos o membresías, el catálogo lo rechaza y dice qué lo
              bloquea.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              disabled={deleteMutation.isPending}
              onClick={(e) => {
                e.preventDefault();
                if (!eliminar) return;
                deleteMutation.mutate(eliminar, {
                  onSuccess: () => {
                    setEliminar(null);
                    toast.success("Ítem de arancel eliminado");
                  },
                  // 409 con los conteos de pagos/membresías que bloquean el borrado:
                  // el diálogo queda abierto y la tabla no se toca (ReQ-007).
                  onError: (e) =>
                    toast.error(mensajeDeError(e, "No se pudo eliminar el ítem de arancel.")),
                });
              }}
            >
              Eliminar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog open={!!historial} onOpenChange={(o) => !o && setHistorial(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Histórico de montos</DialogTitle>
            <DialogDescription>{arancelHist?.nombre}</DialogDescription>
          </DialogHeader>
          <ul className="divide-y divide-border text-sm">
            <li className="flex justify-between py-2">
              <span className="font-medium">
                Vigente desde {arancelHist && formatFecha(arancelHist.vigenteDesde)}
              </span>
              <span className="font-semibold tabular-nums">
                {arancelHist && formatARS(arancelHist.monto)}
              </span>
            </li>
            {arancelHist?.historico.map((h, i) => (
              <li key={i} className="flex justify-between py-2 text-muted-foreground">
                <span>Desde {formatFecha(h.vigenteDesde)}</span>
                <span className="tabular-nums">{formatARS(h.monto)}</span>
              </li>
            ))}
            {arancelHist?.historico.length === 0 && (
              <li className="py-3 text-xs text-muted-foreground">Sin actualizaciones previas.</li>
            )}
          </ul>
        </DialogContent>
      </Dialog>

      <Dialog open={nuevoOpen} onOpenChange={setNuevoOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nuevo ítem de arancel</DialogTitle>
            <DialogDescription>
              El concepto define a qué ítem del cobro puede servir este precio. Elegí el correcto:
              dos filas con el mismo nombre y distinto concepto cobran distinto.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Label htmlFor="nuevo-nombre">Nombre del ítem</Label>
              <Input
                id="nuevo-nombre"
                className="mt-1.5"
                value={nuevo.nombre}
                onChange={(e) => setNuevo({ ...nuevo, nombre: e.target.value })}
              />
            </div>
            <CamposDeConcepto
              form={nuevo}
              set={(patch) => setNuevo({ ...nuevo, ...patch })}
              idPrefix="nuevo"
            />
            <div className="sm:col-span-2">
              <Label htmlFor="nuevo-monto">Monto</Label>
              <Input
                id="nuevo-monto"
                type="number"
                className="mt-1.5"
                value={nuevo.monto}
                onChange={(e) => setNuevo({ ...nuevo, monto: e.target.value })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setNuevoOpen(false)}>
              Cancelar
            </Button>
            <Button
              disabled={createMutation.isPending}
              onClick={() => {
                if (!nuevo.nombre) {
                  toast.error("Ingresá un nombre");
                  return;
                }
                createMutation.mutate(
                  payloadArancel(nuevo, new Date().toISOString().slice(0, 10)),
                  {
                    onSuccess: () => {
                      setNuevoOpen(false);
                      setNuevo(ARANCEL_FORM_VACIO);
                      toast.success("Ítem de arancel creado");
                    },
                    // El 409 de tupla duplicada se muestra entero y el form queda
                    // abierto para cambiar la tupla (ReQ-006).
                    onError: (e) =>
                      toast.error(mensajeDeError(e, "No se pudo crear el ítem de arancel.")),
                  },
                );
              }}
            >
              Crear ítem
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
