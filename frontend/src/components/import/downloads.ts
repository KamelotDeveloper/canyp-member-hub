/**
 * Browser download helpers for the import flow.
 *
 * Kept dependency-free: build a Blob and trigger an anchor download so the
 * user can persist error CSVs or execute logs without server round-trips.
 */

function triggerDownload(blob: Blob, filename: string) {
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
