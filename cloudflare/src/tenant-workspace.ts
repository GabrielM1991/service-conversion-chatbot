import { DurableObject } from "cloudflare:workers";

import type { Env, KnowledgeMetadata, WhatsappMessageReceived } from "./types";

export class TenantWorkspace extends DurableObject<Env> {
  private readonly sql: SqlStorage;
  private readonly storage: DurableObjectStorage;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.storage = ctx.storage;
    this.sql = ctx.storage.sql;
    this.sql.exec(`
      CREATE TABLE IF NOT EXISTS processed_messages (
        message_id TEXT PRIMARY KEY,
        processed_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        customer_phone TEXT NOT NULL,
        direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
        body TEXT NOT NULL,
        created_at TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS ix_messages_phone_created
        ON messages(customer_phone, created_at);
      CREATE TABLE IF NOT EXISTS knowledge_sources (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        object_key TEXT NOT NULL UNIQUE,
        content_type TEXT NOT NULL,
        characters INTEGER NOT NULL,
        chunks INTEGER NOT NULL,
        created_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS appointments (
        id TEXT PRIMARY KEY,
        customer_phone TEXT NOT NULL,
        service TEXT NOT NULL,
        starts_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'cancelled')),
        created_at TEXT NOT NULL
      );
      CREATE UNIQUE INDEX IF NOT EXISTS uq_appointments_confirmed_slot
        ON appointments(starts_at) WHERE status IN ('pending', 'confirmed');
    `);
  }

  async processMessage(message: WhatsappMessageReceived): Promise<{ duplicate: boolean }> {
    let duplicate = false;
    this.storage.transactionSync(() => {
      const inserted = this.sql.exec(
        "INSERT OR IGNORE INTO processed_messages (message_id, processed_at) VALUES (?, ?)",
        message.messageId,
        new Date().toISOString(),
      );
      if (inserted.rowsWritten === 0) {
        duplicate = true;
        return;
      }
      this.sql.exec(
        `INSERT INTO messages (id, customer_phone, direction, body, created_at)
         VALUES (?, ?, 'inbound', ?, ?)`,
        message.messageId,
        message.fromPhone,
        message.text,
        message.receivedAt,
      );
    });
    return { duplicate };
  }

  async addKnowledge(source: KnowledgeMetadata): Promise<void> {
    this.sql.exec(
      `INSERT INTO knowledge_sources
       (id, title, object_key, content_type, characters, chunks, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      source.id,
      source.title,
      source.objectKey,
      source.contentType,
      source.characters,
      source.chunks,
      source.createdAt,
    );
  }

  async summary(): Promise<Record<string, number>> {
    const message = this.sql.exec("SELECT COUNT(*) AS count FROM messages").toArray()[0];
    const knowledge = this.sql
      .exec("SELECT COUNT(*) AS count FROM knowledge_sources")
      .toArray()[0];
    const appointments = this.sql
      .exec("SELECT COUNT(*) AS count FROM appointments")
      .toArray()[0];
    return {
      messages: Number(message?.count ?? 0),
      knowledgeSources: Number(knowledge?.count ?? 0),
      appointments: Number(appointments?.count ?? 0),
    };
  }
}
