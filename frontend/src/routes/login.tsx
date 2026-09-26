import { createFileRoute } from "@tanstack/react-router";
import { LoginGate } from "@/components/canyp/LoginGate";

/**
 * Ruta de login (URL completa). El guard real vive en `__root.tsx` y no
 * depende de esta ruta (D12): acá simplemente montamos el LoginGate para que
 * `/login` sea una URL navegable.
 */
export const Route = createFileRoute("/login")({
  head: () => ({
    meta: [
      { title: "Ingresar — CANYP Gestión" },
      { name: "description", content: "Inicio de sesión del sistema CANYP." },
    ],
  }),
  component: LoginRoute,
});

function LoginRoute() {
  return <LoginGate onAuthenticated={() => {}} />;
}
