import { createFileRoute, Link } from "@tanstack/react-router";
import { FileUp, Plus, Search, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ImportModal, type ImportColumnSpec } from "@/components/import";
import { ExportButton } from "@/components/export";
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
import { AreaBadge } from "@/components/canyp/AreaBadge";
import { PageHeader } from "@/components/canyp/AppShell";
import { estadoVisual, type EstadoVisual } from "@/lib/canyp/utils";
import { useSocios, useMembresias, useCreateSocio, useDeleteSocio } from "@/lib/canyp/queries";
import type { Socio, Membresia } from "@/lib/canyp/types";

export const Route = createFileRoute("/socios/")({
  head: () => ({
    meta: [
      { title: "Socios — CANYP Gestión" },
      {
        name: "description",
        content: "Padrón de socios del club con filtros por predio, área y estado de membresía.",
      },
      { property: "og:title", content: "Socios — CANYP Gestión" },
      { property: "og:description", content: "Buscá un socio y accedé a su ficha en un clic." },
    ],
  }),
  component: SociosPage,
});

const prioridad: EstadoVisual[] = ["vencida", "por_vencer", "suspendida", "activa", "baja"];

/** Editable columns shown in the import preview (Spanish label + canonical field). */
const importColumns: ImportColumnSpec[] = [
  { label: "Nombre", field: "nombre" },
  { label: "DNI", field: "dni" },
  { label: "Teléfono", field: "telefono" },
  { label: "Email", field: "email" },
  { label: "Dirección", field: "direccion" },
  { label: "Fecha de alta", field: "fechaAlta" },
  { label: "Activo", field: "activo" },
];

