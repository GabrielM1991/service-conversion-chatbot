import { describe, expect, it } from "vitest";

import { AI_MODEL_OPTIONS, validateIntegrationInput } from "../src/integrations";

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

  it("offers supported model choices for every provider including Gemini", () => {
    expect(AI_MODEL_OPTIONS.openai.map((model) => model.value)).toContain("gpt-5.6-terra");
    expect(AI_MODEL_OPTIONS.anthropic.map((model) => model.value)).toContain("claude-sonnet-5");
    expect(AI_MODEL_OPTIONS.google.map((model) => model.value)).toContain("gemini-3.6-flash");
    expect(
      validateIntegrationInput({ aiProvider: "google", aiModel: "gemini-3.6-flash" }),
    ).toMatchObject({ aiProvider: "google" });
  });
});
