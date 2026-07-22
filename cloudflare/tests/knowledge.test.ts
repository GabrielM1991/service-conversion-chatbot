import { describe, expect, it } from "vitest";

import { chunkText, validateKnowledgeInput } from "../src/knowledge";

describe("knowledge helpers", () => {
  it("normalizes and chunks text", () => {
    expect(chunkText("  abcdef  ", 3)).toEqual(["abc", "def"]);
    expect(chunkText("   ")).toEqual([]);
  });

  it("validates and trims text input", () => {
    expect(validateKnowledgeInput({ title: " Tarifas ", text: " Contenido útil " })).toEqual({
      title: "Tarifas",
      text: "Contenido útil",
    });
  });

  it("rejects invalid or oversized input", () => {
    expect(() => validateKnowledgeInput({ title: "X", text: "ok" })).toThrow();
    expect(() => validateKnowledgeInput({ title: "Documento", text: "a".repeat(100_001) })).toThrow();
  });
});
