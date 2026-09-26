import { createFileRoute, useNavigate, useSearch } from "@tanstack/react-router";
import { Plus, Printer } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { toast } from "sonner";
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
  conceptosDisponibles,
  conceptoDeMembresia,
  esMembresiaCobrable,
  itemsPorConcepto,
  lineaAPagoItem,
  totalEstimado,
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
import type { Membresia, Pago, Socio, Usuario, ConceptoCobro } from "@/lib/canyp/types";

/** Fecha de hoy en ISO corto, el default del cobro (PAG-02). */
function hoyIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Etiqueta de un concepto de cobro, tal como la nombra el dominio. */
function labelConcepto(c: ConceptoCobro): string {
  if (c === "cuota social") return "Cuota social";
  if (c === "recargo") return "Recargo";
  if (c === "servicio") return "Servicio";
  return "Cuota de área";
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
  const [marcas, setMarcas] = useState<ConceptoCobro[]>([]);
  const [recargo, setRecargo] = useState("");
  const [servicio, setServicio] = useState("");
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
      setMarcas([]);
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

  // Qué se puede cobrar a este socio (CS-05: Windsurf sólo cuota social).
  const disponibles = useMemo(
    () => conceptosDisponibles(membresiasSocio, aranceles),
    [membresiasSocio, aranceles],
  );

  // Los anclos: una membresía por concepto, elegidas por el concepto que
  // SERVIRON, no por adivinar desde el área.
  const anclas = useMemo(() => {
    const cuota = membresiasSocio.find((m) => conceptoDeMembresia(m) === "cuota social");
    const area = membresiasSocio.find(
      (m) => conceptoDeMembresia(m) === "area" && m.area !== "Windsurf",
    );
    return { cuota: cuota?.id, area: cuota?.id ?? area?.id };
  }, [membresiasSocio]);

  // Una sola línea por concepto, compuesta contra el catálogo (PAG-01).
  const lineas = useMemo(
    () =>
      itemsPorConcepto(marcas, {
        anclas,
        miembros: membresiasSocio.filter((m) => conceptoDeMembresia(m) === "area").length || 1,
        aranceles,
        ...(anclas.area
          ? (() => {
              const m = membresiasSocio.find((x) => x.id === anclas.area);
              const parcela = m?.parcelaId ? parcelas.find((p) => p.id === m.parcelaId) : undefined;
              return m?.area && m.predio
                ? {
                    lugar: {
                      area: m.area,
                      predio: m.predio,
                      categoria: parcela?.categoria ?? null,
                    },
                  }
                : {};
            })()
          : {}),
        ...(recargo ? { recargo: Number(recargo) } : {}),
        ...(servicio ? { servicio: Number(servicio) } : {}),
      }),
    [marcas, anclas, membresiasSocio, parcelas, aranceles, recargo, servicio],
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
      toast.error("Elegí un socio y al menos un concepto");
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
        },
        onError: () => toast.error("Error al registrar el pago"),
      },
    );
  }

  function alternar(concepto: ConceptoCobro) {
    setMarcas((prev) =>
      prev.includes(concepto) ? prev.filter((c) => c !== concepto) : [...prev, concepto],
    );
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
                setMarcas([]);
                setRecargo("");
                setServicio("");
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
        <DialogContent className="sm:max-w-lg">
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
                  setMarcas([]);
                  setRecargo("");
                  setServicio("");
                }}
                socios={socios}
              />
            </div>

            {socioId && disponibles.length > 0 && (
              <div>
                <Label>Conceptos a cobrar</Label>
                <ul className="mt-1.5 space-y-2">
                  {disponibles.map((c) => (
                    <li
                      key={c}
                      className="flex items-center gap-3 rounded-md border border-border p-3"
                    >
                      <Checkbox checked={marcas.includes(c)} onCheckedChange={() => alternar(c)} />
                      <div className="flex-1">
                        <p className="text-sm font-medium">{labelConcepto(c)}</p>
                        <p className="text-xs text-muted-foreground">
                          {c === "recargo"
                            ? "Importe que defina el operador"
                            : c === "servicio"
                              ? "Precio de catálogo, ajustable por cobro"
                              : c === "cuota social"
                                ? "Precio de un socio, por socio"
                                : "Cuota del área del socio"}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
                {marcas.includes("servicio") && (
                  <div className="mt-2">
                    <Label htmlFor="pago-servicio" className="text-xs">
                      Importe del servicio
                    </Label>
                    <Input
                      id="pago-servicio"
                      type="number"
                      min={0}
                      step={100}
                      className="mt-1.5"
                      value={servicio}
                      onChange={(e) => setServicio(e.target.value)}
                    />
                  </div>
                )}
                {marcas.includes("recargo") && (
                  <div className="mt-2">
                    <Label htmlFor="pago-recargo" className="text-xs">
                      Importe del recargo
                    </Label>
                    <Input
                      id="pago-recargo"
                      type="number"
                      min={0}
                      step={100}
                      className="mt-1.5"
                      value={recargo}
                      onChange={(e) => setRecargo(e.target.value)}
                      placeholder="0"
                    />
                  </div>
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
                    <li key={l.concepto} className="flex justify-between">
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
          {comprobante && <ComprobanteView comprobante={comprobante} socioMap={socioMap} />}
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
            <ComprobanteView comprobante={comprobante} socioMap={socioMap} />
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
}: {
  comprobante: Pago;
  socioMap: Map<string, Socio>;
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
          {comprobante.items.map((i) => (
            <tr key={i.arancelId} className="border-t border-border">
              <td className="py-2">{i.nombre}</td>
              <td className="py-2 text-right tabular-nums">{formatARS(i.monto)}</td>
            </tr>
          ))}
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
