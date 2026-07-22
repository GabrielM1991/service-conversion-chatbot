import { extractWhatsappMessages } from "./events";
import {
  ingestTextKnowledge,
  searchKnowledge,
  validateKnowledgeInput,
} from "./knowledge";
import { isAdminRequest, isValidIdentifier, verifyMetaSignature } from "./security";
import { TenantWorkspace } from "./tenant-workspace";
import type { Env, WhatsappMessageReceived } from "./types";

export { TenantWorkspace };

function json(payload: unknown, status = 200): Response {
  return Response.json(payload, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

function errorResponse(error: unknown, env: Env): Response {
  const message =
    env.APP_ENV === "development" && error instanceof Error ? error.message : "Error interno";
  console.error("ServiceFlow Worker error", error);
  return json({ detail: message }, 500);
}

function tenantWorkspace(env: Env, tenantId: string): DurableObjectStub<TenantWorkspace> {
  return env.TENANT_WORKSPACE.getByName(tenantId);
}

async function activeTenant(env: Env, tenantId: string): Promise<boolean> {
  const tenant = await env.GLOBAL_DB.prepare(
    "SELECT id FROM tenants WHERE id = ? AND active = 1",
  )
    .bind(tenantId)
    .first();
  return tenant !== null;
}

async function requireAdmin(request: Request, env: Env): Promise<Response | null> {
  return isAdminRequest(request, env.ADMIN_API_TOKEN)
    ? null
    : json({ detail: "No autorizado" }, 401);
}

async function createTenant(request: Request, env: Env): Promise<Response> {
  const denied = await requireAdmin(request, env);
  if (denied) return denied;
  const payload = (await request.json()) as Record<string, unknown>;
  const tenantId = typeof payload.id === "string" ? payload.id.trim() : "";
  const name = typeof payload.name === "string" ? payload.name.trim() : "";
  if (!isValidIdentifier(tenantId) || name.length < 2 || name.length > 160) {
    return json({ detail: "ID o nombre de empresa inválido" }, 400);
  }
  await env.GLOBAL_DB.prepare(
    `INSERT INTO tenants (id, name, active) VALUES (?, ?, 1)
     ON CONFLICT(id) DO UPDATE SET name = excluded.name, active = 1`,
  )
    .bind(tenantId, name)
    .run();
  await tenantWorkspace(env, tenantId).summary();
  await env.GLOBAL_DB.prepare(
    "INSERT INTO audit_events (id, tenant_id, action, metadata) VALUES (?, ?, ?, ?)",
  )
    .bind(crypto.randomUUID(), tenantId, "tenant.upserted", JSON.stringify({ name }))
    .run();
  return json({ id: tenantId, name, status: "ready" }, 201);
}

async function verifyWhatsappWebhook(
  request: Request,
  env: Env,
  tenantId: string,
): Promise<Response> {
  if (!(await activeTenant(env, tenantId))) return json({ detail: "Empresa no encontrada" }, 404);
  const url = new URL(request.url);
  const mode = url.searchParams.get("hub.mode");
  const token = url.searchParams.get("hub.verify_token");
  const challenge = url.searchParams.get("hub.challenge");
  if (mode !== "subscribe" || token !== env.WHATSAPP_VERIFY_TOKEN || !challenge) {
    return json({ detail: "Verificación rechazada" }, 403);
  }
  return new Response(challenge, { status: 200 });
}

async function receiveWhatsappWebhook(
  request: Request,
  env: Env,
  tenantId: string,
): Promise<Response> {
  const body = await request.arrayBuffer();
  const signatureValid = await verifyMetaSignature(
    body,
    request.headers.get("X-Hub-Signature-256"),
    env.META_APP_SECRET,
  );
  if (!signatureValid) return json({ detail: "Firma de Meta inválida" }, 401);
  if (!(await activeTenant(env, tenantId))) return json({ detail: "Empresa no encontrada" }, 404);
  let payload: unknown;
  try {
    payload = JSON.parse(new TextDecoder().decode(body));
  } catch {
    return json({ detail: "JSON inválido" }, 400);
  }
  const messages = extractWhatsappMessages(payload, tenantId);
  for (let start = 0; start < messages.length; start += 100) {
    await env.MESSAGE_QUEUE.sendBatch(
      messages.slice(start, start + 100).map((message) => ({ body: message })),
    );
  }
  return json({ status: "accepted", queued: messages.length });
}

async function addKnowledge(
  request: Request,
  env: Env,
  tenantId: string,
): Promise<Response> {
  const denied = await requireAdmin(request, env);
  if (denied) return denied;
  if (!(await activeTenant(env, tenantId))) return json({ detail: "Empresa no encontrada" }, 404);
  let input;
  try {
    input = validateKnowledgeInput(await request.json());
  } catch (error) {
    return json({ detail: error instanceof Error ? error.message : "Payload inválido" }, 400);
  }
  const metadata = await ingestTextKnowledge(env, tenantId, input);
  try {
    await tenantWorkspace(env, tenantId).addKnowledge(metadata);
  } catch (error) {
    await Promise.allSettled([
      env.KNOWLEDGE_BUCKET.delete(metadata.objectKey),
      env.KNOWLEDGE_INDEX.deleteByIds(
        Array.from({ length: metadata.chunks }, (_, index) => `${metadata.id}-${index}`),
      ),
    ]);
    throw error;
  }
  return json(metadata, 201);
}

async function queryKnowledge(
  request: Request,
  env: Env,
  tenantId: string,
): Promise<Response> {
  const denied = await requireAdmin(request, env);
  if (denied) return denied;
  if (!(await activeTenant(env, tenantId))) return json({ detail: "Empresa no encontrada" }, 404);
  const payload = (await request.json()) as Record<string, unknown>;
  const query = typeof payload.query === "string" ? payload.query.trim() : "";
  if (query.length < 2 || query.length > 2_000) return json({ detail: "Consulta inválida" }, 400);
  return json({ matches: await searchKnowledge(env, tenantId, query) });
}

async function tenantSummary(request: Request, env: Env, tenantId: string): Promise<Response> {
  const denied = await requireAdmin(request, env);
  if (denied) return denied;
  if (!(await activeTenant(env, tenantId))) return json({ detail: "Empresa no encontrada" }, 404);
  return json({ tenantId, ...(await tenantWorkspace(env, tenantId).summary()) });
}

async function handleFetch(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/") {
    return json({ service: "ServiceFlow Cloudflare", version: "0.1.0" });
  }
  if (request.method === "GET" && url.pathname === "/health") {
    await env.GLOBAL_DB.prepare("SELECT 1 AS ok").first();
    return json({ status: "ok", runtime: "cloudflare-workers", storage: "d1+durable-objects+r2" });
  }
  if (request.method === "POST" && url.pathname === "/internal/tenants") {
    return createTenant(request, env);
  }

  const webhook = url.pathname.match(/^\/webhooks\/whatsapp\/([A-Za-z0-9_-]{2,80})$/);
  if (webhook?.[1] && request.method === "GET") {
    return verifyWhatsappWebhook(request, env, webhook[1]);
  }
  if (webhook?.[1] && request.method === "POST") {
    return receiveWhatsappWebhook(request, env, webhook[1]);
  }

  const knowledge = url.pathname.match(
    /^\/api\/tenants\/([A-Za-z0-9_-]{2,80})\/knowledge\/text$/,
  );
  if (knowledge?.[1] && request.method === "POST") {
    return addKnowledge(request, env, knowledge[1]);
  }
  const search = url.pathname.match(
    /^\/api\/tenants\/([A-Za-z0-9_-]{2,80})\/knowledge\/search$/,
  );
  if (search?.[1] && request.method === "POST") {
    return queryKnowledge(request, env, search[1]);
  }
  const summary = url.pathname.match(/^\/api\/tenants\/([A-Za-z0-9_-]{2,80})\/summary$/);
  if (summary?.[1] && request.method === "GET") {
    return tenantSummary(request, env, summary[1]);
  }
  return json({ detail: "Ruta no encontrada" }, 404);
}

async function handleQueue(
  batch: MessageBatch<WhatsappMessageReceived>,
  env: Env,
): Promise<void> {
  for (const message of batch.messages) {
    try {
      const event = message.body;
      if (event.eventType !== "WhatsappMessageReceived" || !isValidIdentifier(event.tenantId)) {
        console.warn("Evento descartado por formato inválido", { messageId: message.id });
        message.ack();
        continue;
      }
      const result = await tenantWorkspace(env, event.tenantId).processMessage(event);
      console.log("Evento procesado", {
        tenantId: event.tenantId,
        providerMessageId: event.messageId,
        duplicate: result.duplicate,
      });
      message.ack();
    } catch (error) {
      console.error("Fallo al procesar evento", { queueMessageId: message.id, error });
      message.retry();
    }
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    try {
      return await handleFetch(request, env);
    } catch (error) {
      return errorResponse(error, env);
    }
  },
  async queue(batch: MessageBatch<WhatsappMessageReceived>, env: Env): Promise<void> {
    await handleQueue(batch, env);
  },
  async scheduled(_controller: ScheduledController, env: Env): Promise<void> {
    await env.GLOBAL_DB.prepare("DELETE FROM auth_sessions WHERE expires_at <= datetime('now')").run();
  },
} satisfies ExportedHandler<Env, WhatsappMessageReceived>;
