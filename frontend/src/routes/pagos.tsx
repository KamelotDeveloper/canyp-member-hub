import { createFileRoute, useNavigate, useSearch } from "@tanstack/react-router";
import { Plus, Printer } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
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
import { ExportButton } from "@/components/export";
import { SocioCombobox } from "@/components/canyp/SocioCombobox";
import { formatARS, formatFecha } from "@/lib/canyp/utils";
import {
  arancelesDisponibles,
  conceptoDeMembresia,
  cuotaAlDia,
  cuotaSocialDe,
  esMembresiaCobrable,
  formatearAvisosCobro,
  hoyLocalISO,
  itemsPorArancel,
  lineaAPagoItem,
  membresiaDeLugar,
  totalEstimado,
  type LugarCobrable,
} from "@/lib/canyp/unidad-helpers";
import {
  useSocios,
  useMembresias,
  useAranceles,
  usePagos,
  useCreatePago,
  useParcelas,
  useUsuarios,
} from "@/lib/canyp/queries";
import type { Arancel, ConceptoCobro, Membresia, Pago, Socio, Usuario } from "@/lib/canyp/types";

/** Fecha de hoy en ISO corto, el default del cobro (PAG-02). */
function hoyIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Concepto de una fila de catálogo; sin `concepto` servido, una fila es de área. */
function conceptoDeArancel(a: Arancel): ConceptoCobro {
  return a.concepto ?? "area";
}

/** Texto auxiliar de una fila: qué precio tiene y quién lo fija. */
function ayudaArancel(a: Arancel): string {
  const concepto = conceptoDeArancel(a);
  if (concepto === "recargo") return "Importe que defina el operador";
  if (concepto === "servicio") return "Precio de catálogo, ajustable por cobro";
  if (concepto === "cuota social") return "Precio de un socio, por socio";
  return "Cuota del área del socio";
}

export const Route = createFileRoute("/pagos")({
  validateSearch: (s: Record<string, unknown>): { nuevo?: string; socioId?: string } => ({
    ...(typeof s["nuevo"] === "string" ? { nuevo: s["nuevo"] } : {}),
    ...(typeof s["socioId"] === "string" ? { socioId: s["socioId"] } : {}),
  }),
  head: () => ({
    meta: [
      { title: "Pagos y comprobantes — CANYP Gestión" },
      {
        name: "description",
        content:
          "Registro de pagos por membresía y emisión de comprobantes con detalle de aranceles.",
      },
      { property: "og:title", content: "Pagos y comprobantes — CANYP Gestión" },
      {
        property: "og:description",
        content: "Cobrá una o varias membresías del socio en un solo comprobante.",
      },
    ],
  }),
  component: PagosPage,
});

