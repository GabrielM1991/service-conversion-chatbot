import type { WhatsappMessageReceived } from "./types";

type JsonRecord = Record<string, unknown>;

function record(value: unknown): JsonRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : null;
}

function string(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function event(
  tenantId: string,
  messageId: string,
  fromPhone: string,
  text: string,
  receivedAt?: string,
): WhatsappMessageReceived {
  return {
    eventType: "WhatsappMessageReceived",
    tenantId,
    messageId,
    fromPhone,
    text,
    receivedAt: receivedAt ?? new Date().toISOString(),
  };
}

export function extractWhatsappMessages(
  payload: unknown,
  tenantId: string,
): WhatsappMessageReceived[] {
  const root = record(payload);
  if (!root) return [];

  const directId = string(root.message_id);
  const directPhone = string(root.from_phone);
  const directText = string(root.text);
  if (directId && directPhone && directText) {
    return [event(tenantId, directId, directPhone, directText)];
  }

  const extracted: WhatsappMessageReceived[] = [];
  const entries = Array.isArray(root.entry) ? root.entry : [];
  for (const entryValue of entries) {
    const entry = record(entryValue);
    const changes = entry && Array.isArray(entry.changes) ? entry.changes : [];
    for (const changeValue of changes) {
      const change = record(changeValue);
      const value = record(change?.value);
      const messages = value && Array.isArray(value.messages) ? value.messages : [];
      for (const messageValue of messages) {
        const message = record(messageValue);
        const textObject = record(message?.text);
        const messageId = string(message?.id);
        const phone = string(message?.from);
        const body = string(textObject?.body);
        if (!messageId || !phone || !body) continue;
        const timestamp = string(message?.timestamp);
        const numericTimestamp = timestamp ? Number(timestamp) : Number.NaN;
        const receivedAt = Number.isFinite(numericTimestamp)
          ? new Date(numericTimestamp * 1000).toISOString()
          : undefined;
        extracted.push(event(tenantId, messageId, phone, body, receivedAt));
      }
    }
  }
  return extracted;
}
