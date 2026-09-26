import { useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Printer } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { CarnetCard } from "./CarnetCard";
import { useMembresias } from "@/lib/canyp/queries";
import { useFotos } from "@/lib/canyp/fotos";
import { agruparPorHojas, areasDeSocio } from "@/lib/canyp/carnets";
import type { Area, Socio } from "@/lib/canyp/types";

const CARDEN_POR_HOJA = 8;

/**
 * Hard cap for a single print job. Windows WebView2 rasterizes the whole
 * document when opening its native print preview: beyond ~7 A4 sheets the
 * preview stays blank ("cargando" forever). Keeping one job under 50 carnets
 * guarantees the native preview can render it.
 */
const LIMITE_IMPRESION = 50;

/**
 * Print sheet for carnets. Mirrors pagos.tsx: the same pages render into a
 * visible Dialog (on-screen preview) AND into a `.print-root` portal at
 * <body> that only appears on print. Multi-page pagination (8 cards per A4)
 * is done by the CSS `.print-page`/`@page` rules — no JS cap on selection.
 *
 * When many socios are selected (hundreds), mounting the full `.print-root`
 * forever would rasterize dozens of A4 sheets inside the on-screen preview.
 * Instead the print portal is mounted ONLY while printing: a single
 * `imprentaAbierta` flag holds all sheets in memory, is set right before
 * `window.print()`, and WebView2's print engine picks it up on the next
 * frame. After onClose it is cleared so the portal disappears.
 *
 * Selections beyond LIMITE_IMPRESION cannot be printed in one job (the native
 * Windows preview blanks out): the button is disabled and the dialog explains
 * how to split the batch.
 */
export function CarnetPrint({ socios, onClose }: { socios: Socio[]; onClose: () => void }) {
  const { data: membresias = [] } = useMembresias();
  const fotoIds = useMemo(() => socios.filter((s) => s.tieneFoto).map((s) => s.id), [socios]);
  const { urls } = useFotos(fotoIds);
  const [imprentaAbierta, setImprentaAbierta] = useState(false);

  const excedeLimite = socios.length > LIMITE_IMPRESION;
  const hojas = useMemo(() => agruparPorHojas(socios, CARDEN_POR_HOJA), [socios]);
  const areasBySocio = useMemo(() => {
    const map: Record<string, Area[]> = {};
    for (const s of socios) map[s.id] = areasDeSocio(membresias, s.id);
    return map;
  }, [membresias, socios]);

  const pages = useMemo(
    () =>
      hojas.map((batch, i) => (
        <div
          key={i}
          className="print-page grid grid-cols-2 gap-x-[5mm] gap-y-[6mm] rounded-md bg-muted/40 p-[5mm]"
        >
          {batch.map((s) => (
            <CarnetCard
              key={s.id}
              socio={s}
              areas={areasBySocio[s.id] ?? []}
              fotoUrl={urls[s.id]}
            />
          ))}
        </div>
      )),
    [hojas, areasBySocio, urls],
  );

  // On-screen preview shows only the FIRST sheet so hundreds of carnets do
  // not freeze the browser (every card carries the SVG watermark + tiled
  // pattern work). The print portal below still carries every sheet, so
  // printing outputs the full selection.
  const preview = hojas[0] ? [hojas[0]] : [];

  const totalText = `${socios.length} carnet${socios.length === 1 ? "" : "s"} · ${hojas.length} hoja${hojas.length === 1 ? "" : "s"} A4`;

  function imprimir() {
    setImprentaAbierta(true);
    // Let React commit the portal before the print engine snapshots the DOM.
    window.setTimeout(() => window.print(), 50);
  }

  return (
    <>
      <Dialog open onOpenChange={(o) => !o && onClose()}>
        <DialogContent className="w-[780px] max-w-[94vw]">
          <DialogHeader>
            <DialogTitle>Imprimir carnets</DialogTitle>
            <DialogDescription>{totalText}</DialogDescription>
          </DialogHeader>
          <div className="max-h-[62vh] space-y-4 overflow-y-auto rounded-md">
            {preview.map((batch, i) => (
              <div
                key={i}
                className="print-page grid grid-cols-2 gap-x-[5mm] gap-y-[6mm] rounded-md bg-muted/40 p-[5mm]"
              >
                {batch.map((s) => (
                  <CarnetCard
                    key={s.id}
                    socio={s}
                    areas={areasBySocio[s.id] ?? []}
                    fotoUrl={urls[s.id]}
                  />
                ))}
              </div>
            ))}
            {hojas.length > 1 && (
              <p className="rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground">
                Vista previa: primera hoja. Al imprimir se generan las {hojas.length} hojas completas.
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={onClose}>
              Cerrar
            </Button>
            <Button onClick={imprimir}>
              <Printer className="mr-2 size-4" /> Imprimir
            </Button>
          </DialogFooter>
          {excedeLimite && (
            <p className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
              Se seleccionaron {socios.length} carnets ({hojas.length} hojas A4). Windows no puede
              generar el preview de impresión para un documento tan grande. Imprimí por tandas:
              filtrá por área o estado, o seleccioná hasta {LIMITE_IMPRESION} carnets por vez.
            </p>
          )}
        </DialogContent>
      </Dialog>
      {imprentaAbierta &&
        createPortal(<div className="print-root">{pages}</div>, document.body)}
    </>
  );
}
