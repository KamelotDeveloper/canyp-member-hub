/**
 * Browser download helpers for the import flow.
 *
 * Kept dependency-free: build a Blob and trigger an anchor download so the
 * user can persist error CSVs or execute logs without server round-trips.
 */

/**
 * Detect the Tauri desktop shell at runtime (same check used by `api.ts`).
 * Tauri v2 exposes `window.__TAURI_INTERNALS__` only inside the WebView;
 * in browser dev (Vite proxy) it is absent and we fall back to anchor download.
 */
function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

function tauriInvoke(cmd: string, args: Record<string, unknown>): Promise<unknown> {
  const internals = (window as unknown as { __TAURI_INTERNALS__: { invoke: unknown } })
    .__TAURI_INTERNALS__;
  const invoke = internals.invoke as (c: string, a: Record<string, unknown>) => Promise<unknown>;
  return invoke(cmd, args);
}

/** Encode a byte array as base64 (chunked to avoid argument-count limits). */
function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

async function triggerDownload(blob: Blob, filename: string): Promise<void> {
  if (inTauri()) {
    // Desktop: write directly into the user's Downloads\canyp folder via a
    // native command (the anchor + Blob approach is silent in WebView2).
    const bytes = new Uint8Array(await blob.arrayBuffer());
    try {
      const path = (await tauriInvoke("save_export", {
        filename,
        data: bytesToBase64(bytes),
      })) as string;
      console.info(`Export guardado en ${path}`);
      return;
    } catch (err) {
      console.error("save_export failed", err);
      // Fall through to the browser-style download so the user still gets it.
    }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Download a record array as CSV with the given headers (in order). */
export function downloadCsv(filename: string, headers: string[], rows: Record<string, unknown>[]) {
  const esc = (v: unknown) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [
    headers.map(esc).join(","),
    ...rows.map((r) => headers.map((h) => esc(r[h])).join(",")),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
  triggerDownload(blob, filename);
}

/** Download a JSON-serializable value as a pretty-printed .json file. */
export function downloadJson(filename: string, value: unknown) {
  const blob = new Blob([JSON.stringify(value, null, 2)], {
    type: "application/json;charset=utf-8;",
  });
  triggerDownload(blob, filename);
}

/** Trigger a browser download for a Blob (e.g. the XLSX template). */
export function downloadBlob(blob: Blob, filename: string) {
  triggerDownload(blob, filename);
}
