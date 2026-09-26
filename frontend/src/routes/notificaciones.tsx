import { createFileRoute } from "@tanstack/react-router";

import { Mail, MessageCircle, Send, SkipForward } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EstadoBadge } from "@/components/canyp/EstadoBadge";
import { PageHeader } from "@/components/canyp/AppShell";
import { ExportButton } from "@/components/export";
import { formatFecha } from "@/lib/canyp/utils";
import {
  useSocios,
  useNotificaciones,
  useCreateNotificacion,
  useDashboardAlertas,
} from "@/lib/canyp/queries";
import type { Socio } from "@/lib/canyp/types";

export const Route = createFileRoute("/notificaciones")({
  head: () => ({
    meta: [
      { title: "Notificaciones — CANYP Gestión" },
      {
        name: "description",
        content: "Avisos de vencimiento por WhatsApp e historial de envíos a los socios.",
      },
      { property: "og:title", content: "Notificaciones — CANYP Gestión" },
      {
        property: "og:description",
        content: "Seleccioná socios vencidos o por vencer y enviá el recordatorio.",
      },
    ],
  }),
  component: NotificacionesPage,
});

// ---------------------------------------------------------------------------
// WhatsApp helpers
// ---------------------------------------------------------------------------

interface EnvioWhatsApp {
  socioId: string;
  nombre: string;
  telefono: string;
  mensaje: string;
}

function armarMensaje(
  nombre: string,
  area: string | null,
  predio: string | null,
  vencimiento: string,
): string {
  const detalle = area
    ? `Tu membresía de ${area} en el predio ${predio} vence el ${formatFecha(vencimiento)}`
    : `Tu cuota social vence el ${formatFecha(vencimiento)}`;
  return (
    `Hola ${nombre}, te escribimos del Club Náutico CANYP. ` +
    `${detalle}. ` +
    `Podés regularizarla en administración. ¡Gracias!`
  );
}

