import { createFileRoute } from "@tanstack/react-router";
import { History, Plus } from "lucide-react";
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
import { AreaBadge } from "@/components/canyp/AreaBadge";
import { formatARS, formatFecha } from "@/lib/canyp/utils";
import { useAranceles, useCreateArancel, useUpdateArancelMonto } from "@/lib/canyp/queries";
import type { Area, Predio } from "@/lib/canyp/types";

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

function ArancelesPage() {
  const { data: aranceles = [], isLoading } = useAranceles();
  const createMutation = useCreateArancel();
  const updateMontoMutation = useUpdateArancelMonto();
  const [editar, setEditar] = useState<{ id: string; nombre: string; monto: string } | null>(null);
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
          <Button onClick={() => setNuevoOpen(true)}>
            <Plus className="mr-2 size-4" /> Nuevo ítem de arancel
          </Button>
        }
      />

      <Card className="overflow-hidden p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Ítem</TableHead>
              <TableHead>Área</TableHead>
              <TableHead>Predio</TableHead>
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
                        setEditar({ id: a.id, nombre: a.nombre, monto: String(a.monto) })
                      }
                    >
                      Actualizar monto
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <Dialog open={!!editar} onOpenChange={(o) => !o && setEditar(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Actualizar monto</DialogTitle>
            <DialogDescription>{editar?.nombre}</DialogDescription>
          </DialogHeader>
          <div>
            <Label>Nuevo monto</Label>
            <Input
              type="number"
              className="mt-1.5"
              value={editar?.monto ?? ""}
              onChange={(e) => setEditar((p) => (p ? { ...p, monto: e.target.value } : p))}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditar(null)}>
              Cancelar
            </Button>
            <Button
              onClick={() => {
                if (editar) {
                  updateMontoMutation.mutate(
                    { id: editar.id, monto: Number(editar.monto) || 0 },
                    {
                      onSuccess: () =>
                        toast.success("Monto actualizado. El anterior quedó en el histórico."),
                      onError: () => toast.error("No se pudo actualizar el monto."),
                    },
                  );
                }
                setEditar(null);
              }}
            >
              Guardar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
