import type {
  Env,
  KnowledgeMetadata,
  KnowledgeTextInput,
  KnowledgeVectorMatch,
} from "./types";

const MAX_TEXT_CHARACTERS = 100_000;
const CHUNK_CHARACTERS = 4_000;

export function chunkText(text: string, chunkSize = CHUNK_CHARACTERS): string[] {
  const normalized = text.replace(/\r\n/g, "\n").trim();
  if (!normalized) return [];
  const chunks: string[] = [];
  for (let start = 0; start < normalized.length; start += chunkSize) {
    chunks.push(normalized.slice(start, start + chunkSize));
  }
  return chunks;
}

export function validateKnowledgeInput(value: unknown): KnowledgeTextInput {
  if (!value || typeof value !== "object") throw new Error("Payload inválido");
  const candidate = value as Record<string, unknown>;
  const title = typeof candidate.title === "string" ? candidate.title.trim() : "";
  const text = typeof candidate.text === "string" ? candidate.text.trim() : "";
  if (title.length < 2 || title.length > 180) throw new Error("Título inválido");
  if (text.length < 3 || text.length > MAX_TEXT_CHARACTERS) {
    throw new Error("El texto debe contener entre 3 y 100.000 caracteres");
  }
  return { title, text };
}

async function embeddings(env: Env, chunks: string[]): Promise<number[][]> {
  const result = (await env.AI.run(env.EMBEDDING_MODEL, { text: chunks })) as {
    data?: number[][];
  };
  if (!result.data || result.data.length !== chunks.length) {
    throw new Error("Workers AI no devolvió embeddings válidos");
  }
  return result.data;
}

export async function ingestTextKnowledge(
  env: Env,
  tenantId: string,
  input: KnowledgeTextInput,
): Promise<{ metadata: KnowledgeMetadata; chunks: string[] }> {
  const id = crypto.randomUUID();
  const chunks = chunkText(input.text);
  const vectors = await embeddings(env, chunks);
  const createdAt = new Date().toISOString();

  const vectorIds = chunks.map((_, index) => `${id}-${index}`);

  try {
    await env.KNOWLEDGE_INDEX.upsert(
      vectors.map((values, index) => ({
        id: vectorIds[index]!,
        values,
        metadata: { tenantId, title: input.title, knowledgeId: id, chunk: index },
      })),
    );
  } catch (error) {
    await env.KNOWLEDGE_INDEX.deleteByIds(vectorIds).catch(() => undefined);
    throw error;
  }

  return {
    metadata: {
      id,
      tenantId,
      title: input.title,
      contentType: "text/plain",
      characters: input.text.length,
      chunks: chunks.length,
      createdAt,
    },
    chunks,
  };
}

export async function searchKnowledge(
  env: Env,
  tenantId: string,
  query: string,
): Promise<KnowledgeVectorMatch[]> {
  const [queryVector] = await embeddings(env, [query]);
  if (!queryVector) return [];
  const result = await env.KNOWLEDGE_INDEX.query(queryVector, {
    topK: 5,
    returnMetadata: "all",
    filter: { tenantId: { $eq: tenantId } },
  });
  return result.matches.map((match) => {
    const metadata = (match.metadata ?? {}) as Record<string, unknown>;
    return {
      id: match.id,
      score: match.score,
      title: typeof metadata.title === "string" ? metadata.title : null,
    };
  });
}
