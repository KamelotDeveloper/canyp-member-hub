/**
 * Tests del estado de pago a medio camino.
 *
 * Esto es lo que hace que volver del navegador externo no deje al usuario con la
 * app bloqueada: el `preference_id` tiene que sobrevivir al remount, expirar, y
 * no romper cuando localStorage no está.
 */

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  PAGO_PENDIENTE_KEY,
  guardarPagoPendiente,
  leerPagoPendiente,
  limpiarPagoPendiente,
} from "../pago-pendiente";

describe("pago pendiente", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("guarda y relee el preference_id con su plan", () => {
    guardarPagoPendiente("3001", "canyp_1_mes");
    const pendiente = leerPagoPendiente();
    expect(pendiente?.preference_id).toBe("3001");
    expect(pendiente?.plan).toBe("canyp_1_mes");
  });

  it("no hay pago pendiente al empezar limpio", () => {
    expect(leerPagoPendiente()).toBeNull();
  });

  it("se limpia cuando el pago se resuelve", () => {
    guardarPagoPendiente("3001");
    limpiarPagoPendiente();
    expect(leerPagoPendiente()).toBeNull();
  });

  it("un pago viejo se ignora y se descarta", () => {
    // Sin este tope, un preference_id olvidado haría consultar a MercadoPago en
    // cada arranque, para siempre.
    const haceTresHoras = Date.now() - 3 * 60 * 60 * 1000;
    window.localStorage.setItem(
      PAGO_PENDIENTE_KEY,
      JSON.stringify({ preference_id: "3001", iniciado: haceTresHoras }),
    );

    expect(leerPagoPendiente()).toBeNull();
    expect(window.localStorage.getItem(PAGO_PENDIENTE_KEY)).toBeNull();
  });

  it("un pago reciente se respeta", () => {
    window.localStorage.setItem(
      PAGO_PENDIENTE_KEY,
      JSON.stringify({ preference_id: "3001", iniciado: Date.now() - 60_000 }),
    );
    expect(leerPagoPendiente()?.preference_id).toBe("3001");
  });

  it.each([
    ["json roto", "{no es json"],
    ["no es objeto", '"un string"'],
    ["sin preference_id", JSON.stringify({ iniciado: Date.now() })],
    ["preference_id vacío", JSON.stringify({ preference_id: "", iniciado: Date.now() })],
    ["sin iniciado", JSON.stringify({ preference_id: "3001" })],
  ])("datos corruptos (%s) devuelven null en vez de romper la app", (_caso, crudo) => {
    window.localStorage.setItem(PAGO_PENDIENTE_KEY, crudo);
    expect(leerPagoPendiente()).toBeNull();
  });

  it("guardar sin plan es válido: el plan es solo informativo", () => {
    guardarPagoPendiente("3001");
    const pendiente = leerPagoPendiente();
    expect(pendiente?.preference_id).toBe("3001");
    expect(pendiente?.plan).toBeUndefined();
  });
});
