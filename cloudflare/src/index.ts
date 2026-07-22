import {
  authenticate,
  clearSessionCookie,
  createOwnerAccess,
  login,
  logout,
  membershipForTenant,
  membershipsForUser,
  validCsrf,
  validEmail,
} from "./auth";
import { extractWhatsappMessages } from "./events";
import {
  ingestTextKnowledge,
  searchKnowledge,
  validateKnowledgeInput,
} from "./knowledge";
import {
  publicIntegrations,
  saveIntegrations,
  testIntegration,
  validateIntegrationInput,
  whatsappSecrets,
} from "./integrations";
import { isAdminRequest, isValidIdentifier, verifyMetaSignature } from "./security";
import { TenantWorkspace } from "./tenant-workspace";
import { dashboardHtml, loginHtml, setupHtml } from "./ui";
import type { Env, WhatsappMessageReceived } from "./types";

export { TenantWorkspace };

function json(payload: unknown, status = 200, headers: HeadersInit = {}): Response {
  return Response.json(payload, {
    status,
    headers: { "Cache-Control": "no-store", ...headers },
  });
}

function html(content: (nonce: string) => string): Response {
  const nonce = crypto.randomUUID();
  return new Response(content(nonce), {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "Content-Security-Policy": `default-src 'self'; script-src 'nonce-${nonce}'; style-src 'nonce-${nonce}'; connect-src 'self'; img-src 'self' data:; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`,
      "Referrer-Policy": "no-referrer",
      "X-Content-Type-Options": "nosniff",
      "X-Frame-Options": "DENY",
    },
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

function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("Origin");
  return !origin || origin === new URL(request.url).origin;
}

async function authorizeTenant(
  request: Request,
  env: Env,
  tenantId: string,
  mutation = false,
): Promise<{ userId: string | null; role: "superadmin" | "owner" | "admin" | "viewer" } | Response> {
  if (isAdminRequest(request, env.ADMIN_API_TOKEN)) return { userId: null, role: "superadmin" };
  const user = await authenticate(request, env);
  if (!user) return json({ detail: "No autorizado" }, 401);
  const membership = await membershipForTenant(env, user.id, tenantId);
  if (!membership) return json({ detail: "Empresa no encontrada" }, 404);
  if (mutation && !validCsrf(request, user)) return json({ detail: "Solicitud inválida" }, 403);
  if (mutation && membership.role === "viewer") {
    return json({ detail: "Tu rol es de solo lectura" }, 403);
  }
  return { userId: user.id, role: membership.role };
}

async function setupOwner(request: Request, env: Env): Promise<Response> {
  if (!sameOrigin(request)) return json({ detail: "Origen no permitido" }, 403);
  const denied = await requireAdmin(request, env);
  if (denied) return denied;
  const payload = (await request.json()) as Record<string, unknown>;
  const tenantId = typeof payload.tenantId === "string" ? payload.tenantId.trim() : "";
  const tenantName = typeof payload.tenantName === "string" ? payload.tenantName.trim() : "";
  const email = typeof payload.email === "string" ? payload.email.trim().toLowerCase() : "";
  if (
    !isValidIdentifier(tenantId) ||
    tenantName.length < 2 ||
    tenantName.length > 160 ||
    !validEmail(email)
  ) {
    return json({ detail: "Datos de empresa o correo inválidos" }, 400);
  }
  try {
    const account = await createOwnerAccess(env, { tenantId, tenantName, email });
    await tenantWorkspace(env, tenantId).summary();
    return json({ tenantId, email, accessKey: account.accessKey }, 201);
  } catch (error) {
    const detail = error instanceof Error ? error.message : "No fue posible crear la cuenta";
    return json({ detail }, 409);
  }
}

async function loginRequest(request: Request, env: Env): Promise<Response> {
  if (!sameOrigin(request)) return json({ detail: "Origen no permitido" }, 403);
  const payload = (await request.json()) as Record<string, unknown>;
  const email = typeof payload.email === "string" ? payload.email : "";
  const accessKey = typeof payload.accessKey === "string" ? payload.accessKey : "";
  const result = await login(env, email, accessKey);
  if (!result) return json({ detail: "Correo o clave de acceso incorrectos" }, 401);
  return json(
    { user: result.user, memberships: result.memberships },
    200,
    { "Set-Cookie": result.cookie },
  );
}

async function sessionRequest(request: Request, env: Env): Promise<Response> {
  const user = await authenticate(request, env);
  if (!user) return json({ detail: "No autorizado" }, 401);
  return json({ user, memberships: await membershipsForUser(env, user.id) });
}

async function logoutRequest(request: Request, env: Env): Promise<Response> {
  const user = await authenticate(request, env);
  if (!user) return json({ status: "ok" }, 200, { "Set-Cookie": clearSessionCookie() });
  if (!validCsrf(request, user)) return json({ detail: "Solicitud inválida" }, 403);
  await logout(request, env);
  return json({ status: "ok" }, 200, { "Set-Cookie": clearSessionCookie() });
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
  const credentials = await whatsappSecrets(env, tenantId);
  if (mode !== "subscribe" || token !== credentials.verifyToken || !challenge) {
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
  const credentials = await whatsappSecrets(env, tenantId);
  const signatureValid = await verifyMetaSignature(
    body,
    request.headers.get("X-Hub-Signature-256"),
    credentials.appSecret,
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
  const access = await authorizeTenant(request, env, tenantId, true);
  if (access instanceof Response) return access;
  if (!(await activeTenant(env, tenantId))) return json({ detail: "Empresa no encontrada" }, 404);
  let input;
  try {
    input = validateKnowledgeInput(await request.json());
  } catch (error) {
    return json({ detail: error instanceof Error ? error.message : "Payload inválido" }, 400);
  }
  const { metadata, chunks } = await ingestTextKnowledge(env, tenantId, input);
  try {
    await tenantWorkspace(env, tenantId).addKnowledge(metadata, chunks);
  } catch (error) {
    await env.KNOWLEDGE_INDEX.deleteByIds(
      Array.from({ length: metadata.chunks }, (_, index) => `${metadata.id}-${index}`),
    ).catch(() => undefined);
    throw error;
  }
  return json(metadata, 201);
}

async function queryKnowledge(
  request: Request,
  env: Env,
  tenantId: string,
): Promise<Response> {
  const access = await authorizeTenant(request, env, tenantId, true);
  if (access instanceof Response) return access;
  if (!(await activeTenant(env, tenantId))) return json({ detail: "Empresa no encontrada" }, 404);
  const payload = (await request.json()) as Record<string, unknown>;
  const query = typeof payload.query === "string" ? payload.query.trim() : "";
  if (query.length < 2 || query.length > 2_000) return json({ detail: "Consulta inválida" }, 400);
  const matches = await searchKnowledge(env, tenantId, query);
  const excerpts = await tenantWorkspace(env, tenantId).knowledgeExcerpts(
    matches.map((match) => match.id),
  );
  return json({
    matches: matches.map((match) => ({
      ...match,
      title: excerpts[match.id]?.title ?? match.title,
      excerpt: excerpts[match.id]?.excerpt ?? null,
    })),
  });
}

async function tenantSummary(request: Request, env: Env, tenantId: string): Promise<Response> {
  const access = await authorizeTenant(request, env, tenantId);
  if (access instanceof Response) return access;
  if (!(await activeTenant(env, tenantId))) return json({ detail: "Empresa no encontrada" }, 404);
  return json({ tenantId, ...(await tenantWorkspace(env, tenantId).summary()) });
}

async function tenantSettings(request: Request, env: Env, tenantId: string): Promise<Response> {
  const mutation = request.method === "PUT";
  const access = await authorizeTenant(request, env, tenantId, mutation);
  if (access instanceof Response) return access;
  if (!(await activeTenant(env, tenantId))) return json({ detail: "Empresa no encontrada" }, 404);
  if (!mutation) {
    const settings = await env.GLOBAL_DB.prepare(
      `SELECT bot_name AS botName, tone, welcome_message AS welcomeMessage,
              system_instructions AS systemInstructions, ai_provider AS aiProvider,
              ai_model AS aiModel, updated_at AS updatedAt
       FROM tenant_settings WHERE tenant_id = ?`,
    )
      .bind(tenantId)
      .first();
    return json(
      settings ?? {
        botName: "Asistente",
        tone: "Profesional y cercano",
        welcomeMessage: "Hola, ¿cómo puedo ayudarte?",
        systemInstructions: "",
        aiProvider: "workers-ai",
        aiModel: env.EMBEDDING_MODEL,
      },
    );
  }
  const payload = (await request.json()) as Record<string, unknown>;
  const botName = typeof payload.botName === "string" ? payload.botName.trim() : "";
  const tone = typeof payload.tone === "string" ? payload.tone.trim() : "";
  const welcome = typeof payload.welcomeMessage === "string" ? payload.welcomeMessage.trim() : "";
  const instructions =
    typeof payload.systemInstructions === "string" ? payload.systemInstructions.trim() : "";
  if (
    botName.length < 2 ||
    botName.length > 80 ||
    tone.length < 2 ||
    tone.length > 120 ||
    welcome.length < 2 ||
    welcome.length > 1_000 ||
    instructions.length > 10_000
  ) {
    return json({ detail: "La configuración contiene campos inválidos" }, 400);
  }
  await env.GLOBAL_DB.prepare(
    `INSERT INTO tenant_settings
      (tenant_id, bot_name, tone, welcome_message, system_instructions, ai_provider, ai_model, updated_at)
     VALUES (?, ?, ?, ?, ?, 'workers-ai', ?, datetime('now'))
     ON CONFLICT(tenant_id) DO UPDATE SET
       bot_name = excluded.bot_name,
       tone = excluded.tone,
       welcome_message = excluded.welcome_message,
       system_instructions = excluded.system_instructions,
       ai_provider = excluded.ai_provider,
       ai_model = excluded.ai_model,
       updated_at = excluded.updated_at`,
  )
    .bind(tenantId, botName, tone, welcome, instructions, env.EMBEDDING_MODEL)
    .run();
  await env.GLOBAL_DB.prepare(
    "INSERT INTO audit_events (id, tenant_id, user_id, action, metadata) VALUES (?, ?, ?, ?, ?)",
  )
    .bind(crypto.randomUUID(), tenantId, access.userId, "settings.updated", "{}")
    .run();
  return tenantSettings(new Request(request.url, { method: "GET", headers: request.headers }), env, tenantId);
}

async function tenantIntegrations(request: Request, env: Env, tenantId: string): Promise<Response> {
  const mutation = request.method === "PUT";
  const access = await authorizeTenant(request, env, tenantId, mutation);
  if (access instanceof Response) return access;
  if (!(await activeTenant(env, tenantId))) return json({ detail: "Empresa no encontrada" }, 404);
  if (!mutation) {
    return json(await publicIntegrations(env, tenantId, new URL(request.url).origin));
  }
  try {
    const input = validateIntegrationInput(await request.json());
    await saveIntegrations(env, tenantId, input);
    await env.GLOBAL_DB.prepare(
      "INSERT INTO audit_events (id, tenant_id, user_id, action, metadata) VALUES (?, ?, ?, ?, ?)",
    )
      .bind(
        crypto.randomUUID(), tenantId, access.userId, "integrations.updated",
        JSON.stringify({ aiProvider: input.aiProvider, whatsappEnabled: input.whatsappEnabled }),
      )
      .run();
    return json(await publicIntegrations(env, tenantId, new URL(request.url).origin));
  } catch (error) {
    return json({ detail: error instanceof Error ? error.message : "Configuración inválida" }, 400);
  }
}

async function tenantIntegrationTest(request: Request, env: Env, tenantId: string): Promise<Response> {
  const access = await authorizeTenant(request, env, tenantId, true);
  if (access instanceof Response) return access;
  const payload = (await request.json()) as Record<string, unknown>;
  const target = payload.target === "whatsapp" || payload.target === "ai" ? payload.target : null;
  if (!target) return json({ detail: "Integración inválida" }, 400);
  try {
    const result = await testIntegration(env, tenantId, target);
    await env.GLOBAL_DB.prepare(
      "INSERT INTO audit_events (id, tenant_id, user_id, action, metadata) VALUES (?, ?, ?, ?, ?)",
    )
      .bind(crypto.randomUUID(), tenantId, access.userId, `integrations.${target}.tested`, "{}")
      .run();
    return json(result);
  } catch (error) {
    return json({ detail: error instanceof Error ? error.message : "No fue posible probar la conexión" }, 422);
  }
}

async function listKnowledge(request: Request, env: Env, tenantId: string): Promise<Response> {
  const access = await authorizeTenant(request, env, tenantId);
  if (access instanceof Response) return access;
  if (!(await activeTenant(env, tenantId))) return json({ detail: "Empresa no encontrada" }, 404);
  return json({ sources: await tenantWorkspace(env, tenantId).listKnowledge() });
}

async function removeKnowledge(
  request: Request,
  env: Env,
  tenantId: string,
  sourceId: string,
): Promise<Response> {
  const access = await authorizeTenant(request, env, tenantId, true);
  if (access instanceof Response) return access;
  const vectorIds = await tenantWorkspace(env, tenantId).deleteKnowledge(sourceId);
  if (!vectorIds.length) return json({ detail: "Fuente no encontrada" }, 404);
  await env.KNOWLEDGE_INDEX.deleteByIds(vectorIds);
  await env.GLOBAL_DB.prepare(
    "INSERT INTO audit_events (id, tenant_id, user_id, action, metadata) VALUES (?, ?, ?, ?, ?)",
  )
    .bind(
      crypto.randomUUID(),
      tenantId,
      access.userId,
      "knowledge.deleted",
      JSON.stringify({ sourceId }),
    )
    .run();
  return json({ status: "deleted", id: sourceId });
}

async function handleFetch(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/") {
    return Response.redirect(`${url.origin}/admin`, 302);
  }
  if (request.method === "GET" && url.pathname === "/login") {
    return (await authenticate(request, env))
      ? Response.redirect(`${url.origin}/admin`, 302)
      : html(loginHtml);
  }
  if (request.method === "GET" && url.pathname === "/setup") {
    return html(setupHtml);
  }
  if (request.method === "GET" && url.pathname === "/admin") {
    return (await authenticate(request, env))
      ? html(dashboardHtml)
      : Response.redirect(`${url.origin}/login`, 302);
  }
  if (request.method === "GET" && url.pathname === "/health") {
    await env.GLOBAL_DB.prepare("SELECT 1 AS ok").first();
    return json({ status: "ok", runtime: "cloudflare-workers", storage: "d1+durable-objects" });
  }
  if (request.method === "POST" && url.pathname === "/internal/tenants") {
    return createTenant(request, env);
  }
  if (request.method === "POST" && url.pathname === "/api/setup") {
    return setupOwner(request, env);
  }
  if (request.method === "POST" && url.pathname === "/api/auth/login") {
    return loginRequest(request, env);
  }
  if (request.method === "POST" && url.pathname === "/api/auth/logout") {
    return logoutRequest(request, env);
  }
  if (request.method === "GET" && url.pathname === "/api/session") {
    return sessionRequest(request, env);
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
  const knowledgeList = url.pathname.match(
    /^\/api\/tenants\/([A-Za-z0-9_-]{2,80})\/knowledge$/,
  );
  if (knowledgeList?.[1] && request.method === "GET") {
    return listKnowledge(request, env, knowledgeList[1]);
  }
  const knowledgeItem = url.pathname.match(
    /^\/api\/tenants\/([A-Za-z0-9_-]{2,80})\/knowledge\/([A-Fa-f0-9-]{36})$/,
  );
  if (knowledgeItem?.[1] && knowledgeItem[2] && request.method === "DELETE") {
    return removeKnowledge(request, env, knowledgeItem[1], knowledgeItem[2]);
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
  const settings = url.pathname.match(/^\/api\/tenants\/([A-Za-z0-9_-]{2,80})\/settings$/);
  if (settings?.[1] && (request.method === "GET" || request.method === "PUT")) {
    return tenantSettings(request, env, settings[1]);
  }
  const integrations = url.pathname.match(
    /^\/api\/tenants\/([A-Za-z0-9_-]{2,80})\/integrations$/,
  );
  if (integrations?.[1] && (request.method === "GET" || request.method === "PUT")) {
    return tenantIntegrations(request, env, integrations[1]);
  }
  const integrationTest = url.pathname.match(
    /^\/api\/tenants\/([A-Za-z0-9_-]{2,80})\/integrations\/test$/,
  );
  if (integrationTest?.[1] && request.method === "POST") {
    return tenantIntegrationTest(request, env, integrationTest[1]);
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
    await env.GLOBAL_DB.prepare(
      "DELETE FROM auth_sessions WHERE datetime(expires_at) <= datetime('now')",
    ).run();
  },
} satisfies ExportedHandler<Env, WhatsappMessageReceived>;
