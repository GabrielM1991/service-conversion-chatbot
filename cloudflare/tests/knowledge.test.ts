import { describe, expect, it, vi } from "vitest";

import { chunkText, ingestTextKnowledge, searchKnowledge, validateKnowledgeInput } from "../src/knowledge";
import type { Env } from "../src/types";

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

  it("indexes text without requiring object storage", async () => {
    const upsert = vi.fn().mockResolvedValue(undefined);
    const env = {
      EMBEDDING_MODEL: "test-embedding",
      AI: { run: vi.fn().mockResolvedValue({ data: [[0.1, 0.2]] }) },
      KNOWLEDGE_INDEX: { upsert, deleteByIds: vi.fn() },
    } as unknown as Env;

    const result = await ingestTextKnowledge(env, "tenant-01", {
      title: "Servicios",
      text: "Limpieza dental de 45 minutos",
    });

    expect(result.chunks).toEqual(["Limpieza dental de 45 minutos"]);
    expect(result.metadata).toMatchObject({ tenantId: "tenant-01", chunks: 1 });
    expect(upsert).toHaveBeenCalledWith([
      expect.objectContaining({
        id: `${result.metadata.id}-0`,
        metadata: expect.objectContaining({ tenantId: "tenant-01", knowledgeId: result.metadata.id }),
      }),
    ]);
  });

  it("returns vector references for SQLite excerpt lookup", async () => {
    const env = {
      EMBEDDING_MODEL: "test-embedding",
      AI: { run: vi.fn().mockResolvedValue({ data: [[0.1, 0.2]] }) },
      KNOWLEDGE_INDEX: {
        query: vi.fn().mockResolvedValue({
          matches: [{ id: "source-0", score: 0.93, metadata: { title: "Servicios" } }],
        }),
      },
    } as unknown as Env;

    await expect(searchKnowledge(env, "tenant-01", "limpieza")).resolves.toEqual([
      { id: "source-0", score: 0.93, title: "Servicios" },
    ]);
  });
});
