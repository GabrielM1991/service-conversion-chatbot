import { describe, expect, it } from "vitest";

import { clearSessionCookie, sessionCookie, validEmail } from "../src/auth";

describe("dashboard authentication helpers", () => {
  it("validates normalized business email shapes", () => {
    expect(validEmail("owner@example.com")).toBe(true);
    expect(validEmail("missing-at.example.com")).toBe(false);
    expect(validEmail("a".repeat(250) + "@example.com")).toBe(false);
  });

  it("creates hardened session cookies", () => {
    const cookie = sessionCookie("private-token");
    expect(cookie).toContain("serviceflow_session=private-token");
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("Secure");
    expect(cookie).toContain("SameSite=Strict");
  });

  it("clears the same cookie path", () => {
    expect(clearSessionCookie()).toContain("Max-Age=0");
    expect(clearSessionCookie()).toContain("Path=/");
  });
});