async function abrirWhatsApp(telefono: string, mensaje: string) {
  const tel = `549${telefono.replace(/\D/g, "")}`;
  const msg = encodeURIComponent(mensaje);
  const webUrl = `https://wa.me/${tel}?text=${msg}`;
  const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
  if (isTauri) {
    // Dynamic import so the SSR/Nitro build never tries to resolve the Tauri-only module.
    const { open } = await import("@tauri-apps/plugin-shell");
    try {
      const internals = (
        window as unknown as {
          __TAURI_INTERNALS__: { invoke: (cmd: string) => Promise<boolean> };
        }
      ).__TAURI_INTERNALS__;
      // `open()` on Windows shells out to `cmd start`, which shows the native
      // "no app associated" dialog WITHOUT rejecting, so probe the registry
      // handler up front and fall back to WhatsApp Web when it is missing.
      const hasDesktopApp = await internals.invoke("whatsapp_desktop_available");
      if (hasDesktopApp) {
        await open(`whatsapp://send?phone=${tel}&text=${msg}`);
      } else {
        await open(webUrl);
      }
    } catch {
      // Any IPC/open failure falls back to WhatsApp Web.
      await open(webUrl);
    }
  } else {
    // Browser fallback: wa.me opens WhatsApp Web or the desktop app.
    window.open(webUrl, "_blank");
  }
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

function NotificacionesPage() {
  // Las alertas las sirve el backend (membresías vencidas/suspendidas + su estado
  // de socio). No hay ventana de "por vencer" (EST-04): solo la deuda real.
  const { data: alertas = [], isLoading: loadingAlertas } = useDashboardAlertas();
  const { data: socios = [] } = useSocios();
  const { data: notificaciones = [] } = useNotificaciones();
  const createNotificacion = useCreateNotificacion();

  const [sel, setSel] = useState<string[]>([]);
  // Sequential WhatsApp send state
  const [envios, setEnvios] = useState<EnvioWhatsApp[]>([]);
  const [idxActual, setIdxActual] = useState(0);
  const [wa, setWa] = useState<string | null>(null);

  const socioMap = useMemo(() => new Map(socios.map((s: Socio) => [s.id, s])), [socios]);

  const pendientes = useMemo(
    () => [...alertas].sort((a, b) => (a.vencimiento < b.vencimiento ? -1 : 1)),
    [alertas],
  );

  const toggle = (id: string, on: boolean) =>
    setSel((prev) => (on ? [...prev, id] : prev.filter((x) => x !== id)));

  const socioIdsSeleccionados = [
    ...new Set(pendientes.filter((p) => sel.includes(p.id)).map((p) => p.socioId)),
  ];

  // --- WhatsApp sequential send ---
  function iniciarWhatsApp() {
    if (socioIdsSeleccionados.length === 0) {
      toast.error("Seleccioná al menos un socio");
      return;
    }
    const lista: EnvioWhatsApp[] = [];
    for (const p of pendientes.filter((p) => sel.includes(p.id))) {
      const socio = socioMap.get(p.socioId);
      if (!socio || !socio.telefono) continue;
      lista.push({
        socioId: p.socioId,
        nombre: socio.nombre,
        telefono: socio.telefono,
        mensaje: armarMensaje(socio.nombre, p.area, p.predio, p.vencimiento),
      });
    }
    if (lista.length === 0) {
      toast.error("Ninguno de los socios seleccionados tiene teléfono cargado");
      return;
    }
    const primero = lista[0];
    if (!primero) return;

    setEnvios(lista);
    setIdxActual(0);
    setWa(primero.mensaje);
  }

  function abrirWhatsAppActual() {
    const socio = envios[idxActual];
    if (!socio || !wa) return;
    abrirWhatsApp(socio.telefono, wa);
  }

  function siguienteSocio() {
    const next = idxActual + 1;
    if (next >= envios.length) {
      finalizarWhatsApp();
      return;
    }
    const sig = envios[next];
    if (!sig) return;

    setIdxActual(next);
    setWa(sig.mensaje);
  }

  function finalizarWhatsApp() {
    const socioIds = [...new Set(envios.map((e) => e.socioId))];
    createNotificacion.mutate(
      { socioIds, canal: "whatsapp", motivo: "Recordatorio de vencimiento" },
      {
        onSuccess: () => {
          setSel([]);
          setEnvios([]);
          setIdxActual(0);
          setWa(null);
          toast.success(`Notificaciones registradas: ${socioIds.length} socio(s)`);
        },
      },
    );
  }

  function cancelarWhatsApp() {
    setEnvios([]);
    setIdxActual(0);
    setWa(null);
  }

  if (loadingAlertas) {
    return (
      <>
        <PageHeader title="Centro de notificaciones" subtitle="Cargando..." />
        <Card className="p-10 text-center text-sm text-muted-foreground">
          Cargando notificaciones...
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Centro de notificaciones"
        subtitle={`${pendientes.length} membresías con vencimiento vencido o suspendidas`}
        actions={
          <>
            <ExportButton resource="notificaciones" label="notificaciones" />
            <Button variant="outline" onClick={iniciarWhatsApp}>
              <MessageCircle className="mr-2 size-4" /> Enviar por WhatsApp
            </Button>
          </>
        }
      />

      <Card className="overflow-hidden p-0">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-sm font-semibold">A notificar</h2>
          <button
            className="text-xs font-medium text-primary hover:underline"
            onClick={() =>
              setSel(sel.length === pendientes.length ? [] : pendientes.map((p) => p.id))
            }
          >
            {sel.length === pendientes.length ? "Quitar selección" : "Seleccionar todos"}
          </button>
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10" />
              <TableHead>Socio</TableHead>
              <TableHead>Contacto</TableHead>
              <TableHead>Membresía</TableHead>
              <TableHead>Vencimiento</TableHead>
              <TableHead>Estado</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pendientes.map((a) => {
              const socio = socioMap.get(a.socioId);
              return (
                <TableRow key={a.id}>
                  <TableCell>
                    <Checkbox
                      checked={sel.includes(a.id)}
                      onCheckedChange={(c) => toggle(a.id, !!c)}
                    />
                  </TableCell>
                  <TableCell className="font-medium">{socio?.nombre}</TableCell>
                  <TableCell className="text-xs">
                    <p>{socio?.telefono}</p>
                    <p className="text-muted-foreground">{socio?.email}</p>
                  </TableCell>
                  <TableCell className="text-xs">
                    {a.area ? `${a.area} · ${a.predio}` : "Cuota social"}
                  </TableCell>
                  <TableCell className="text-xs tabular-nums">
                    {formatFecha(a.vencimiento)}
                  </TableCell>
                  <TableCell>
                    <EstadoBadge estado={a.estadoSocio} />
                  </TableCell>
                </TableRow>
              );
            })}
            {pendientes.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="py-10 text-center text-sm text-muted-foreground">
                  No hay vencimientos pendientes.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>

      <Card className="mt-6 p-0">
        <div className="border-b border-border px-5 py-3">
          <h2 className="text-sm font-semibold">Historial de notificaciones</h2>
        </div>
        <ul className="divide-y divide-border">
          {notificaciones.map((n) => (
            <li key={n.id} className="flex items-center gap-4 px-5 py-3 text-sm">
              <span className="rounded bg-secondary p-1.5 text-secondary-foreground">
                {n.canal === "email" ? (
                  <Mail className="size-3.5" />
                ) : (
                  <MessageCircle className="size-3.5" />
                )}
              </span>
              <span className="font-medium">{socioMap.get(n.socioId)?.nombre}</span>
              <span className="flex-1 text-xs text-muted-foreground">{n.motivo}</span>
              <span className="text-xs text-muted-foreground tabular-nums">
                {formatFecha(n.fecha)}
              </span>
            </li>
          ))}
        </ul>
      </Card>

      {/* WhatsApp sequential send dialog */}
      <Dialog open={!!wa} onOpenChange={(o) => !o && cancelarWhatsApp()}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              Enviar WhatsApp — socio {idxActual + 1} de {envios.length}
            </DialogTitle>
            <DialogDescription>
              Podés editar el mensaje para <strong>{envios[idxActual]?.nombre}</strong> y luego tocá
              "Abrir WhatsApp".
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={wa ?? ""}
            onChange={(e) => setWa(e.target.value)}
            rows={4}
            className="min-w-0 resize-none whitespace-pre-wrap rounded-lg bg-success/10 p-4 text-sm leading-relaxed focus-visible:ring-0 focus-visible:ring-offset-0"
          />
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={cancelarWhatsApp}>
              Cancelar
            </Button>
            <Button variant="outline" onClick={abrirWhatsAppActual}>
              <Send className="mr-2 size-4" /> Abrir WhatsApp
            </Button>
            {idxActual + 1 < envios.length ? (
              <Button onClick={siguienteSocio}>
                <SkipForward className="mr-2 size-4" /> Siguiente socio
              </Button>
            ) : (
              <Button onClick={finalizarWhatsApp}>Finalizar y registrar ({envios.length})</Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
