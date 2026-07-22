import type { TenantWorkspace } from "./tenant-workspace";

export interface Env {
  APP_ENV: string;
  EMBEDDING_MODEL: string;
  ADMIN_API_TOKEN: string;
  META_APP_SECRET: string;
  WHATSAPP_VERIFY_TOKEN: string;
  GLOBAL_DB: D1Database;
  TENANT_WORKSPACE: DurableObjectNamespace<TenantWorkspace>;
  MESSAGE_QUEUE: Queue<WhatsappMessageReceived>;
  KNOWLEDGE_INDEX: VectorizeIndex;
  AI: Ai;
}

export interface WhatsappMessageReceived {
  eventType: "WhatsappMessageReceived";
  tenantId: string;
  messageId: string;
  fromPhone: string;
  text: string;
  receivedAt: string;
}

export interface KnowledgeMetadata {
  id: string;
  tenantId: string;
  title: string;
  contentType: string;
  characters: number;
  chunks: number;
  createdAt: string;
}

export interface KnowledgeTextInput {
  title: string;
  text: string;
}

export interface KnowledgeVectorMatch {
  id: string;
  score: number;
  title: string | null;
}

export interface KnowledgeExcerpt {
  title: string;
  excerpt: string;
}
