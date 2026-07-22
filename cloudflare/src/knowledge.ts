import type { Env, KnowledgeMetadata, KnowledgeTextInput } from "./types";

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
): Promise<KnowledgeMetadata> {
  const id = crypto.randomUUID();
  const objectKey = `tenants/${tenantId}/knowledge/${id}.txt`;
  const chunks = chunkText(input.text);
  const vectors = await embeddings(env, chunks);
  const createdAt = new Date().toISOString();

  await env.KNOWLEDGE_BUCKET.put(objectKey, input.text, {
    httpMetadata: { contentType: "text/plain; charset=utf-8" },
    customMetadata: { tenantId, title: input.title, knowledgeId: id },
  });

  try {
    await env.KNOWLEDGE_INDEX.upsert(
      vectors.map((values, index) => ({
        id: `${id}-${index}`,
        values,
        metadata: { tenantId, title: input.title, objectKey, chunk: index },
      })),
    );
  } catch (error) {
    await env.KNOWLEDGE_BUCKET.delete(objectKey);
    throw error;
  }

  return {
    id,
    tenantId,
    title: input.title,
    objectKey,
    contentType: "text/plain",
    characters: input.text.length,
    chunks: chunks.length,
    createdAt,
  };
}

export async function searchKnowledge(
  env: Env,
  tenantId: string,
  query: string,
): Promise<Array<Record<string, unknown>>> {
  const [queryVector] = await embeddings(env, [query]);
  if (!queryVector) return [];
  const result = await env.KNOWLEDGE_INDEX.query(queryVector, {
    topK: 5,
    returnMetadata: "all",
    filter: { tenantId: { $eq: tenantId } },
  });
  const responses: Array<Record<string, unknown>> = [];
  for (const match of result.matches) {
    const metadata = (match.metadata ?? {}) as Record<string, unknown>;
    const objectKey = typeof metadata.objectKey === "string" ? metadata.objectKey : null;
    const object = objectKey ? await env.KNOWLEDGE_BUCKET.get(objectKey) : null;
    responses.push({
      id: match.id,
      score: match.score,
      title: metadata.title,
      excerpt: object ? (await object.text()).slice(0, 2_000) : null,
    });
  }
  return responses;
}
