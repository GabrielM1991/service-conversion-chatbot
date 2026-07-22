import { describe, expect, it } from "vitest";

import { dashboardHtml, loginHtml, setupHtml } from "../src/ui";

describe("tenant dashboard HTML", () => {
  it("renders the login and one-time setup surfaces", () => {
    expect(loginHtml("nonce-test")).toContain("Entrar al panel");
    expect(setupHtml("nonce-test")).toContain("Crear acceso seguro");
    expect(setupHtml("nonce-test")).toContain('nonce="nonce-test"');
  });

  it("renders the tenant controls without embedding credentials", () => {
    const html = dashboardHtml("nonce-test");
    expect(html).toContain("Configuración del bot");
    expect(html).toContain("Base de conocimiento");
    expect(html).toContain("Probar conocimiento");
    expect(html).not.toContain("ADMIN_API_TOKEN");
  });
});
