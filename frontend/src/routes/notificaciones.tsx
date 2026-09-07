import { createFileRoute } from "@tanstack/react-router";
import { Mail, MessageCircle } from "lucide-react";
import { useState } from "react";
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
import { diasRestantes, estadoVisual, formatFecha } from "@/lib/canyp/utils";
import {
  useMembresias,
  useSocios,
  useNotificaciones,
  useCreateNotificacion,
} from "@/lib/canyp/queries";
import type { Socio } from "@/lib/canyp/types";

export const Route = createFileRoute("/notificaciones")({
  head: () => ({
    meta: [
      { title: "Notificaciones — CANYP Gestión" },
      {
        name: "description",
        content: "Avisos de vencimiento por email o WhatsApp e historial de envíos a los socios.",
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

function NotificacionesPage() {
  const { data: membresias = [], isLoading: loadingMembresias } = useMembresias();
  const { data: socios = [] } = useSocios();
  const { data: notificaciones = [] } = useNotificaciones();
  const createNotificacion = useCreateNotificacion();

  const [sel, setSel] = useState<string[]>([]);
  const [wa, setWa] = useState<string | null>(null);

  const socioMap = new Map(socios.map((s: Socio) => [s.id, s]));

  const pendientes = membresias
    .map((m) => ({ m, e: estadoVisual(m) }))
    .filter((x) => x.e === "vencida" || x.e === "por_vencer")
    .sort((a, b) => diasRestantes(a.m.vencimiento) - diasRestantes(b.m.vencimiento));

  const toggle = (id: string, on: boolean) =>
    setSel((prev) => (on ? [...prev, id] : prev.filter((x) => x !== id)));

  const socioIdsSeleccionados = [
    ...new Set(pendientes.filter((p) => sel.includes(p.m.id)).map((p) => p.m.socioId)),
  ];

  function enviarEmail() {
    if (socioIdsSeleccionados.length === 0) {
      toast.error("Seleccioná al menos un socio");
      return;
    }
    createNotificacion.mutate(
      { socioIds: socioIdsSeleccionados, canal: "email", motivo: "Recordatorio de vencimiento" },
      {
        onSuccess: () => {
          setSel([]);
          toast.success(`Recordatorio enviado a ${socioIdsSeleccionados.length} socio(s)`);
        },
        onError: () => toast.error("Error al enviar notificaciones"),
      },
    );
  }

  function generarWhatsapp() {
    if (socioIdsSeleccionados.length === 0) {
      toast.error("Seleccioná al menos un socio");
      return;
    }
    const primero = pendientes.find((p) => sel.includes(p.m.id))!;
    const socio = socioMap.get(primero.m.socioId);
    setWa(
      `Hola ${socio?.nombre}, te escribimos del Club Náutico CANYP. Tu membresía de ${primero.m.area} en el predio ${primero.m.predio} vence el ${formatFecha(primero.m.vencimiento)}. Podés regularizarla en administración. ¡Gracias!`,
    );
  }

  if (loadingMembresias) {
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
        subtitle={`${pendientes.length} membresías vencidas o por vencer en los próximos 30 días`}
        actions={
          <>
            <ExportButton resource="notificaciones" label="notificaciones" />
            <Button variant="outline" onClick={generarWhatsapp}>
              <MessageCircle className="mr-2 size-4" /> Enviar por WhatsApp
            </Button>
            <Button onClick={enviarEmail} disabled={createNotificacion.isPending}>
              <Mail className="mr-2 size-4" /> Enviar recordatorio por email
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
              setSel(sel.length === pendientes.length ? [] : pendientes.map((p) => p.m.id))
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
            {pendientes.map(({ m, e }) => {
              const socio = socioMap.get(m.socioId);
              return (
                <TableRow key={m.id}>
                  <TableCell>
                    <Checkbox
                      checked={sel.includes(m.id)}
                      onCheckedChange={(c) => toggle(m.id, !!c)}
                    />
                  </TableCell>
                  <TableCell className="font-medium">{socio?.nombre}</TableCell>
                  <TableCell className="text-xs">
                    <p>{socio?.telefono}</p>
                    <p className="text-muted-foreground">{socio?.email}</p>
                  </TableCell>
                  <TableCell className="text-xs">
                    {m.area} · {m.predio}
                  </TableCell>
                  <TableCell className="text-xs tabular-nums">
                    {formatFecha(m.vencimiento)}
                  </TableCell>
                  <TableCell>
                    <EstadoBadge estado={e} />
                  </TableCell>
                </TableRow>
              );
            })}
            {pendientes.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="py-10 text-center text-sm text-muted-foreground">
                  No hay vencimientos pendientes. 🎉
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

      <Dialog open={!!wa} onOpenChange={(o) => !o && setWa(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Mensaje de WhatsApp listo para enviar</DialogTitle>
            <DialogDescription>
              Se generó un mensaje por cada socio seleccionado. Este es el primero.
            </DialogDescription>
          </DialogHeader>
          <p className="rounded-lg bg-success/10 p-4 text-sm leading-relaxed">{wa}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setWa(null)}>
              Cerrar
            </Button>
            <Button
              onClick={() => {
                createNotificacion.mutate(
                  {
                    socioIds: socioIdsSeleccionados,
                    canal: "whatsapp",
                    motivo: "Recordatorio de vencimiento",
                  },
                  {
                    onSuccess: () => {
                      setSel([]);
                      setWa(null);
                      toast.success("Mensajes generados y registrados en el historial");
                    },
                  },
                );
              }}
            >
              Marcar como enviados
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
