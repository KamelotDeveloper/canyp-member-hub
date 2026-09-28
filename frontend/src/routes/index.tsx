import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowRight,
  BellRing,
  CreditCard,
  Home,
  Sailboat,
  Users,
  Warehouse,
  Wind,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EstadoBadge } from "@/components/canyp/EstadoBadge";
import { PageHeader } from "@/components/canyp/AppShell";
import { formatFecha } from "@/lib/canyp/utils";
import { useSocios, usePagos, useDashboardStats, useDashboardAlertas } from "@/lib/canyp/queries";
import type { Area, EstadoSocio, Socio } from "@/lib/canyp/types";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Dashboard — CANYP Gestión" },
      {
        name: "description",
        content:
          "Panel diario del club: los 4 estados de socio servidos por el backend, alertas de vencimiento y accesos rápidos.",
      },
      { property: "og:title", content: "Dashboard — CANYP Gestión" },
      {
        property: "og:description",
        content: "Estado del club de un vistazo: estados de socios y cobros del día.",
      },
    ],
  }),
  component: Dashboard,
});

/** Los 4 estados de socio, en el orden de severidad que sirve el backend (EST-01). */
const ESTADOS: EstadoSocio[] = [
  "Inactivo — revisar",
  "Socio activo — revisar",
  "Socio activo",
  "Solo cuota social",
];

/** Las 4 áreas de membresía, con su ícono y el predio que les corresponde. */
const AREAS: Area[] = ["Balseros", "Cabañeros", "Guardería", "Windsurf"];

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
  const { data: socios = [] } = useSocios();
  const { data: stats } = useDashboardStats();
  const { data: alertas = [] } = useDashboardAlertas();
  const { data: pagos = [] } = usePagos();
  const navigate = useNavigate();

  const socioMap = new Map(socios.map((s: Socio) => [s.id, s]));

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle={`${socios.length} socios · ${stats?.totalMembresias ?? 0} membresías en Embalse y Almafuerte`}
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

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <Link to="/socios">
          <Card className="h-full p-5 transition-shadow hover:shadow-md">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                  Socios total
                </p>
                <p className="mt-2 text-3xl font-bold tabular-nums">{socios.length}</p>
                <p className="text-xs text-muted-foreground">padrón completo</p>
              </div>
              <span className="rounded-md bg-accent p-2 text-accent-foreground">
                <Users className="size-5" />
              </span>
            </div>
            <p className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
              <span>Ir al padrón</span>
              <ArrowRight className="size-3" />
            </p>
          </Card>
        </Link>

        {ESTADOS.map((e) => (
          <Card key={e} className="h-full p-5">
            <EstadoBadge estado={e} />
            <p className="mt-3 text-3xl font-bold tabular-nums">{stats?.estados[e] ?? 0}</p>
            <p className="text-xs text-muted-foreground">socios</p>
          </Card>
        ))}
      </section>

      <section className="mt-6">
        <h2 className="mb-3 text-sm font-semibold">Membresías por área</h2>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {AREAS.map((area) => {
            const Icon = areaIcon[area];
            const total = stats?.countsByArea[area] ?? 0;
            const aRevisar = alertas.filter((a) => a.area === area).length;
            return (
              <Link key={area} to="/membresias" search={{ area }}>
                <Card className="h-full p-5 transition-shadow hover:shadow-md">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                        {area}
                      </p>
                      <p className="mt-2 text-3xl font-bold tabular-nums">{total}</p>
                      <p className="text-xs text-muted-foreground">membresías</p>
                    </div>
                    <span className="rounded-md bg-accent p-2 text-accent-foreground">
                      <Icon className="size-5" />
                    </span>
                  </div>
                  <p className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
                    <span>{areaPredio[area]}</span>
                    {aRevisar > 0 && (
                      <span className="font-semibold text-danger">{aRevisar} a revisar</span>
                    )}
                  </p>
                </Card>
              </Link>
            );
          })}
        </div>
      </section>

      <section className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card className="p-0 lg:col-span-2">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <h2 className="text-sm font-semibold">Atención inmediata</h2>
            <Link
              to="/notificaciones"
              className="flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              Ver todas <ArrowRight className="size-3" />
            </Link>
          </div>
          <ul className="divide-y divide-border">
            {alertas.slice(0, 8).map((a) => {
              const socio = socioMap.get(a.socioId);
              return (
                <li key={a.id} className="flex items-center gap-4 px-5 py-3">
                  <div className="min-w-0 flex-1">
                    <Link
                      to="/socios/$socioId"
                      params={{ socioId: a.socioId }}
                      className="truncate text-sm font-semibold hover:underline"
                    >
                      {socio?.nombre}
                    </Link>
                    <p className="truncate text-xs text-muted-foreground">
                      {a.area ? `${a.area} · ${a.predio}` : "Cuota social"} · vence{" "}
                      {formatFecha(a.vencimiento)}
                    </p>
                  </div>
                  <EstadoBadge estado={a.estadoSocio} />
                  <Button
                    size="sm"
                    onClick={() =>
                      navigate({ to: "/pagos", search: { nuevo: "1", socioId: a.socioId } })
                    }
                  >
                    Cobrar
                  </Button>
                </li>
              );
            })}
            {alertas.length === 0 && (
              <li className="px-5 py-8 text-center text-sm text-muted-foreground">
                No hay vencimientos que atender.
              </li>
            )}
          </ul>
        </Card>

        <Card className="border-danger/30 bg-danger/5 p-5">
          <div className="flex items-center gap-3">
            <span className="rounded-md bg-danger/15 p-2 text-danger">
              <AlertTriangle className="size-5" />
            </span>
            <div>
              <p className="text-3xl leading-none font-bold text-danger tabular-nums">
                {alertas.length}
              </p>
              <p className="text-sm font-medium">Membresías con alerta</p>
            </div>
          </div>
          <p className="mt-4 text-xs text-muted-foreground">
            Vencidas o suspendidas, según las sirve el backend. Sin ventana de aviso previo: solo la
            deuda real.
          </p>
          <Button
            className="mt-5 w-full"
            variant="secondary"
            onClick={() => navigate({ to: "/notificaciones" })}
          >
            <BellRing className="mr-2 size-4" /> Notificar a los socios
          </Button>
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
