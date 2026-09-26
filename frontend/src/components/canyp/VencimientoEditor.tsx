import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
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
import { useSocios, useSetBatchVencimiento, useUpdateMembresiaVencimiento } from "@/lib/canyp/queries";
import type { ConceptoMembresia, Membresia, Parcela } from "@/lib/canyp/types";

/**
 * Editor manual de `vencimiento` (CBM-06 / UI-03).
 *
 * El backend es la única autoridad del estado: este editor solo fija la FECHA
 * absoluta de una membresía (o de un lote) y el estado se recalcula en la
 * próxima lectura (EST-02). La fecha se guarda VERBATIM — sin proyección a día
 * 10 — y se acepta una fecha pasada, porque las filas legacy a corregir están
 * justamente vencidas. No crea ni altera ningún `Pago`.
 */

/** Etiqueta legible de una membresía: su área+predio o "Cuota social". */
function etiquetaMembresia(m: Membresia): string {
  return m.area ? `${m.area} · ${m.predio}` : "Cuota social";
}

/**
 * Edición individual: fija el vencimiento de UNA membresía (área o cuota social).
 * Confirma antes de guardar.
 */
export function EditarVencimientoMembresia({
  membresia,
  onClose,
}: {
  membresia: Membresia;
  onClose: () => void;
}) {
  const update = useUpdateMembresiaVencimiento();
  const { data: socios = [] } = useSocios();
  const [fecha, setFecha] = useState(membresia.vencimiento);

  const socio = socios.find((s) => s.id === membresia.socioId);

  function guardar() {
    if (!fecha) {
      toast.error("Elegí una fecha");
      return;
    }
    update.mutate(
      { id: membresia.id, vencimiento: fecha },
      {
        onSuccess: () => {
          onClose();
          toast.success("Vencimiento actualizado");
        },
        onError: () => toast.error("No se pudo actualizar el vencimiento"),
      },
    );
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Editar vencimiento</DialogTitle>
          <DialogDescription>
            {socio?.nombre ?? membresia.socioId} · {etiquetaMembresia(membresia)}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor="venc-membresia">Nueva fecha</Label>
            <Input
              id="venc-membresia"
              type="date"
              className="mt-1.5"
              value={fecha}
              onChange={(e) => setFecha(e.target.value)}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            Se guarda tal cual, sin redondeo. No se crea ningún pago: el estado se recalcula en la
            próxima lectura.
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancelar
          </Button>
          <Button onClick={guardar} disabled={update.isPending || !fecha}>
            Guardar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Edición por lote: fija el vencimiento de todas las membresías de una parcela
 * para UN concepto (`area` | `cuota social`). Confirma antes de aplicar.
 */
export function EditarVencimientoLote({
  parcelas,
  onClose,
}: {
  parcelas: Parcela[];
  onClose: () => void;
}) {
  const batch = useSetBatchVencimiento();
  const [parcelaId, setParcelaId] = useState("");
  const [concepto, setConcepto] = useState<ConceptoMembresia>("area");
  const [fecha, setFecha] = useState("");

  const parcela = parcelas.find((p) => p.id === parcelaId);

  function aplicar() {
    if (!parcelaId || !fecha) {
      toast.error("Elegí una parcela y una fecha");
      return;
    }
    batch.mutate(
      { parcelaId, vencimiento: fecha, concepto },
      {
        onSuccess: () => {
          onClose();
          toast.success("Vencimiento aplicado al lote");
        },
        onError: () => toast.error("No se pudo aplicar el vencimiento"),
      },
    );
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Vencimiento por lote</DialogTitle>
          <DialogDescription>
            Aplica la fecha a todas las membresías de la parcela para un concepto.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label>Parcela / unidad</Label>
            <Select value={parcelaId} onValueChange={setParcelaId}>
              <SelectTrigger className="mt-1.5">
                <SelectValue placeholder="Elegir parcela" />
              </SelectTrigger>
              <SelectContent>
                {parcelas.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.nombre}
                  </SelectItem>
                ))}
                {parcelas.length === 0 && (
                  <SelectItem value="__ninguna__" disabled>
                    No hay parcelas
                  </SelectItem>
                )}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Concepto</Label>
            <Select value={concepto} onValueChange={(v) => setConcepto(v as ConceptoMembresia)}>
              <SelectTrigger className="mt-1.5">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="area">Área</SelectItem>
                <SelectItem value="cuota social">Cuota social</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label htmlFor="venc-lote">Nueva fecha</Label>
            <Input
              id="venc-lote"
              type="date"
              className="mt-1.5"
              value={fecha}
              onChange={(e) => setFecha(e.target.value)}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            Solo cambia las membresías de {concepto === "area" ? "área" : "cuota social"}; la otra
            queda intacta. No se crea ningún pago.
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancelar
          </Button>
          <Button onClick={aplicar} disabled={batch.isPending || !parcelaId || !fecha}>
            Aplicar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
