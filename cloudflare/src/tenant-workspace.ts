import { DurableObject } from "cloudflare:workers";

import type {
  Env,
  KnowledgeExcerpt,
  KnowledgeMetadata,
  WhatsappMessageReceived,
} from "./types";

export class TenantWorkspace extends DurableObject<Env> {
  private readonly sql: SqlStorage;
  private readonly storage: DurableObjectStorage;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.storage = ctx.storage;
    this.sql = ctx.storage.sql;
    this.sql.exec(`
      PRAGMA foreign_keys = ON;
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
    this.migrateKnowledgeSchema();
    this.sql.exec(`
      CREATE TABLE IF NOT EXISTS knowledge_sources (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        content_type TEXT NOT NULL,
        characters INTEGER NOT NULL,
        chunks INTEGER NOT NULL,
        created_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS knowledge_chunks (
        id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        content TEXT NOT NULL,
        UNIQUE(source_id, position)
      );
      CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_source
        ON knowledge_chunks(source_id, position);
    `);
  }

  private migrateKnowledgeSchema(): void {
    const columns = this.sql.exec("PRAGMA table_info(knowledge_sources)").toArray();
    if (!columns.some((column) => column.name === "object_key")) return;
    this.storage.transactionSync(() => {
      this.sql.exec(`
        ALTER TABLE knowledge_sources RENAME TO knowledge_sources_r2_legacy;
        CREATE TABLE knowledge_sources (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          content_type TEXT NOT NULL,
          characters INTEGER NOT NULL,
          chunks INTEGER NOT NULL,
          created_at TEXT NOT NULL
        );
        INSERT INTO knowledge_sources
          (id, title, content_type, characters, chunks, created_at)
        SELECT id, title, content_type, characters, chunks, created_at
        FROM knowledge_sources_r2_legacy;
        DROP TABLE knowledge_sources_r2_legacy;
      `);
    });
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

  async addKnowledge(source: KnowledgeMetadata, chunks: string[]): Promise<void> {
    if (chunks.length !== source.chunks) throw new Error("Cantidad de fragmentos inválida");
    this.storage.transactionSync(() => {
      this.sql.exec(
        `INSERT INTO knowledge_sources
         (id, title, content_type, characters, chunks, created_at)
         VALUES (?, ?, ?, ?, ?, ?)`,
        source.id,
        source.title,
        source.contentType,
        source.characters,
        source.chunks,
        source.createdAt,
      );
      chunks.forEach((content, position) => {
        this.sql.exec(
          `INSERT INTO knowledge_chunks (id, source_id, position, content)
           VALUES (?, ?, ?, ?)`,
          `${source.id}-${position}`,
          source.id,
          position,
          content,
        );
      });
    });
  }

  async knowledgeExcerpts(ids: string[]): Promise<Record<string, KnowledgeExcerpt>> {
    if (!ids.length) return {};
    const safeIds = ids.slice(0, 20);
    const placeholders = safeIds.map(() => "?").join(", ");
    const rows = this.sql
      .exec(
        `SELECT c.id, c.content, s.title
         FROM knowledge_chunks c
         JOIN knowledge_sources s ON s.id = c.source_id
         WHERE c.id IN (${placeholders})`,
        ...safeIds,
      )
      .toArray();
    return Object.fromEntries(
      rows.map((row) => [
        String(row.id),
        { title: String(row.title), excerpt: String(row.content).slice(0, 2_000) },
      ]),
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
