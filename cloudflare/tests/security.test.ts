import { describe, expect, it } from "vitest";

import {
  bearerToken,
  constantTimeEqual,
  isAdminRequest,
  isValidIdentifier,
  verifyMetaSignature,
} from "../src/security";

function hex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

describe("security", () => {
  it("accepts only safe tenant identifiers", () => {
    expect(isValidIdentifier("ClinicaDental_01")).toBe(true);
    expect(isValidIdentifier("a")).toBe(false);
    expect(isValidIdentifier("tenant/other")).toBe(false);
  });

  it("extracts and compares bearer tokens", () => {
    const request = new Request("https://example.test", {
      headers: { Authorization: "Bearer secret-token" },
    });
    expect(bearerToken(request)).toBe("secret-token");
    expect(constantTimeEqual("same", "same")).toBe(true);
    expect(constantTimeEqual("same", "different")).toBe(false);
    expect(isAdminRequest(request, "secret-token")).toBe(true);
  });

  it("verifies the HMAC signature sent by Meta", async () => {
    const body = new TextEncoder().encode('{"message":"hola"}');
    const secret = "meta-app-secret";
    const key = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"],
    );
    const signature = await crypto.subtle.sign("HMAC", key, body);
    expect(await verifyMetaSignature(body.buffer, `sha256=${hex(signature)}`, secret)).toBe(true);
    expect(await verifyMetaSignature(body.buffer, `sha256=${"0".repeat(64)}`, secret)).toBe(false);
  });
});
