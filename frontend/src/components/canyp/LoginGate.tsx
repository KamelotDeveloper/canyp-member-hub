import { Loader2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, createFirstUser, login, setToken } from "@/lib/canyp/api";
import { useAuthStatus, useSettings } from "@/lib/canyp/queries";

/**
 * Pantalla de ingreso / primer usuario.
 *
 * Decide qué formulario mostrar según el estado del backend:
 * - Mientras el sistema no está configurado (`configured === false`), el
 *   DataModeWizard (incondicional en `__root.tsx`) se superpone; el gate queda
 *   en blanco para no pisar el wizard de primer uso.
 * - `configured === true && !users_exist` → FirstUserForm (crea el primer
 *   usuario y guarda el token).
 * - `configured === true && users_exist` → LoginForm (inicio de sesión).
 *
 * `configured` se deriva de dos señales: la respuesta de GET /api/settings
 * (abierto pre-config) o un 401 (D9: una vez configurado, settings exige auth).
 */
export function LoginGate({ onAuthenticated }: { onAuthenticated: (token: string) => void }) {
  const { data: settings, error: settingsError, isLoading: settingsLoading } = useSettings();
  const { data: status, isLoading: statusLoading } = useAuthStatus();

  const settingsUnauthorized = settingsError instanceof ApiError && settingsError.status === 401;
  const configured = settings?.configured === true || settingsUnauthorized;
  const usersExist = status?.users_exist ?? false;

  if (settingsLoading || statusLoading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-background">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
        <p className="text-sm text-muted-foreground">Iniciando servidor…</p>
      </div>
    );
  }

  if (!configured) {
    // El wizard de primer uso maneja la pre-configuración; no mostramos nada.
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <span className="sr-only">Configurando CANYP…</span>
      </div>
    );
  }

  if (!usersExist) {
    return (
      <AuthShell
        title="Crear el primer usuario"
        description="Todavía no hay usuarios. Definí las credenciales del administrador."
      >
        <FirstUserForm onAuthenticated={onAuthenticated} />
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Ingresar"
      description="Ingresá con tu usuario para acceder al sistema."
    >
      <LoginForm onAuthenticated={onAuthenticated} />
    </AuthShell>
  );
}

function AuthShell({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <img
            src="/CANYP_Almafuerte_logo.svg?v=3"
            alt="CANYP logo"
            className="mx-auto mb-3 size-16 object-contain"
          />
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <CardContent>{children}</CardContent>
      </Card>
    </div>
  );
}

function LoginForm({ onAuthenticated }: { onAuthenticated: (token: string) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) {
      toast.error("Usuario y contraseña son obligatorios");
      return;
    }
    setPending(true);
    login(username.trim(), password)
      .then(({ token }) => {
        setToken(token);
        onAuthenticated(token);
      })
      .catch((err: unknown) => {
        toast.error(err instanceof ApiError ? err.message : "No se pudo iniciar sesión");
      })
      .finally(() => setPending(false));
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="login-username">Usuario</Label>
        <Input
          id="login-username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          autoFocus
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="login-password">Contraseña</Label>
        <Input
          id="login-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />
      </div>
      <Button type="submit" className="w-full" disabled={pending}>
        {pending && <Loader2 className="size-4 animate-spin" />}
        Ingresar
      </Button>
    </form>
  );
}

function FirstUserForm({ onAuthenticated }: { onAuthenticated: (token: string) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!username.trim()) {
      toast.error("Elegí un nombre de usuario");
      return;
    }
    if (password.length < 6) {
      toast.error("La contraseña debe tener al menos 6 caracteres");
      return;
    }
    setPending(true);
    createFirstUser(username.trim(), password)
      .then(({ token }) => {
        setToken(token);
        onAuthenticated(token);
      })
      .catch((err: unknown) => {
        toast.error(err instanceof ApiError ? err.message : "No se pudo crear el usuario");
      })
      .finally(() => setPending(false));
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="first-username">Usuario</Label>
        <Input
          id="first-username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          autoFocus
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="first-password">Contraseña</Label>
        <Input
          id="first-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="new-password"
        />
        <p className="text-xs text-muted-foreground">Mínimo 6 caracteres.</p>
      </div>
      <Button type="submit" className="w-full" disabled={pending}>
        {pending && <Loader2 className="size-4 animate-spin" />}
        Crear usuario
      </Button>
    </form>
  );
}
