import { describe, expect, it } from "vitest";

import { validateIntegrationInput } from "../src/integrations";

describe("tenant integration validation", () => {
  it("accepts supported providers and Meta identifiers", () => {
    expect(
      validateIntegrationInput({
        whatsappEnabled: true,
        metaPhoneNumberId: "123456789",
        metaWabaId: "987654321",
        metaGraphVersion: "v25.0",
        aiProvider: "openai",
        aiModel: "gpt-5.6-luna",
      }),
    ).toMatchObject({ aiProvider: "openai", whatsappEnabled: true });
  });

  it("rejects unsupported providers and invalid Graph versions", () => {
    expect(() => validateIntegrationInput({ aiProvider: "unknown", aiModel: "model" })).toThrow(
      "Proveedor",
    );
    expect(() =>
      validateIntegrationInput({ aiProvider: "workers-ai", aiModel: "model", metaGraphVersion: "latest" }),
    ).toThrow("Graph API");
  });
});
