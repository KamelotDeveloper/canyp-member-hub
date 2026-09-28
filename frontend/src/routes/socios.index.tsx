import { createFileRoute, Link, useNavigate, useSearch } from "@tanstack/react-router";
import { FileUp, Plus, Printer, Search, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
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
import { CarnetPrint } from "@/components/canyp/CarnetPrint";
import { PageHeader } from "@/components/canyp/AppShell";
import { useSocios, useMembresias, useCreateSocio, useDeleteSocio } from "@/lib/canyp/queries";
import { ORDEN_ESTADOS } from "@/lib/canyp/utils";
import type { Area, EstadoSocio, Predio, Socio, Membresia } from "@/lib/canyp/types";

/** Las 4 áreas de membresía, para validar el filtro `area` de la URL. */
const AREAS: readonly Area[] = ["Balseros", "Cabañeros", "Guardería", "Windsurf"];

/** Filtros del padrón transportados en la URL (el atajo del dashboard los setea). */
type SociosSearch = { q?: string; predio?: Predio; area?: Area; estado?: EstadoSocio };

export const Route = createFileRoute("/socios/")({
  validateSearch: (s: Record<string, unknown>): SociosSearch => ({
    ...(typeof s["q"] === "string" && s["q"] ? { q: s["q"] } : {}),
    ...(s["predio"] === "Embalse" || s["predio"] === "Almafuerte" ? { predio: s["predio"] } : {}),
    ...(AREAS.includes(s["area"] as Area) ? { area: s["area"] as Area } : {}),
    ...(ORDEN_ESTADOS.includes(s["estado"] as EstadoSocio)
      ? { estado: s["estado"] as EstadoSocio }
      : {}),
  }),
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
  const search = useSearch({ from: "/socios/" });
  const navigate = useNavigate();
  const [q, setQ] = useState(() => search.q ?? "");
  // Predio/área/estado viven en la URL: el atajo del dashboard los setea y el
  // botón "atrás" vuelve al filtro anterior. "todos"/"todas" = sin filtro.
  const predio = search.predio ?? "todos";
  const area = search.area ?? "todas";
  const estado = search.estado ?? "todos";
  const [open, setOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Socio | null>(null);
  const [printOpen, setPrintOpen] = useState(false);
  /** Carnets seleccionados: ids de socio sobre las filas filtradas actuales. */
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [form, setForm] = useState({
    nombre: "",
    dni: "",
    telefono: "",
    email: "",
    direccion: "",
  });

  /** Refleja un filtro de select en la URL (compartible y compatible con "atrás"). */
  function setFiltro<K extends "predio" | "area" | "estado">(key: K, value: SociosSearch[K]) {
    const next: SociosSearch = { ...search };
    if (value === undefined) delete next[key];
    else next[key] = value;
    navigate({ to: "/socios", search: next });
  }

  const filas = useMemo(() => {
    return socios
      .map((s: Socio) => {
        const ms = membresias.filter((m: Membresia) => m.socioId === s.id);
        // El estado es el que SIRVIÓ el backend en `Socio.estado`: no se deriva.
        return { socio: s, membresias: ms, estado: s.estado };
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
        if (estado !== "todos" && f.estado !== estado) return false;
        return true;
      });
  }, [socios, membresias, q, predio, area, estado]);

  const selTodos = filas.length > 0 && sel.size === filas.length;

  /** Select-all toggles over the CURRENT filtered rows (mirrors notificaciones). */
  function toggleSelectarTodos() {
    setSel(selTodos ? new Set() : new Set(filas.map((f) => f.socio.id)));
  }

  function toggleSocio(id: string, on: boolean) {
    setSel((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  const sociosSeleccionados = useMemo(
    () => filas.filter((f) => sel.has(f.socio.id)).map((f) => f.socio),
    [filas, sel],
  );

  function crearSocio() {
    if (!form.nombre || !form.telefono) {
      toast.error("Nombre y teléfono son obligatorios");
      return;
    }
    createSocio.mutate(
      { ...form, activo: true, numeroSocio: null, tieneFoto: false },
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
        subtitle={`${socios.length} socios en el padrón`}
        actions={
          <>
            <Button
              variant="outline"
              disabled={sociosSeleccionados.length === 0}
              onClick={() => setPrintOpen(true)}
            >
              <Printer className="mr-2 size-4" /> Imprimir carnets
            </Button>
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
        <span className="text-sm font-medium text-muted-foreground">Total: {socios.length}</span>
        <Select
          value={predio}
          onValueChange={(v) => setFiltro("predio", v === "todos" ? undefined : (v as Predio))}
        >
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder="Predio" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="todos">Todos los predios</SelectItem>
            <SelectItem value="Embalse">Embalse</SelectItem>
            <SelectItem value="Almafuerte">Almafuerte</SelectItem>
          </SelectContent>
        </Select>
        <Select
          value={area}
          onValueChange={(v) => setFiltro("area", v === "todas" ? undefined : (v as Area))}
        >
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
        <Select
          value={estado}
          onValueChange={(v) => setFiltro("estado", v === "todos" ? undefined : (v as EstadoSocio))}
        >
          <SelectTrigger className="w-[170px]">
            <SelectValue placeholder="Estado" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="todos">Todos los estados</SelectItem>
            {ORDEN_ESTADOS.map((e) => (
              <SelectItem key={e} value={e}>
                {e}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Card>

      <Card className="overflow-hidden p-0">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-sm font-semibold">Padrón</h2>
          <div className="flex items-center gap-3">
            {sel.size > 0 && (
              <span className="text-xs text-muted-foreground tabular-nums">
                {sel.size} seleccionado{sel.size === 1 ? "" : "s"}
              </span>
            )}
            <button
              className="text-xs font-medium text-primary hover:underline"
              onClick={toggleSelectarTodos}
            >
              {selTodos ? "Quitar selección" : "Seleccionar todos"}
            </button>
          </div>
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">
                <Checkbox
                  aria-label={selTodos ? "Quitar selección" : "Seleccionar todos"}
                  checked={selTodos}
                  onCheckedChange={toggleSelectarTodos}
                />
              </TableHead>
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
                <TableCell>
                  <Checkbox
                    aria-label={`Seleccionar ${f.socio.nombre}`}
                    checked={sel.has(f.socio.id)}
                    onCheckedChange={(c) => toggleSocio(f.socio.id, !!c)}
                  />
                </TableCell>
                <TableCell className="font-medium">
                  <div className="flex items-center gap-2">
                    <Link
                      to="/socios/$socioId"
                      params={{ socioId: f.socio.id }}
                      className="hover:underline"
                    >
                      {f.socio.nombre}
                    </Link>
                    {f.socio.categoria === "vitalicio" && (
                      <span className="rounded-full bg-secondary px-2 py-0.5 text-xs font-medium text-secondary-foreground">
                        Vitalicio
                      </span>
                    )}
                  </div>
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
                    {f.membresias.map((m) =>
                      m.area ? (
                        <span key={m.id} className="inline-flex items-center gap-1">
                          <AreaBadge area={m.area} />
                          <span className="text-[11px] text-muted-foreground">{m.predio}</span>
                        </span>
                      ) : null,
                    )}
                  </div>
                </TableCell>
                <TableCell>{f.estado ? <EstadoBadge estado={f.estado} /> : null}</TableCell>
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
                <TableCell colSpan={7} className="py-10 text-center text-sm text-muted-foreground">
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

      {printOpen && (
        <CarnetPrint socios={sociosSeleccionados} onClose={() => setPrintOpen(false)} />
      )}
    </>
  );
}
