declare const __CLIENT_BUILD__: boolean | undefined;
declare const __DATABASE_URL__: string | undefined;

/** True only in the packaged client installer (tauri build). */
export const CLIENT_BUILD = typeof __CLIENT_BUILD__ !== "undefined" && __CLIENT_BUILD__ === true;

/** Baked Supabase URL (client build) or "" (dev/web). Never logged. */
export const DATABASE_URL = typeof __DATABASE_URL__ === "string" ? __DATABASE_URL__ : "";
