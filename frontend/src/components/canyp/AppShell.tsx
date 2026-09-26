import { Link, useRouterState } from "@tanstack/react-router";
import {
  BellRing,
  CreditCard,
  LayoutDashboard,
  LogOut,
  ScrollText,
  Settings,
  Tags,
  UserPlus,
  Users,
} from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { CLIENT_BUILD } from "@/lib/canyp/build-flags";
import { useDashboardAlertas } from "@/lib/canyp/queries";
import { DataModeBadge } from "@/components/canyp/DataModeBadge";
import { TooltipProvider } from "@/components/ui/tooltip";

const nav: { to: string; label: string; icon: typeof Users; exact?: boolean }[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, exact: true },
  { to: "/socios", label: "Socios", icon: Users },
  { to: "/membresias", label: "Membresías", icon: ScrollText },
  { to: "/aranceles", label: "Aranceles", icon: Tags },
  { to: "/pagos", label: "Pagos", icon: CreditCard },
  { to: "/notificaciones", label: "Notificaciones", icon: BellRing },
  { to: "/usuarios", label: "Usuarios", icon: UserPlus },
  { to: "/ajustes", label: "Ajustes", icon: Settings },
];

export function AppShell({
  children,
  onLogout,
}: {
  children: ReactNode;
  onLogout?: () => void;
}) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  // El badge de Notificaciones cuenta las alertas SERVIDAS por el backend
  // (membresías vencidas/suspendidas), no un estado derivado en el cliente.
  const { data: alertas = [] } = useDashboardAlertas();
  const navItems = CLIENT_BUILD ? nav.filter((i) => i.to !== "/ajustes") : nav;

  return (
    <TooltipProvider delayDuration={0}>
      <div className="flex min-h-screen w-full bg-background">
        <aside className="fixed inset-y-0 left-0 z-20 hidden w-60 flex-col bg-sidebar text-sidebar-foreground md:flex">
          <div className="flex shrink-0 flex-col items-center gap-3 border-b border-sidebar-border px-5 py-6">
            <div className="flex h-20 w-[70px] items-center justify-center">
              <img
                src="/CANYP_Almafuerte_logo.svg?v=3"
                alt="CANYP logo"
                className="h-full w-full object-contain"
              />
            </div>
            <div className="text-center leading-tight">
              <p className="text-base font-bold tracking-wide">CANYP</p>
              <p className="text-[11px] text-sidebar-foreground/60">Sistema de Gestión</p>
            </div>
          </div>
          <nav className="min-h-0 flex-1 space-y-1 overflow-y-auto p-3">
            {navItems.map((item) => {
              const active = item.exact ? pathname === item.to : pathname.startsWith(item.to);
              return (
                <Link
                  key={item.to}
                  to={item.to as string}
                  className={cn(
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    active
                      ? "bg-sidebar-accent text-sidebar-accent-foreground"
                      : "text-sidebar-foreground/75 hover:bg-sidebar-accent/50 hover:text-sidebar-accent-foreground",
                  )}
                >
                  <item.icon className="size-4" />
                  <span className="flex-1">{item.label}</span>
                  {item.label === "Notificaciones" && alertas.length > 0 && (
                    <span className="rounded-full bg-danger px-1.5 py-0.5 text-[10px] font-bold text-danger-foreground">
                      {alertas.length}
                    </span>
                  )}
                </Link>
              );
            })}
          </nav>
          <div className="shrink-0 flex items-center justify-between gap-2 border-t border-sidebar-border px-4 py-3">
            <DataModeBadge />
            {onLogout && (
              <button
                onClick={onLogout}
                title="Cerrar sesión"
                className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium text-sidebar-foreground/65 transition-colors hover:bg-sidebar-accent/50 hover:text-sidebar-accent-foreground"
              >
                <LogOut className="size-3.5" />
                Salir
              </button>
            )}
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col md:pl-60">
          <nav className="flex gap-1 overflow-x-auto border-b border-border bg-sidebar px-3 py-2 md:hidden">
            {navItems.map((item) => (
              <Link
                key={item.to}
                to={item.to as string}
                className="rounded-md px-3 py-1.5 text-xs font-medium text-sidebar-foreground/80"
              >
                {item.label}
              </Link>
            ))}
          </nav>
          <main className="mx-auto w-full max-w-[1400px] flex-1 px-5 py-6 lg:px-8">{children}</main>
        </div>
      </div>
    </TooltipProvider>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
