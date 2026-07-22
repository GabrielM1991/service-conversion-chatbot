import { describe, expect, it } from "vitest";

import { extractWhatsappMessages } from "../src/events";

describe("extractWhatsappMessages", () => {
  it("accepts the simple local payload", () => {
    const messages = extractWhatsappMessages(
      { message_id: "wamid-1", from_phone: "+584121234567", text: "Quiero una cita" },
      "ClinicaDental_01",
    );
    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({
      tenantId: "ClinicaDental_01",
      messageId: "wamid-1",
      text: "Quiero una cita",
    });
  });

  it("extracts text messages from a Meta webhook", () => {
    const messages = extractWhatsappMessages(
      {
        entry: [
          {
            changes: [
              {
                value: {
                  messages: [
                    {
                      id: "wamid-meta-1",
                      from: "584121234567",
                      timestamp: "1784736000",
                      type: "text",
                      text: { body: "Necesito información" },
                    },
                  ],
                },
              },
            ],
          },
        ],
      },
      "tenant-01",
    );
    expect(messages).toEqual([
      {
        eventType: "WhatsappMessageReceived",
        tenantId: "tenant-01",
        messageId: "wamid-meta-1",
        fromPhone: "584121234567",
        text: "Necesito información",
        receivedAt: "2026-07-22T16:00:00.000Z",
      },
    ]);
  });

  it("ignores non-text messages", () => {
    const messages = extractWhatsappMessages(
      { entry: [{ changes: [{ value: { messages: [{ id: "1", from: "2", image: {} }] } }] }] },
      "tenant-01",
    );
    expect(messages).toEqual([]);
  });
});
