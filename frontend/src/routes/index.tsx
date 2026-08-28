import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowRight,
  BellRing,
  CalendarClock,
  CreditCard,
  Sailboat,
  Home,
  Warehouse,
  Wind,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EstadoBadge } from "@/components/canyp/EstadoBadge";
import { PageHeader } from "@/components/canyp/AppShell";
import { diasRestantes, estadoVisual, formatFecha } from "@/lib/canyp/utils";
import { useSocios, useMembresias, usePagos } from "@/lib/canyp/queries";
import type { Area, Membresia, Socio } from "@/lib/canyp/types";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Dashboard — CANYP Gestión" },
      {
        name: "description",
        content:
          "Panel diario del club: socios activos por área, membresías vencidas y por vencer, y accesos rápidos.",
      },
      { property: "og:title", content: "Dashboard — CANYP Gestión" },
      {
        property: "og:description",
        content: "Estado del club de un vistazo: altas, vencimientos y cobros del día.",
      },
    ],
  }),
  component: Dashboard,
});

const areaIcon: Record<Area, typeof Sailboat> = {
  Balseros: Sailboat,
  Cabañeros: Home,
  Guardería: Warehouse,
  Windsurf: Wind,
};

const areaPredio: Record<Area, string> = {
  Balseros: "Embalse",
  Cabañeros: "Almafuerte",
  Guardería: "Almafuerte",
  Windsurf: "Almafuerte",
};

function Dashboard() {
  const { data: membresias = [], isLoading: loadingMembresias } = useMembresias();
  const { data: socios = [] } = useSocios();
  const { data: pagos = [] } = usePagos();
  const navigate = useNavigate();

  const socioMap = new Map(socios.map((s: Socio) => [s.id, s]));

  const conEstado = membresias.map((m: Membresia) => ({ m, e: estadoVisual(m) }));
  const vencidas = conEstado.filter((x) => x.e === "vencida");
  const porVencer = conEstado
    .filter((x) => x.e === "por_vencer")
    .sort((a, b) => diasRestantes(a.m.vencimiento) - diasRestantes(b.m.vencimiento));

  const areas: Area[] = ["Balseros", "Cabañeros", "Guardería", "Windsurf"];

  if (loadingMembresias) {
    return (
      <>
        <PageHeader title="Dashboard" subtitle="Cargando..." />
        <Card className="p-10 text-center text-sm text-muted-foreground">
          Cargando dashboard...
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle={`${socios.length} socios · ${membresias.length} membresías en Embalse y Almafuerte`}
        actions={
          <>
            <Button variant="outline" onClick={() => navigate({ to: "/socios" })}>
              Buscar socio
            </Button>
            <Button onClick={() => navigate({ to: "/pagos", search: { nuevo: "1" } })}>
              <CreditCard className="mr-2 size-4" /> Registrar pago
            </Button>
          </>
        }
      />

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {areas.map((area) => {
          const Icon = areaIcon[area];
          const activas = conEstado.filter(
            (x) => x.m.area === area && (x.e === "activa" || x.e === "por_vencer"),
          ).length;
          const alertas = conEstado.filter(
            (x) => x.m.area === area && (x.e === "vencida" || x.e === "por_vencer"),
          ).length;
          return (
            <Link key={area} to="/membresias" search={{ area }}>
              <Card className="h-full p-5 transition-shadow hover:shadow-md">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                      {area}
                    </p>
                    <p className="mt-2 text-3xl font-bold tabular-nums">{activas}</p>
                    <p className="text-xs text-muted-foreground">socios activos</p>
                  </div>
                  <span className="rounded-md bg-accent p-2 text-accent-foreground">
                    <Icon className="size-5" />
                  </span>
                </div>
                <p className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
                  <span>{areaPredio[area]}</span>
                  {alertas > 0 && (
                    <span className="font-semibold text-danger">{alertas} a revisar</span>
                  )}
                </p>
              </Card>
            </Link>
          );
        })}
      </section>

      <section className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card className="border-danger/30 bg-danger/5 p-5 lg:col-span-1">
          <div className="flex items-center gap-3">
            <span className="rounded-md bg-danger/15 p-2 text-danger">
              <AlertTriangle className="size-5" />
            </span>
            <div>
              <p className="text-3xl leading-none font-bold text-danger tabular-nums">
                {vencidas.length}
              </p>
              <p className="text-sm font-medium">Membresías vencidas</p>
            </div>
          </div>
          <div className="mt-4 flex items-center gap-3 border-t border-danger/20 pt-4">
            <span className="rounded-md bg-warning/20 p-2 text-warning-foreground">
              <CalendarClock className="size-5" />
            </span>
            <div>
              <p className="text-3xl leading-none font-bold tabular-nums">{porVencer.length}</p>
              <p className="text-sm font-medium">Vencen en los próximos 30 días</p>
            </div>
          </div>
          <Button
            className="mt-5 w-full"
            variant="secondary"
            onClick={() => navigate({ to: "/notificaciones" })}
          >
            <BellRing className="mr-2 size-4" /> Notificar a los socios
          </Button>
        </Card>

        <Card className="p-0 lg:col-span-2">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <h2 className="text-sm font-semibold">Atención inmediata</h2>
            <Link
              to="/membresias"
              search={{ filtro: "alertas" }}
              className="flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              Ver todas <ArrowRight className="size-3" />
            </Link>
          </div>
          <ul className="divide-y divide-border">
            {[...vencidas, ...porVencer].slice(0, 6).map(({ m, e }) => {
              const socio = socioMap.get(m.socioId);
              const d = diasRestantes(m.vencimiento);
              return (
                <li key={m.id} className="flex items-center gap-4 px-5 py-3">
                  <div className="min-w-0 flex-1">
                    <Link
                      to="/socios/$socioId"
                      params={{ socioId: m.socioId }}
                      className="truncate text-sm font-semibold hover:underline"
                    >
                      {socio?.nombre}
                    </Link>
                    <p className="truncate text-xs text-muted-foreground">
                      {m.area} · {m.predio} · vence {formatFecha(m.vencimiento)}
                    </p>
                  </div>
                  <span className="hidden text-xs text-muted-foreground sm:block">
                    {d < 0 ? `hace ${Math.abs(d)} días` : `en ${d} días`}
                  </span>
                  <EstadoBadge estado={e} />
                  <Button
                    size="sm"
                    onClick={() =>
                      navigate({ to: "/pagos", search: { nuevo: "1", socioId: m.socioId } })
                    }
                  >
                    Cobrar
                  </Button>
                </li>
              );
            })}
          </ul>
        </Card>
      </section>

      <section className="mt-6">
        <Card className="p-0">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <h2 className="text-sm font-semibold">Últimos comprobantes emitidos</h2>
            <Link
              to="/pagos"
              className="flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              Ver pagos <ArrowRight className="size-3" />
            </Link>
          </div>
          <ul className="divide-y divide-border">
            {pagos.slice(0, 4).map((p) => (
              <li key={p.id} className="flex items-center justify-between px-5 py-3 text-sm">
                <span className="font-mono text-xs text-muted-foreground">{p.numero}</span>
                <span className="flex-1 px-4 truncate">{socioMap.get(p.socioId)?.nombre}</span>
                <span className="hidden text-xs text-muted-foreground sm:block">
                  {formatFecha(p.fecha)}
                </span>
                <span className="ml-4 font-semibold tabular-nums">
                  $ {p.total.toLocaleString("es-AR")}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      </section>
    </>
  );
}
