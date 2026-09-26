import type { Area, Socio } from "@/lib/canyp/types";
import { iniciales } from "@/lib/canyp/carnets";
import { AreaBadge } from "./AreaBadge";

/**
 * Carnet CR80 (85.6 x 54 mm) — fixed physical size via `.carnet` in styles.css.
 *
 * Background: club logo as a subtle watermark (top-right, low opacity).
 * Left: photo circle (object URL) or initials fallback.
 * Center: numero de socio, nombre, DNI.
 * Bottom: area badges (reuse AreaBadge); "Sin membresías" when the socio has
 * no non-baja memberships.
 */
export function CarnetCard({
  socio,
  areas,
  fotoUrl,
}: {
  socio: Socio;
  areas: Area[];
  fotoUrl?: string | null | undefined;
}) {
  return (
    <div className="carnet relative flex flex-col overflow-hidden rounded-[2mm] border border-slate-300 bg-white p-[3mm] text-slate-900">
      <img
        src="/CANYP_Almafuerte_logo.svg?v=3"
        alt=""
        aria-hidden
        className="carnet-logo pointer-events-none absolute top-[1mm] right-[1.5mm] h-[26mm] w-auto opacity-[0.10]"
      />
      <div className="relative flex items-center gap-[4mm]">
        <div className="flex h-[25mm] w-[25mm] shrink-0 items-center justify-center overflow-hidden rounded-full bg-slate-200">
          {fotoUrl ? (
            <img src={fotoUrl} alt={socio.nombre} className="h-full w-full object-cover" />
          ) : (
            <span className="text-[6.5mm] font-bold text-slate-600">{iniciales(socio.nombre)}</span>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[3mm] leading-none font-semibold tracking-wide text-slate-500 uppercase">
            Socio Nº {socio.numeroSocio ?? "S/N"}
          </p>
          <p className="mt-[1.4mm] truncate text-[4.6mm] leading-tight font-bold">{socio.nombre}</p>
          <p className="mt-[1.2mm] text-[3.5mm] leading-tight text-slate-600">
            {socio.dni ? `DNI ${socio.dni}` : "Sin DNI"}
          </p>
        </div>
      </div>

      <div className="relative mt-auto flex flex-wrap gap-[1.5mm]">
        {areas.length === 0 ? (
          <span className="rounded-full bg-slate-100 px-[2.5mm] py-[1mm] text-[2.8mm] font-semibold text-slate-500">
            Sin membresías
          </span>
        ) : (
          areas.map((area) => <AreaBadge key={area} area={area} />)
        )}
      </div>
    </div>
  );
}