function SociosPage() {
  const { data: socios = [], isLoading: loadingSocios, refetch: refetchSocios } = useSocios();
  const { data: membresias = [] } = useMembresias();
  const createSocio = useCreateSocio();
  const deleteSocio = useDeleteSocio();
  const [q, setQ] = useState("");
  const [predio, setPredio] = useState("todos");
  const [area, setArea] = useState("todas");
  const [estado, setEstado] = useState("todos");
  const [open, setOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Socio | null>(null);
  const [form, setForm] = useState({
    nombre: "",
    dni: "",
    telefono: "",
    email: "",
    direccion: "",
  });

  const filas = useMemo(() => {
    return socios
      .map((s: Socio) => {
        const ms = membresias.filter((m: Membresia) => m.socioId === s.id);
        const estados = ms.map(estadoVisual);
        const general =
          prioridad.find((p) => estados.includes(p)) ?? (s.activo ? "activa" : "baja");
        return { socio: s, membresias: ms, estados, general };
      })
      .filter((f) => {
        const term = q.trim().toLowerCase();
        if (
          term &&
          !`${f.socio.nombre} ${f.socio.dni} ${f.socio.email} ${f.socio.telefono}`
            .toLowerCase()
            .includes(term)
        )
          return false;
        if (predio !== "todos" && !f.membresias.some((m) => m.predio === predio)) return false;
        if (area !== "todas" && !f.membresias.some((m) => m.area === area)) return false;
        if (estado !== "todos" && !f.estados.includes(estado as EstadoVisual)) return false;
        return true;
      });
  }, [socios, membresias, q, predio, area, estado]);

  function crearSocio() {
    if (!form.nombre || !form.telefono) {
      toast.error("Nombre y teléfono son obligatorios");
      return;
    }
    createSocio.mutate(
      { ...form, activo: true },
      {
        onSuccess: (nuevo) => {
          setOpen(false);
          setForm({ nombre: "", dni: "", telefono: "", email: "", direccion: "" });
          toast.success(`Socio ${nuevo.nombre} dado de alta`);
        },
        onError: () => toast.error("Error al crear el socio"),
      },
    );
  }

  if (loadingSocios) {
    return (
      <>
        <PageHeader title="Socios" subtitle="Cargando..." />
        <Card className="p-10 text-center text-sm text-muted-foreground">Cargando socios...</Card>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Socios"
        subtitle="Padrón general del club. Ingresá a la ficha para ver membresías y pagos."
        actions={
          <>
            <ExportButton resource="socios" label="socios" />
            <Button variant="outline" onClick={() => setImportOpen(true)}>
              <FileUp className="mr-2 size-4" /> Importar socios
            </Button>
            <Button onClick={() => setOpen(true)}>
              <Plus className="mr-2 size-4" /> Nuevo socio
            </Button>
          </>
        }
      />

      <Card className="mb-4 flex flex-wrap items-center gap-3 p-4">
        <div className="relative min-w-[240px] flex-1">
          <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Buscar por nombre, DNI, email o teléfono"
            className="pl-9"
          />
        </div>
        <Select value={predio} onValueChange={setPredio}>
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder="Predio" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="todos">Todos los predios</SelectItem>
            <SelectItem value="Embalse">Embalse</SelectItem>
            <SelectItem value="Almafuerte">Almafuerte</SelectItem>
          </SelectContent>
        </Select>
        <Select value={area} onValueChange={setArea}>
          <SelectTrigger className="w-[150px]">
            <SelectValue placeholder="Área" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="todas">Todas las áreas</SelectItem>
            <SelectItem value="Balseros">Balseros</SelectItem>
            <SelectItem value="Cabañeros">Cabañeros</SelectItem>
            <SelectItem value="Guardería">Guardería</SelectItem>
            <SelectItem value="Windsurf">Windsurf</SelectItem>
          </SelectContent>
        </Select>
        <Select value={estado} onValueChange={setEstado}>
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder="Estado" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="todos">Todos los estados</SelectItem>
            <SelectItem value="activa">Activa</SelectItem>
            <SelectItem value="por_vencer">Por vencer</SelectItem>
            <SelectItem value="vencida">Vencida</SelectItem>
            <SelectItem value="suspendida">Suspendida</SelectItem>
            <SelectItem value="baja">Dada de baja</SelectItem>
          </SelectContent>
        </Select>
      </Card>

      <Card className="overflow-hidden p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Socio</TableHead>
              <TableHead>DNI</TableHead>
              <TableHead>Contacto</TableHead>
              <TableHead>Áreas / predios</TableHead>
              <TableHead>Estado general</TableHead>
              <TableHead className="text-right">Acciones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filas.map((f) => (
              <TableRow key={f.socio.id}>
                <TableCell className="font-medium">
                  <Link
                    to="/socios/$socioId"
                    params={{ socioId: f.socio.id }}
                    className="hover:underline"
                  >
                    {f.socio.nombre}
                  </Link>
                </TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">
                  {f.socio.dni}
                </TableCell>
                <TableCell className="text-xs">
                  <p>{f.socio.telefono}</p>
                  <p className="text-muted-foreground">{f.socio.email}</p>
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {f.membresias.length === 0 && (
                      <span className="text-xs text-muted-foreground">Sin membresías</span>
                    )}
                    {f.membresias.map((m) => (
                      <span key={m.id} className="inline-flex items-center gap-1">
                        <AreaBadge area={m.area} />
                        <span className="text-[11px] text-muted-foreground">{m.predio}</span>
                      </span>
                    ))}
                  </div>
                </TableCell>
                <TableCell>
                  <EstadoBadge estado={f.general} />
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex items-center justify-end gap-2">
                    <Button asChild size="sm" variant="outline">
                      <Link to="/socios/$socioId" params={{ socioId: f.socio.id }}>
                        Ver ficha
                      </Link>
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="text-destructive hover:bg-destructive hover:text-destructive-foreground"
                      onClick={() => setDeleteTarget(f.socio)}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
            {filas.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="py-10 text-center text-sm text-muted-foreground">
                  No hay socios que coincidan con la búsqueda.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nuevo socio</DialogTitle>
            <DialogDescription>
              Cargá los datos personales. Las membresías se agregan después desde la ficha.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Label htmlFor="nombre">Nombre y apellido *</Label>
              <Input
                id="nombre"
                value={form.nombre}
                onChange={(e) => setForm({ ...form, nombre: e.target.value })}
                className="mt-1.5"
              />
            </div>
            <div>
              <Label htmlFor="dni">DNI</Label>
              <Input
                id="dni"
                value={form.dni}
                onChange={(e) => setForm({ ...form, dni: e.target.value })}
                className="mt-1.5"
              />
            </div>
            <div>
              <Label htmlFor="tel">Teléfono *</Label>
              <Input
                id="tel"
                value={form.telefono}
                onChange={(e) => setForm({ ...form, telefono: e.target.value })}
                className="mt-1.5"
              />
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                className="mt-1.5"
              />
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="dir">Dirección</Label>
              <Input
                id="dir"
                value={form.direccion}
                onChange={(e) => setForm({ ...form, direccion: e.target.value })}
                className="mt-1.5"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancelar
            </Button>
            <Button onClick={crearSocio} disabled={createSocio.isPending}>
              Dar de alta
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ImportModal
        resource="socios"
        resourceLabel="socios"
        columnSpec={importColumns}
        open={importOpen}
        onOpenChange={setImportOpen}
        onImportComplete={() => refetchSocios()}
      />

      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar socio</AlertDialogTitle>
            <AlertDialogDescription>
              ¿Seguro que querés eliminar a <strong>{deleteTarget?.nombre}</strong>? Se borrarán
              todas sus membresías. Si es Titular de alguna unidad, se designará un nuevo Titular
              automáticamente.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (!deleteTarget) return;
                deleteSocio.mutate(deleteTarget.id, {
                  onSuccess: () => {
                    setDeleteTarget(null);
                    toast.success(`Socio ${deleteTarget.nombre} eliminado`);
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
    </>
  );
}
