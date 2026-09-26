import { useEffect, useState } from "react";
import { getSocioFoto } from "./api";

/**
 * Object-URL cache for socio photos (carnet print).
 *
 * Blob URLs are cheap and the payload is at most 5 MB (backed down to ~800px
 * JPEG), so one URL per socio is kept for the whole session and reused when
 * the print sheet reopens — no refetch, no flicker. `clearFotosCache` revokes
 * every URL (used after `useSubirFoto` succeeds, since `tieneFoto` flipped).
 */

const cache = new Map<string, string>();
const inflight = new Map<string, Promise<string | null>>();

/** Revoke all cached photo object URLs (call after the foto changed). */
export function clearFotosCache(): void {
  for (const url of cache.values()) {
    if (typeof URL !== "undefined") URL.revokeObjectURL(url);
  }
  cache.clear();
  inflight.clear();
}

async function fotoUrl(socioId: string): Promise<string | null> {
  const cached = cache.get(socioId);
  if (cached) return cached;
  const pending = inflight.get(socioId);
  if (pending) return pending;
  const p = getSocioFoto(socioId)
    .then((blob) => {
      const url = URL.createObjectURL(blob);
      cache.set(socioId, url);
      return url;
    })
    .catch(() => null)
    .finally(() => {
      inflight.delete(socioId);
    });
  inflight.set(socioId, p);
  return p;
}

/**
 * Resolve `GET /api/socios/{id}/foto` into object URLs for a set of socios.
 * `urls[id]` is `undefined` when not requested, `null` when the fetch failed
 * (caller falls back to initials), or a stable object URL when cached.
 */
export function useFotos(socioIds: string[]): {
  urls: Record<string, string | null>;
  loading: boolean;
} {
  const [urls, setUrls] = useState<Record<string, string | null>>({});
  const [loading, setLoading] = useState(socioIds.length > 0);
  const key = socioIds.join(",");

  useEffect(() => {
    const list = key ? key.split(",") : [];
    let cancelled = false;
    setLoading(list.length > 0);
    void Promise.all(
      list.map(async (id) => {
        const url = await fotoUrl(id);
        if (!cancelled) setUrls((prev) => (prev[id] === url ? prev : { ...prev, [id]: url }));
      }),
    ).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [key]);

  return { urls, loading };
}