function PagosPage() {
  const search = useSearch({ from: "/pagos" });
  const navigate = useNavigate();
  const { data: socios = [] } = useSocios();
  const { data: membresias = [] } = useMembresias();
  const { data: aranceles = [] } = useAranceles();
  const { data: pagos = [] } = usePagos();
  const { data: parcelas = [] } = useParcelas();
  const { data: usuarios = [] } = useUsuarios();
  const createPago = useCreatePago();

  const socioMap = useMemo(() => new Map(socios.map((s: Socio) => [s.id, s])), [socios]);
  const usuarioMap = useMemo(
    () => new Map(usuarios.map((u: Usuario) => [u.id, u.username])),
    [usuarios],
  );

  /** Usuario que cobró el pago; "sin operador" para pagos previos al multi-usuario. */
  const operadorLabel = (createdBy?: string | null) =>
    createdBy ? (usuarioMap.get(createdBy) ?? "sin operador") : "sin operador";

  const [open, setOpen] = useState(false);
  const [socioId, setSocioId] = useState<string>("");
  const [marcas, setMarcas] = useState<Set<string>>(new Set());
  const [ajustes, setAjustes] = useState<Record<string, string>>({});
  const [fecha, setFecha] = useState(hoyIso);
  const [medio, setMedio] = useState("Transferencia");
  const [nota, setNota] = useState("");
  const [comprobante, setComprobante] = useState<Pago | null>(null);
  const [fSocio, setFSocio] = useState("todos");
  const [fArea, setFArea] = useState("todas");
  const [fDesde, setFDesde] = useState("");

  useEffect(() => {
    if (search.nuevo === "1") {
      setOpen(true);
      setSocioId(search.socioId ?? "");
      setMarcas(new Set());
      setAjustes({});
      navigate({ to: "/pagos", search: {}, replace: true });
    }
  }, [search.nuevo, search.socioId, navigate]);

  const membresiasSocio = useMemo(
    () =>
      membresias.filter(
        (m: Membresia) => m.socioId === socioId && m.estado !== "baja" && esMembresiaCobrable(m),
      ),
    [membresias, socioId],
  );

  // Un lugar por unidad del socio, anclado en SU membresía de área (ReQ-004): una
  // balsa y una cabaña del mismo socio son dos lugares con precios propios.
  const lugares = useMemo<LugarCobrable[]>(() => {
    const vistos = new Set<string>();
    const out: LugarCobrable[] = [];
    for (const m of membresiasSocio) {
      if (conceptoDeMembresia(m) !== "area" || !m.area || !m.predio || m.area === "Windsurf") {
        continue;
      }
      const clave = `${m.area}|${m.predio}`;
      if (vistos.has(clave)) continue;
      vistos.add(clave);
      const categoria =
        (m.parcelaId ? parcelas.find((p) => p.id === m.parcelaId)?.categoria : undefined) ?? null;
      const ancla = membresiaDeLugar(membresiasSocio, {
        area: m.area,
        predio: m.predio,
        categoria,
      });
      if (!ancla) continue;
      out.push({ area: m.area, predio: m.predio, categoria, membresiaId: ancla.id });
    }
    return out;
  }, [membresiasSocio, parcelas]);

  // Anclas de las líneas sin lugar: la cuota social del socio y el carrier de
  // recargo. Las de área/servicio salen del lugar de cada fila (ReQ-004).
  const anclas = useMemo(() => {
    const cuota = membresiasSocio.find((m) => conceptoDeMembresia(m) === "cuota social");
    const area = membresiasSocio.find(
      (m) => conceptoDeMembresia(m) === "area" && m.area !== "Windsurf",
    );
    return { cuota: cuota?.id, area: area?.id ?? cuota?.id };
  }, [membresiasSocio]);

  /**
   * ¿El socio debe la cuota? Si ya la tiene al día no se le ofrece ni se le
   * cobra de nuevo (regla del dueño); el servidor resuelve lo mismo sobre el
   * padrón completo, no sobre la lista ya filtrada de este cobro.
   */
  const cuotaImpaga = useMemo(
    () => !cuotaAlDia(cuotaSocialDe(membresias, socioId), hoyLocalISO()),
    [membresias, socioId],
  );

  // Filas del catálogo que este cobro puede tikear (ReQ-001). La cuota social se
  // ofrece SIEMPRE que el arancel exista: el servidor decide el monto y si emite
  // la línea (sin nadie impago no cobra). Windsurf (sin unidad) cobra sólo cuota
  // social (CS-05), como antes de recablear.
  const disponibles = useMemo(() => {
    const soloWindsurf = lugares.length === 0 && membresiasSocio.some((m) => m.area === "Windsurf");
    return arancelesDisponibles(aranceles, lugares).filter((a) => {
      if (conceptoDeArancel(a) === "cuota social") return true;
      if (soloWindsurf) return false;
      return true;
    });
  }, [aranceles, lugares, membresiasSocio]);

  // Aviso ReQ-003: el socio tiene unidad(es) pero ninguna fila de servicio.
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

  // Una línea por arancel tickeado, compuesta contra el catálogo (PAG-01).
  const lineas = useMemo(
    () =>
      itemsPorArancel(aranceles, lugares, marcas, {
        anclas,
        // Cobro por socio: la cuota es ×1 cuando se debe, y nada cuando está
        // al día (el servidor tampoco la emitiría).
        miembrosImpagos: cuotaImpaga ? 1 : 0,
        ajustes: ajustesNum,
      }),
    [aranceles, lugares, marcas, anclas, cuotaImpaga, ajustesNum],
  );

  const total = totalEstimado(lineas);

  const historico = pagos.filter((p: Pago) => {
    if (fSocio !== "todos" && p.socioId !== fSocio) return false;
    if (fDesde && p.fecha < fDesde) return false;
    if (fArea !== "todas") {
      const areas = membresias
        .filter((m: Membresia) => p.membresiaIds.includes(m.id))
        .map((m) => m.area);
      if (!areas.includes(fArea as Membresia["area"])) return false;
    }
    return true;
  });

  function registrar() {
    if (!socioId || lineas.length === 0) {
      toast.error("Elegí un socio y al menos un arancel");
      return;
    }
    createPago.mutate(
      {
        socioId,
        medio,
        fecha,
        ...(nota.trim() ? { nota: nota.trim() } : {}),
        items: lineas.map(lineaAPagoItem),
      },
      {
        onSuccess: (pago) => {
          setOpen(false);
          setComprobante(pago);
          // Total y desglose son los que resolvió el servidor. Nada de "renovadas
          // por 12 meses": qué se renueva depende de los conceptos marcados y
          // cuánto dura lo define el servidor (PAG-01, REN-01).
          toast.success(
            `Pago registrado: ${pago.items.map((i) => i.nombre).join(" + ")} · ${formatARS(pago.total)}`,
          );
          // ReQ-011: si el servidor reemplazó un arancel mal asignado, lo avisa
          // acá. El cobro ya se registró; el toast es warning, no error.
          const aviso = formatearAvisosCobro(pago.avisos);
          if (aviso) toast.warning("Cobro registrado con avisos", { description: aviso });
        },
        onError: () => toast.error("Error al registrar el pago"),
      },
    );
  }

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

  return (
    <>
      <PageHeader
        title="Pagos y comprobantes"
        subtitle="Registrá un cobro y emití el comprobante con el detalle de aranceles."
        actions={
          <>
            <ExportButton resource="pagos" label="pagos" />
            <Button
              onClick={() => {
                setSocioId("");
                setMarcas(new Set());
                setAjustes({});
                setOpen(true);
              }}
            >
              <Plus className="mr-2 size-4" /> Registrar pago
            </Button>
          </>
        }
      />

      <Card className="mb-4 flex flex-wrap items-end gap-3 p-4">
        <div className="min-w-[220px] flex-1">
          <Label className="text-xs">Socio</Label>
          <SocioCombobox
            className="mt-1.5"
            value={fSocio}
            onChange={setFSocio}
            socios={socios}
            allowEmpty
            emptyLabel="Todos los socios"
            placeholder="Buscar socio..."
          />
        </div>
        <div className="w-[170px]">
          <Label className="text-xs">Área</Label>
          <Select value={fArea} onValueChange={setFArea}>
            <SelectTrigger className="mt-1.5">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="todas">Todas</SelectItem>
              <SelectItem value="Balseros">Balseros</SelectItem>
              <SelectItem value="Cabañeros">Cabañeros</SelectItem>
              <SelectItem value="Guardería">Guardería</SelectItem>
              <SelectItem value="Windsurf">Windsurf</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="w-[170px]">
          <Label className="text-xs">Desde</Label>
          <Input
            type="date"
            className="mt-1.5"
            value={fDesde}
            onChange={(e) => setFDesde(e.target.value)}
          />
        </div>
      </Card>

      <Card className="overflow-hidden p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Comprobante</TableHead>
              <TableHead>Fecha</TableHead>
              <TableHead>Socio</TableHead>
              <TableHead>Detalle</TableHead>
              <TableHead>Medio</TableHead>
              <TableHead>Operador</TableHead>
              <TableHead className="text-right">Total</TableHead>
              <TableHead className="text-right">Acciones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {historico.map((p) => (
              <TableRow key={p.id}>
                <TableCell className="font-mono text-xs">{p.numero}</TableCell>
                <TableCell className="text-xs tabular-nums">{formatFecha(p.fecha)}</TableCell>
                <TableCell className="font-medium">{socioMap.get(p.socioId)?.nombre}</TableCell>
                <TableCell className="max-w-[280px] truncate text-xs text-muted-foreground">
                  {p.items.map((i) => i.nombre).join(" + ")}
                </TableCell>
                <TableCell className="text-xs">{p.medio}</TableCell>
                <TableCell className="text-xs">{operadorLabel(p.createdBy)}</TableCell>
                <TableCell className="text-right font-semibold tabular-nums">
                  {formatARS(p.total)}
                </TableCell>
                <TableCell className="text-right">
                  <Button size="sm" variant="outline" onClick={() => setComprobante(p)}>
                    Ver comprobante
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {historico.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="py-10 text-center text-sm text-muted-foreground">
                  No hay comprobantes con estos filtros.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Registrar pago</DialogTitle>
            <DialogDescription>
              Elegí el socio y las membresías a cobrar: los aranceles se cargan solos.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div>
              <Label>Socio</Label>
              <SocioCombobox
                className="mt-1.5"
                placeholder="Seleccionar socio"
                value={socioId}
                onChange={(v) => {
                  setSocioId(v);
                  setMarcas(new Set());
                  setAjustes({});
                }}
                socios={socios}
              />
            </div>

            {socioId && disponibles.length > 0 && (
              <div>
                <Label>Aranceles a cobrar</Label>
                <ul className="mt-1.5 space-y-2">
                  {disponibles.map((a) => {
                    const concepto = conceptoDeArancel(a);
                    const editable = concepto === "servicio" || concepto === "recargo";
                    return (
                      <li
                        key={a.id}
                        className="flex items-center gap-3 rounded-md border border-border p-3"
                      >
                        <Checkbox
                          checked={marcas.has(a.id)}
                          onCheckedChange={() => alternar(a.id)}
                        />
                        <div className="flex-1">
                          <p className="text-sm font-medium">{a.nombre}</p>
                          <p className="text-xs text-muted-foreground">{ayudaArancel(a)}</p>
                        </div>
                        {editable && marcas.has(a.id) && (
                          <Input
                            type="number"
                            min={0}
                            step={100}
                            className="w-32 shrink-0"
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
                {lugares.length > 0 && !hayServicio && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Sin arancel de servicio para esta área.
                  </p>
                )}
              </div>
            )}

            {socioId && disponibles.length === 0 && (
              <p className="text-xs text-muted-foreground">
                El socio no tiene membresías activas para cobrar.
              </p>
            )}

            {lineas.length > 0 && (
              <div className="rounded-md bg-secondary p-3">
                <p className="text-xs font-semibold tracking-wide uppercase">Ítems a cobrar</p>
                <ul className="mt-2 space-y-1 text-sm">
                  {lineas.map((l) => (
                    <li key={l.arancelId} className="flex justify-between">
                      <span>
                        {l.arancelNombre}
                        {l.factor > 1 && (
                          <span className="text-muted-foreground"> ×{l.factor}</span>
                        )}
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
              <Label htmlFor="pago-fecha">Fecha del cobro</Label>
              <Input
                id="pago-fecha"
                type="date"
                className="mt-1.5"
                value={fecha}
                onChange={(e) => setFecha(e.target.value)}
              />
            </div>

            <div>
              <Label htmlFor="pago-nota">Nota (opcional)</Label>
              <Input
                id="pago-nota"
                value={nota}
                onChange={(e) => setNota(e.target.value)}
                placeholder="Texto que se muestra en el comprobante"
                className="mt-1.5"
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancelar
            </Button>
            <Button onClick={registrar} disabled={createPago.isPending || lineas.length === 0}>
              Registrar y emitir comprobante
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!comprobante} onOpenChange={(o) => !o && setComprobante(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Comprobante emitido</DialogTitle>
            <DialogDescription>Revisá el detalle y usá Imprimir para emitirlo.</DialogDescription>
          </DialogHeader>
          {comprobante && (
            <ComprobanteView comprobante={comprobante} socioMap={socioMap} aranceles={aranceles} />
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setComprobante(null)}>
              Cerrar
            </Button>
            <Button
              onClick={() => {
                window.print();
                toast.success("Comprobante enviado a imprimir");
              }}
            >
              <Printer className="mr-2 size-4" /> Imprimir
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {comprobante &&
        createPortal(
          <div className="print-root">
            <ComprobanteView comprobante={comprobante} socioMap={socioMap} aranceles={aranceles} />
          </div>,
          document.body,
        )}
    </>
  );
}

/** Comprobante impreso: detalle de ítems + total. Reutilizado por el Dialog y el print-root. */
function ComprobanteView({
  comprobante,
  socioMap,
  aranceles,
}: {
  comprobante: Pago;
  socioMap: Map<string, Socio>;
  /** Catálogo vigente: sirve para marcar un nombre congelado que ya no existe. */
  aranceles: Arancel[];
}) {
  return (
    <div className="print-area rounded-lg border border-border bg-card p-5">
      <div className="flex items-start justify-between border-b border-border pb-3">
        <div className="flex items-center gap-2">
          <img
            src="/CANYP_Almafuerte_logo.svg?v=3"
            alt="CANYP logo"
            className="size-9 object-contain"
          />
          <div>
            <p className="text-sm font-bold">Club Náutico CANYP</p>
            <p className="text-[11px] text-muted-foreground">Comprobante de pago</p>
          </div>
        </div>
        <div className="text-right text-[11px]">
          <p className="font-mono font-semibold">{comprobante.numero}</p>
          <p className="text-muted-foreground">{formatFecha(comprobante.fecha)}</p>
        </div>
      </div>
      <div className="py-3 text-xs">
        <p className="text-muted-foreground">Socio</p>
        <p className="text-sm font-semibold">{socioMap.get(comprobante.socioId)?.nombre}</p>
        <p className="text-muted-foreground">DNI {socioMap.get(comprobante.socioId)?.dni}</p>
      </div>
      <table className="w-full text-sm">
        <tbody>
          {comprobante.items.map((i) => {
            // ReQ-016: el nombre viaja congelado en el ítem y NO se reescribe. Si
            // el catálogo ya no lo usa (fila renombrada o dada de baja), se
            // muestra tal cual y se marca como histórico para que sea legible.
            const vigente = aranceles.find((a) => a.id === i.arancelId);
            const historico = !vigente || vigente.nombre !== i.nombre;
            return (
              <tr key={i.arancelId} className="border-t border-border">
                <td className="py-2">
                  {i.nombre}
                  {historico && (
                    <Badge
                      variant="secondary"
                      className="ml-2 align-middle text-[10px]"
                      title="Nombre congelado en el comprobante; el catálogo ya no lo usa."
                    >
                      Histórico
                    </Badge>
                  )}
                </td>
                <td className="py-2 text-right tabular-nums">{formatARS(i.monto)}</td>
              </tr>
            );
          })}
          <tr className="border-t-2 border-foreground/20">
            <td className="py-2 font-bold">Total</td>
            <td className="py-2 text-right font-bold tabular-nums">
              {formatARS(comprobante.total)}
            </td>
          </tr>
        </tbody>
      </table>
      {comprobante.nota && (
        <p className="mt-3 rounded-md bg-secondary p-2 text-xs whitespace-pre-wrap">
          {comprobante.nota}
        </p>
      )}
      <p className="mt-3 text-[11px] text-muted-foreground">Abonado con {comprobante.medio}</p>
    </div>
  );
}
