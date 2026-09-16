import { createFileRoute, Link, useNavigate, useParams } from "@tanstack/react-router";
import { ArrowLeft, CreditCard, Pencil, Plus, Trash2, UserCheck, UserX } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
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
import { EstadoBadge } from "@/components/canyp/EstadoBadge";
import { PageHeader } from "@/components/canyp/AppShell";
import { diasRestantes, estadoVisual, formatARS, formatFecha } from "@/lib/canyp/utils";
import {
  useSocio,
  useMembresias,
  usePagos,
  useUpdateSocio,
  useCreateMembresia,
  useUpdateMembresia,
  useDeleteSocio,
  useAranceles,
  useUsuarios,
} from "@/lib/canyp/queries";
import type { Arancel, Area, Membresia, Predio, Rol, Socio, Usuario } from "@/lib/canyp/types";

export const Route = createFileRoute("/socios/$socioId")({
  head: () => ({
    meta: [
      { title: "Ficha de socio — CANYP Gestión" },
      {
        name: "description",
        content: "Datos personales, membresías por predio e historial de pagos del socio.",
      },
      { property: "og:title", content: "Ficha de socio — CANYP Gestión" },
      {
        property: "og:description",
        content: "Estado de membresías y comprobantes emitidos en una sola vista.",
      },
    ],
  }),
  component: FichaSocio,
});

const areasPorPredio: Record<Predio, Area[]> = {
  Embalse: ["Balseros"],
  Almafuerte: ["Cabañeros", "Guardería", "Windsurf"],
};

