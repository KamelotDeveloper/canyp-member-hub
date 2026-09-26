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
import { formatARS, formatFecha } from "@/lib/canyp/utils";
import {
  useAranceles,
  useCreateArancel,
  useDeleteArancel,
  useUpdateArancel,
} from "@/lib/canyp/queries";
import type { Area, CategoriaParcela, Predio } from "@/lib/canyp/types";

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

/** Estado del dialog de edición: copia editable de TODOS los campos. */
interface EditarEstado {
  id: string;
  nombre: string;
  area: Area;
  predio: Predio;
  monto: string;
  categoria: CategoriaParcela | null;
  vigenteDesde: string;
}

const CATEGORIAS: CategoriaParcela[] = ["Chica", "Mediana", "Especial", "Grande"];

function ArancelesPage() {
  const { data: aranceles = [], isLoading } = useAranceles();
  const createMutation = useCreateArancel();
  const updateMutation = useUpdateArancel();
  const deleteMutation = useDeleteArancel();
  const [editar, setEditar] = useState<EditarEstado | null>(null);
  const [eliminar, setEliminar] = useState<string | null>(null);
  const [historial, setHistorial] = useState<string | null>(null);
  const [nuevoOpen, setNuevoOpen] = useState(false);
  const [nuevo, setNuevo] = useState<{ nombre: string; area: Area; predio: Predio; monto: string }>(
    {
      nombre: "",
      area: "Balseros",
      predio: "Embalse",
      monto: "",
    },
  );

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
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        setEditar({
                          id: a.id,
                          nombre: a.nombre,
                          area: a.area,
                          predio: a.predio,
                          monto: String(a.monto),
                          categoria: a.categoria ?? null,
                          vigenteDesde: a.vigenteDesde,
                        })
                      }
                    >
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
              Editá nombre, área, predio o monto. Al cambiar el monto, el anterior queda en el
              histórico.
            </DialogDescription>
          </DialogHeader>
          {editar && (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <Label>Nombre del ítem</Label>
                <Input
                  className="mt-1.5"
                  value={editar.nombre}
                  onChange={(e) => setEditar({ ...editar, nombre: e.target.value })}
                />
              </div>
              <div>
                <Label>Área</Label>
                <Select
                  value={editar.area}
                  onValueChange={(v) => setEditar({ ...editar, area: v as Area })}
                >
                  <SelectTrigger className="mt-1.5">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Balseros">Balseros</SelectItem>
                    <SelectItem value="Cabañeros">Cabañeros</SelectItem>
                    <SelectItem value="Guardería">Guardería</SelectItem>
                    <SelectItem value="Windsurf">Windsurf</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Predio</Label>
                <Select
                  value={editar.predio}
                  onValueChange={(v) => setEditar({ ...editar, predio: v as Predio })}
                >
                  <SelectTrigger className="mt-1.5">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Embalse">Embalse</SelectItem>
                    <SelectItem value="Almafuerte">Almafuerte</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Categoría (opcional)</Label>
                <Select
                  value={editar.categoria ?? "sin-categoria"}
                  onValueChange={(v) =>
                    setEditar({
                      ...editar,
                      categoria: v === "sin-categoria" ? null : (v as CategoriaParcela),
                    })
                  }
                >
                  <SelectTrigger className="mt-1.5">
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
              </div>
              <div>
                <Label>Monto</Label>
                <Input
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
                  {
                    id: editar.id,
                    data: {
                      nombre: editar.nombre,
                      area: editar.area,
                      predio: editar.predio,
                      monto: Number(editar.monto) || 0,
                      categoria: editar.categoria,
                      vigenteDesde: editar.vigenteDesde,
                    },
                  },
                  {
                    onSuccess: () => {
                      setEditar(null);
                      toast.success("Arancel actualizado");
                    },
                    onError: () => toast.error("No se pudo actualizar el arancel."),
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
              Se va a eliminar “{arancelEliminar?.nombre}”. Esta acción no se puede deshacer.
              Los pagos ya emitidos conservan el monto y nombre guardados en su comprobante.
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
                  onError: () => toast.error("No se pudo eliminar el ítem de arancel."),
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
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Label>Nombre del ítem</Label>
              <Input
                className="mt-1.5"
                value={nuevo.nombre}
                onChange={(e) => setNuevo({ ...nuevo, nombre: e.target.value })}
              />
            </div>
            <div>
              <Label>Área</Label>
              <Select
                value={nuevo.area}
                onValueChange={(v) => setNuevo({ ...nuevo, area: v as Area })}
              >
                <SelectTrigger className="mt-1.5">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="Balseros">Balseros</SelectItem>
                  <SelectItem value="Cabañeros">Cabañeros</SelectItem>
                  <SelectItem value="Guardería">Guardería</SelectItem>
                  <SelectItem value="Windsurf">Windsurf</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Predio</Label>
              <Select
                value={nuevo.predio}
                onValueChange={(v) => setNuevo({ ...nuevo, predio: v as Predio })}
              >
                <SelectTrigger className="mt-1.5">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="Embalse">Embalse</SelectItem>
                  <SelectItem value="Almafuerte">Almafuerte</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="sm:col-span-2">
              <Label>Monto</Label>
              <Input
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
                  {
                    nombre: nuevo.nombre,
                    area: nuevo.area,
                    predio: nuevo.predio,
                    monto: Number(nuevo.monto) || 0,
                    vigenteDesde: new Date().toISOString().slice(0, 10),
                  },
                  {
                    onSuccess: () => {
                      setNuevoOpen(false);
                      setNuevo({ nombre: "", area: "Balseros", predio: "Embalse", monto: "" });
                      toast.success("Ítem de arancel creado");
                    },
                    onError: () => toast.error("No se pudo crear el ítem de arancel."),
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
