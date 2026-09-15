import { createFileRoute } from "@tanstack/react-router";
import { UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PageHeader } from "@/components/canyp/AppShell";
import { formatFecha } from "@/lib/canyp/utils";
import { useUsuarios, useCreateUsuario } from "@/lib/canyp/queries";
import { ApiError } from "@/lib/canyp/api";
import type { Usuario } from "@/lib/canyp/types";

export const Route = createFileRoute("/usuarios")({
  head: () => ({
    meta: [
      { title: "Usuarios — CANYP Gestión" },
      {
        name: "description",
        content: "Cuentas con acceso al sistema. Todas tienen el mismo nivel de permisos.",
      },
    ],
  }),
  component: UsuariosPage,
});

function UsuariosPage() {
  const { data: usuarios = [] } = useUsuarios();
  const createUsuario = useCreateUsuario();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const nombre = username.trim();
    if (!nombre) {
      toast.error("Ingresá un nombre de usuario");
      return;
    }
    if (password.length < 6) {
      toast.error("La contraseña debe tener al menos 6 caracteres");
      return;
    }
    createUsuario.mutate(
      { username: nombre, password },
      {
        onSuccess: () => {
          setUsername("");
          setPassword("");
          toast.success("Usuario creado");
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) {
            toast.error("El nombre de usuario ya existe");
          } else if (err instanceof ApiError && err.status === 422) {
            toast.error("La contraseña debe tener al menos 6 caracteres");
          } else {
            toast.error("No se pudo crear el usuario");
          }
        },
      },
    );
  }

  return (
    <>
      <PageHeader
        title="Usuarios"
        subtitle="Todas las cuentas tienen el mismo nivel de acceso: listar y crear usuarios."
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="h-fit p-5">
          <h2 className="text-sm font-semibold">Nuevo usuario</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Cada usuario puede ingresar al sistema y cobrar con su propia cuenta.
          </p>
          <form onSubmit={onSubmit} className="mt-4 space-y-4">
            <div className="space-y-2">
              <Label htmlFor="usuario-username">Usuario</Label>
              <Input
                id="usuario-username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                placeholder="Ej: operador"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="usuario-password">Contraseña</Label>
              <Input
                id="usuario-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
              />
              <p className="text-xs text-muted-foreground">Mínimo 6 caracteres.</p>
            </div>
            <Button type="submit" disabled={createUsuario.isPending}>
              <UserPlus className="mr-2 size-4" /> Crear usuario
            </Button>
          </form>
        </Card>

        <Card className="overflow-hidden p-0 lg:col-span-2">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Usuario</TableHead>
                <TableHead>Creado el</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {usuarios.map((u: Usuario) => (
                <TableRow key={u.id}>
                  <TableCell className="font-medium">{u.username}</TableCell>
                  <TableCell className="text-xs tabular-nums">
                    {formatFecha(u.created_at.slice(0, 10))}
                  </TableCell>
                </TableRow>
              ))}
              {usuarios.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={2}
                    className="py-10 text-center text-sm text-muted-foreground"
                  >
                    No hay usuarios todavía.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </Card>
      </div>
    </>
  );
}