function FichaSocio() {
  const { socioId } = useParams({ from: "/socios/$socioId" });
  const navigate = useNavigate();
  const { data: socio, isLoading: loadingSocio } = useSocio(socioId);
  const { data: allMembresias = [] } = useMembresias();
  const { data: pagos = [] } = usePagos();
  const updateSocio = useUpdateSocio();
  const createMembresia = useCreateMembresia();
  const updateMembresia = useUpdateMembresia();
  const deleteSocio = useDeleteSocio();
  const { data: aranceles = [] } = useAranceles();
  const { data: usuarios = [] } = useUsuarios();

  const [editOpen, setEditOpen] = useState(false);
  const [memOpen, setMemOpen] = useState(false);
  const [edit, setEdit] = useState<Socio | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [bajaOpen, setBajaOpen] = useState(false);
  const [nueva, setNueva] = useState<{
    predio: Predio;
    area: Area;
    vencimiento: string;
    detalle: string;
    arancelId: string;
    rol: Rol | "";
  }>({
    predio: "Embalse",
    area: "Balseros",
    vencimiento: new Date(Date.now() + 365 * 86400000).toISOString().slice(0, 10),
    detalle: "",
    arancelId: "",
    rol: "Titular",
  });

  if (loadingSocio) {
    return (
      <Card className="p-10 text-center text-sm text-muted-foreground">Cargando socio...</Card>
    );
  }

  if (!socio) {
    return (
      <Card className="p-10 text-center">
        <p className="text-sm text-muted-foreground">No se encontró el socio.</p>
        <Button asChild className="mt-4">
          <Link to="/socios">Volver al padrón</Link>
        </Button>
      </Card>
    );
  }

  const membresias = allMembresias.filter((m: Membresia) => m.socioId === socio.id);
  const pagosSocio = pagos.filter((p) => p.socioId === socio.id);

  const usuarioMap = useMemo(
    () => new Map(usuarios.map((u: Usuario) => [u.id, u.username])),
    [usuarios],
  );

  const arancelesArea = aranceles.filter(
    (a: Arancel) => a.area === nueva.area && a.predio === nueva.predio,
  );

  return (
    <>
      <Link
        to="/socios"
        className="mb-4 inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" /> Volver a socios
      </Link>

      {(socio.activo === false || socio.categoria === "vitalicio") && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {socio.activo === false && <EstadoBadge estado="baja" />}
          {socio.categoria === "vitalicio" && (
            <span className="rounded-full bg-secondary px-2 py-0.5 text-xs font-medium text-secondary-foreground">
              Vitalicio
            </span>
          )}
        </div>
      )}

      <PageHeader
        title={socio.nombre}
        subtitle={`${socio.dni ? `DNI ${socio.dni} · ` : ""}Socio desde ${formatFecha(socio.fechaAlta)}`}
        actions={
          <>
            <Button
              variant="outline"
              onClick={() => {
                setEdit(socio);
                setEditOpen(true);
              }}
            >
              <Pencil className="mr-2 size-4" /> Editar datos
            </Button>
            <Button variant="outline" onClick={() => setMemOpen(true)}>
              <Plus className="mr-2 size-4" /> Nueva membresía
            </Button>
            <Button
              onClick={() => navigate({ to: "/pagos", search: { nuevo: "1", socioId: socio.id } })}
            >
              <CreditCard className="mr-2 size-4" /> Registrar pago
            </Button>
            {socio.activo ? (
              <Button variant="outline" onClick={() => setBajaOpen(true)}>
                <UserX className="mr-2 size-4" /> Dar de baja
              </Button>
            ) : (
              <Button
                variant="outline"
                onClick={() =>
                  updateSocio.mutate(
                    { id: socio.id, data: { activo: true } },
                    {
                      onSuccess: () => toast.success("Socio reactivado"),
                      onError: () => toast.error("Error al reactivar el socio"),
                    },
                  )
                }
              >
                <UserCheck className="mr-2 size-4" /> Reactivar
              </Button>
            )}
            <Button
              variant="outline"
              className="text-destructive hover:bg-destructive hover:text-destructive-foreground"
              onClick={() => setDeleteOpen(true)}
            >
              <Trash2 className="mr-2 size-4" /> Eliminar
            </Button>
          </>
        }
      />

      <section className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card className="p-0">
            <div className="border-b border-border px-5 py-4">
              <h2 className="text-sm font-semibold">Membresías ({membresias.length})</h2>
              <p className="text-xs text-muted-foreground">
                Cada actividad se gestiona y se cobra por separado.
              </p>
            </div>
            <ul className="divide-y divide-border">
              {membresias.map((m) => {
                const e = estadoVisual(m);
                const d = diasRestantes(m.vencimiento);
                return (
                  <li key={m.id} className="flex flex-wrap items-center gap-4 px-5 py-4">
                    <div className="min-w-[180px] flex-1">
                      <p className="text-sm font-semibold">
                        {m.area} · {m.predio}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {m.detalle} — vence {formatFecha(m.vencimiento)} (
                        {d < 0 ? `hace ${Math.abs(d)} días` : `en ${d} días`})
                      </p>
                    </div>
                    <EstadoBadge estado={e} />
                    <Select
                      value={m.estado}
                      onValueChange={(v) => {
                        updateMembresia.mutate(
                          { id: m.id, data: { estado: v as Membresia["estado"] } },
                          { onSuccess: () => toast.success("Estado de la membresía actualizado") },
                        );
                      }}
                    >
                      <SelectTrigger className="w-[150px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="activa">Activar</SelectItem>
                        <SelectItem value="suspendida">Suspender</SelectItem>
                        <SelectItem value="vencida">Marcar vencida</SelectItem>
                        <SelectItem value="baja">Dar de baja</SelectItem>
                      </SelectContent>
                    </Select>
                  </li>
                );
              })}
              {membresias.length === 0 && (
                <li className="px-5 py-8 text-center text-sm text-muted-foreground">
                  Este socio todavía no tiene membresías.
                </li>
              )}
            </ul>
          </Card>

          <Card className="p-0">
            <div className="border-b border-border px-5 py-4">
              <h2 className="text-sm font-semibold">Historial de pagos</h2>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Comprobante</TableHead>
                  <TableHead>Fecha</TableHead>
                  <TableHead>Detalle</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pagosSocio.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-mono text-xs">{p.numero}</TableCell>
                    <TableCell className="text-xs">{formatFecha(p.fecha)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {p.items.map((i) => i.nombre).join(" + ")}
                    </TableCell>
                    <TableCell className="text-right font-semibold tabular-nums">
                      {formatARS(p.total)}
                    </TableCell>
                  </TableRow>
                ))}
                {pagosSocio.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={4}
                      className="py-8 text-center text-sm text-muted-foreground"
                    >
                      Sin pagos registrados.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </Card>
        </div>

        <Card className="h-fit p-5">
          <h2 className="text-sm font-semibold">Datos personales</h2>
          <dl className="mt-4 space-y-3 text-sm">
            {[
              ["DNI", socio.dni],
              ["Teléfono", socio.telefono],
              ["Email", socio.email],
              ["Dirección", socio.direccion],
              ["Fecha de alta", formatFecha(socio.fechaAlta)],
            ].map(([k, v]) => (
              <div key={k}>
                <dt className="text-[11px] tracking-wide text-muted-foreground uppercase">{k}</dt>
                <dd className="font-medium break-words">{v || "—"}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </section>

      <p className="mt-6 text-xs text-muted-foreground">
        Creado por {usuarioMap.get(socio.createdBy ?? "") ?? "sin operador"} · Modificado por{" "}
        {usuarioMap.get(socio.updatedBy ?? "") ?? "—"}
      </p>

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Editar datos del socio</DialogTitle>
          </DialogHeader>
          {edit && (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <Label>Nombre</Label>
                <Input
                  value={edit.nombre}
                  onChange={(e) => setEdit({ ...edit, nombre: e.target.value })}
                  className="mt-1.5"
                />
              </div>
              <div>
                <Label>DNI</Label>
                <Input
                  value={edit.dni}
                  onChange={(e) => setEdit({ ...edit, dni: e.target.value })}
                  className="mt-1.5"
                />
              </div>
              <div>
                <Label>Teléfono</Label>
                <Input
                  value={edit.telefono}
                  onChange={(e) => setEdit({ ...edit, telefono: e.target.value })}
                  className="mt-1.5"
                />
              </div>
              <div className="sm:col-span-2">
                <Label>Email</Label>
                <Input
                  value={edit.email}
                  onChange={(e) => setEdit({ ...edit, email: e.target.value })}
                  className="mt-1.5"
                />
              </div>
              <div className="sm:col-span-2">
                <Label>Dirección</Label>
                <Input
                  value={edit.direccion}
                  onChange={(e) => setEdit({ ...edit, direccion: e.target.value })}
                  className="mt-1.5"
                />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditOpen(false)}>
              Cancelar
            </Button>
            <Button
              onClick={() => {
                if (edit)
                  updateSocio.mutate(
                    { id: socio.id, data: edit },
                    {
                      onSuccess: () => {
                        setEditOpen(false);
                        toast.success("Datos actualizados");
                      },
                    },
                  );
              }}
            >
              Guardar cambios
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={memOpen} onOpenChange={setMemOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nueva membresía</DialogTitle>
            <DialogDescription>
              Un socio puede tener actividad en ambos predios al mismo tiempo.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label>Predio</Label>
              <Select
                value={nueva.predio}
                onValueChange={(v) =>
                  setNueva({
                    ...nueva,
                    predio: v as Predio,
                    area: areasPorPredio[v as Predio][0]!,
                    rol: "Titular",
                    arancelId: "",
                  })
                }
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
            <div>
              <Label>Área</Label>
              <Select
                value={nueva.area}
                onValueChange={(v) => {
                  const area = v as Area;
                  const rol: Rol | "" =
                    area === "Balseros" || area === "Cabañeros" ? "Titular" : "";
                  setNueva({ ...nueva, area, rol, arancelId: "" });
                }}
              >
                <SelectTrigger className="mt-1.5">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {areasPorPredio[nueva.predio].map((a) => (
                    <SelectItem key={a} value={a}>
                      {a}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {(nueva.area === "Balseros" || nueva.area === "Cabañeros") && (
              <div>
                <Label>Rol</Label>
                <Select
                  value={nueva.rol}
                  onValueChange={(v) => setNueva({ ...nueva, rol: v as Rol })}
                >
                  <SelectTrigger className="mt-1.5">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Titular">Titular</SelectItem>
                    <SelectItem value="Integrante">Integrante</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
            <div>
              <Label>Vencimiento</Label>
              <Input
                type="date"
                value={nueva.vencimiento}
                onChange={(e) => setNueva({ ...nueva, vencimiento: e.target.value })}
                className="mt-1.5"
              />
            </div>
            <div>
              <Label>Detalle (balsa, cabaña, box)</Label>
              <Input
                value={nueva.detalle}
                onChange={(e) => setNueva({ ...nueva, detalle: e.target.value })}
                className="mt-1.5"
              />
            </div>
            <div>
              <Label>Arancel</Label>
              <Select
                value={nueva.arancelId}
                onValueChange={(v) =>
                  setNueva({ ...nueva, arancelId: v === "__ninguno__" ? "" : v })
                }
              >
                <SelectTrigger className="mt-1.5">
                  <SelectValue placeholder="Seleccionar arancel" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__ninguno__">Sin arancel</SelectItem>
                  {arancelesArea.map((a) => (
                    <SelectItem key={a.id} value={a.id}>
                      {a.nombre} — ${a.monto.toLocaleString("es-AR")}
                      {a.categoria ? ` (categoría: ${a.categoria})` : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setMemOpen(false)}>
              Cancelar
            </Button>
            <Button
              onClick={() => {
                const { arancelId, rol, ...resto } = nueva;
                createMembresia.mutate(
                  {
                    socioId: socio.id,
                    estado: "activa",
                    ...resto,
                    ...(rol ? { rol } : {}),
                    ...(arancelId ? { arancelId } : {}),
                  },
                  {
                    onSuccess: () => {
                      setMemOpen(false);
                      toast.success("Membresía agregada");
                    },
                  },
                );
              }}
            >
              Agregar membresía
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar socio</AlertDialogTitle>
            <AlertDialogDescription>
              ¿Seguro que querés eliminar a <strong>{socio.nombre}</strong>? Se borrarán todas sus
              membresías y pagos asociados. Si es Titular de alguna unidad, se designará un nuevo
              Titular automáticamente.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                deleteSocio.mutate(socio.id, {
                  onSuccess: () => {
                    setDeleteOpen(false);
                    toast.success(`Socio ${socio.nombre} eliminado`);
                    navigate({ to: "/socios" });
                  },
                  onError: () => toast.error("Error al eliminar el socio"),
                });
              }}
            >
              Eliminar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={bajaOpen} onOpenChange={setBajaOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Dar de baja al socio</AlertDialogTitle>
            <AlertDialogDescription>
              ¿Seguro que querés dar de baja a <strong>{socio.nombre}</strong>? El socio dejará de
              estar activo pero conservará su historial de membresías y pagos.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                updateSocio.mutate(
                  { id: socio.id, data: { activo: false } },
                  {
                    onSuccess: () => {
                      setBajaOpen(false);
                      toast.success("Socio dado de baja");
                    },
                    onError: () => toast.error("Error al dar de baja al socio"),
                  },
                );
              }}
            >
              Dar de baja
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
