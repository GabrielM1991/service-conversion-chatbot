import { decryptSecret, encryptSecret, maskedSecret } from "./crypto";
import type { Env } from "./types";

export type AiProvider = "workers-ai" | "openai" | "anthropic" | "google";

export const AI_MODEL_OPTIONS: Record<AiProvider, Array<{ value: string; label: string }>> = {
  "workers-ai": [
    { value: "@cf/zai-org/glm-4.7-flash", label: "GLM 4.7 Flash · rápido y multilingüe" },
    { value: "@cf/google/gemma-4-26b-a4b-it", label: "Gemma 4 26B · equilibrio general" },
    { value: "@cf/openai/gpt-oss-120b", label: "GPT-OSS 120B · razonamiento avanzado" },
    { value: "@cf/moonshotai/kimi-k2.6", label: "Kimi K2.6 · contexto amplio y herramientas" },
  ],
  openai: [
    { value: "gpt-5.6-terra", label: "GPT-5.6 Terra · recomendado para servicios" },
    { value: "gpt-5.6-luna", label: "GPT-5.6 Luna · rápido y económico" },
    { value: "gpt-5.6-sol", label: "GPT-5.6 Sol · máxima capacidad" },
  ],
  anthropic: [
    { value: "claude-sonnet-5", label: "Claude Sonnet 5 · velocidad e inteligencia" },
    { value: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5 · rápido y económico" },
    { value: "claude-opus-4-8", label: "Claude Opus 4.8 · trabajo complejo" },
    { value: "claude-fable-5", label: "Claude Fable 5 · máxima capacidad" },
  ],
  google: [
    { value: "gemini-3.6-flash", label: "Gemini 3.6 Flash · recomendado y multimodal" },
    { value: "gemini-3.5-flash-lite", label: "Gemini 3.5 Flash-Lite · alto volumen" },
    { value: "gemini-3.1-pro", label: "Gemini 3.1 Pro · razonamiento avanzado" },
  ],
};

interface IntegrationRow {
  tenantId: string;
  whatsappEnabled: number;
  metaPhoneNumberId: string;
  metaWabaId: string;
  metaGraphVersion: string;
  metaAccessTokenEncrypted: string;
  metaAppSecretEncrypted: string;
  metaVerifyTokenEncrypted: string;
  whatsappStatus: string;
  whatsappCheckedAt: string | null;
  aiProvider: AiProvider;
  aiModel: string;
  aiApiKeyEncrypted: string;
  aiStatus: string;
  aiCheckedAt: string | null;
  updatedAt: string;
}

export interface IntegrationInput {
  whatsappEnabled: boolean;
  metaPhoneNumberId: string;
  metaWabaId: string;
  metaGraphVersion: string;
  metaAccessToken: string;
  metaAppSecret: string;
  metaVerifyToken: string;
  clearWhatsappSecrets: boolean;
  aiProvider: AiProvider;
  aiModel: string;
  aiApiKey: string;
  clearAiApiKey: boolean;
}

const SELECT_INTEGRATION = `SELECT tenant_id AS tenantId, whatsapp_enabled AS whatsappEnabled,
  meta_phone_number_id AS metaPhoneNumberId, meta_waba_id AS metaWabaId,
  meta_graph_version AS metaGraphVersion,
  meta_access_token_encrypted AS metaAccessTokenEncrypted,
  meta_app_secret_encrypted AS metaAppSecretEncrypted,
  meta_verify_token_encrypted AS metaVerifyTokenEncrypted,
  whatsapp_status AS whatsappStatus, whatsapp_checked_at AS whatsappCheckedAt,
  ai_provider AS aiProvider, ai_model AS aiModel, ai_api_key_encrypted AS aiApiKeyEncrypted,
  ai_status AS aiStatus, ai_checked_at AS aiCheckedAt, updated_at AS updatedAt
  FROM tenant_integrations WHERE tenant_id = ?`;

function text(value: unknown, maximum: number): string {
  return typeof value === "string" ? value.trim().slice(0, maximum) : "";
}

export function validateIntegrationInput(payload: unknown): IntegrationInput {
  const input = (payload ?? {}) as Record<string, unknown>;
  const aiProvider = text(input.aiProvider, 40) as AiProvider;
  const result: IntegrationInput = {
    whatsappEnabled: input.whatsappEnabled === true,
    metaPhoneNumberId: text(input.metaPhoneNumberId, 80),
    metaWabaId: text(input.metaWabaId, 80),
    metaGraphVersion: text(input.metaGraphVersion, 10) || "v25.0",
    metaAccessToken: text(input.metaAccessToken, 2_000),
    metaAppSecret: text(input.metaAppSecret, 512),
    metaVerifyToken: text(input.metaVerifyToken, 512),
    clearWhatsappSecrets: input.clearWhatsappSecrets === true,
    aiProvider,
    aiModel: text(input.aiModel, 160),
    aiApiKey: text(input.aiApiKey, 2_000),
    clearAiApiKey: input.clearAiApiKey === true,
  };
  if (!/^[0-9]{5,80}$/.test(result.metaPhoneNumberId) && result.metaPhoneNumberId) {
    throw new Error("Phone Number ID inválido");
  }
  if (!/^[0-9]{5,80}$/.test(result.metaWabaId) && result.metaWabaId) {
    throw new Error("WhatsApp Business Account ID inválido");
  }
  if (!/^v[0-9]{1,3}\.0$/.test(result.metaGraphVersion)) throw new Error("Versión de Graph API inválida");
  if (!["workers-ai", "openai", "anthropic", "google"].includes(result.aiProvider)) {
    throw new Error("Proveedor de IA inválido");
  }
  if (result.aiModel.length < 2) throw new Error("Modelo de IA inválido");
  return result;
}

async function row(env: Env, tenantId: string): Promise<IntegrationRow | null> {
  return env.GLOBAL_DB.prepare(SELECT_INTEGRATION).bind(tenantId).first<IntegrationRow>();
}

async function reveal(env: Env, tenantId: string, encrypted: string, field: string): Promise<string> {
  return encrypted
    ? decryptSecret(encrypted, env.INTEGRATIONS_ENCRYPTION_KEY, `${tenantId}:${field}`)
    : "";
}

export async function publicIntegrations(env: Env, tenantId: string, origin: string): Promise<Record<string, unknown>> {
  const current = await row(env, tenantId);
  if (!current) {
    return {
      whatsappEnabled: false,
      metaPhoneNumberId: "",
      metaWabaId: "",
      metaGraphVersion: "v25.0",
      metaAccessTokenMasked: "",
      metaAppSecretMasked: "",
      metaVerifyTokenMasked: "",
      whatsappStatus: "pending",
      whatsappCheckedAt: null,
      webhookUrl: `${origin}/webhooks/whatsapp/${tenantId}`,
      aiProvider: "workers-ai",
      aiModel: "@cf/zai-org/glm-4.7-flash",
      aiApiKeyMasked: "",
      aiStatus: "pending",
      aiCheckedAt: null,
      modelOptions: AI_MODEL_OPTIONS,
    };
  }
  const [accessToken, appSecret, verifyToken, aiApiKey] = await Promise.all([
    reveal(env, tenantId, current.metaAccessTokenEncrypted, "meta-access-token"),
    reveal(env, tenantId, current.metaAppSecretEncrypted, "meta-app-secret"),
    reveal(env, tenantId, current.metaVerifyTokenEncrypted, "meta-verify-token"),
    reveal(env, tenantId, current.aiApiKeyEncrypted, "ai-api-key"),
  ]);
  return {
    whatsappEnabled: current.whatsappEnabled === 1,
    metaPhoneNumberId: current.metaPhoneNumberId,
    metaWabaId: current.metaWabaId,
    metaGraphVersion: current.metaGraphVersion,
    metaAccessTokenMasked: maskedSecret(accessToken),
    metaAppSecretMasked: maskedSecret(appSecret),
    metaVerifyTokenMasked: maskedSecret(verifyToken),
    whatsappStatus: current.whatsappStatus,
    whatsappCheckedAt: current.whatsappCheckedAt,
    webhookUrl: `${origin}/webhooks/whatsapp/${tenantId}`,
    aiProvider: current.aiProvider,
    aiModel: current.aiModel,
    aiApiKeyMasked: maskedSecret(aiApiKey),
    aiStatus: current.aiStatus,
    aiCheckedAt: current.aiCheckedAt,
    modelOptions: AI_MODEL_OPTIONS,
    updatedAt: current.updatedAt,
  };
}

async function encryptedValue(
  env: Env,
  tenantId: string,
  field: string,
  supplied: string,
  existing: string,
  clear: boolean,
): Promise<string> {
  if (clear) return "";
  return supplied
    ? encryptSecret(supplied, env.INTEGRATIONS_ENCRYPTION_KEY, `${tenantId}:${field}`)
    : existing;
}

export async function saveIntegrations(env: Env, tenantId: string, input: IntegrationInput): Promise<void> {
  const current = await row(env, tenantId);
  const [accessToken, appSecret, verifyToken, aiApiKey] = await Promise.all([
    encryptedValue(env, tenantId, "meta-access-token", input.metaAccessToken, current?.metaAccessTokenEncrypted ?? "", input.clearWhatsappSecrets),
    encryptedValue(env, tenantId, "meta-app-secret", input.metaAppSecret, current?.metaAppSecretEncrypted ?? "", input.clearWhatsappSecrets),
    encryptedValue(env, tenantId, "meta-verify-token", input.metaVerifyToken, current?.metaVerifyTokenEncrypted ?? "", input.clearWhatsappSecrets),
    encryptedValue(env, tenantId, "ai-api-key", input.aiApiKey, current?.aiApiKeyEncrypted ?? "", input.clearAiApiKey),
  ]);
  await env.GLOBAL_DB.prepare(
    `INSERT INTO tenant_integrations
      (tenant_id, whatsapp_enabled, meta_phone_number_id, meta_waba_id, meta_graph_version,
       meta_access_token_encrypted, meta_app_secret_encrypted, meta_verify_token_encrypted,
       whatsapp_status, ai_provider, ai_model, ai_api_key_encrypted, ai_status, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, 'pending', datetime('now'))
     ON CONFLICT(tenant_id) DO UPDATE SET
       whatsapp_enabled=excluded.whatsapp_enabled, meta_phone_number_id=excluded.meta_phone_number_id,
       meta_waba_id=excluded.meta_waba_id, meta_graph_version=excluded.meta_graph_version,
       meta_access_token_encrypted=excluded.meta_access_token_encrypted,
       meta_app_secret_encrypted=excluded.meta_app_secret_encrypted,
       meta_verify_token_encrypted=excluded.meta_verify_token_encrypted,
       whatsapp_status='pending', ai_provider=excluded.ai_provider, ai_model=excluded.ai_model,
       ai_api_key_encrypted=excluded.ai_api_key_encrypted, ai_status='pending', updated_at=datetime('now')`,
  )
    .bind(
      tenantId, input.whatsappEnabled ? 1 : 0, input.metaPhoneNumberId, input.metaWabaId,
      input.metaGraphVersion, accessToken, appSecret, verifyToken,
      input.aiProvider, input.aiModel, aiApiKey,
    )
    .run();
}

export async function whatsappSecrets(env: Env, tenantId: string): Promise<{
  appSecret: string;
  verifyToken: string;
}> {
  const current = await row(env, tenantId);
  if (!current || current.whatsappEnabled !== 1) {
    return { appSecret: env.META_APP_SECRET, verifyToken: env.WHATSAPP_VERIFY_TOKEN };
  }
  return {
    appSecret: await reveal(env, tenantId, current.metaAppSecretEncrypted, "meta-app-secret") || env.META_APP_SECRET,
    verifyToken: await reveal(env, tenantId, current.metaVerifyTokenEncrypted, "meta-verify-token") || env.WHATSAPP_VERIFY_TOKEN,
  };
}

async function markStatus(env: Env, tenantId: string, target: "whatsapp" | "ai", status: "connected" | "error"): Promise<void> {
  const column = target === "whatsapp" ? "whatsapp" : "ai";
  await env.GLOBAL_DB.prepare(
    `UPDATE tenant_integrations SET ${column}_status = ?, ${column}_checked_at = datetime('now') WHERE tenant_id = ?`,
  ).bind(status, tenantId).run();
}

export async function testIntegration(env: Env, tenantId: string, target: "whatsapp" | "ai"): Promise<Record<string, unknown>> {
  const current = await row(env, tenantId);
  if (!current) throw new Error("Guarda la integración antes de probarla");
  try {
    if (target === "whatsapp") {
      const token = await reveal(env, tenantId, current.metaAccessTokenEncrypted, "meta-access-token");
      if (!token || !current.metaPhoneNumberId) throw new Error("Faltan el Access Token o Phone Number ID");
      const endpoint = `https://graph.facebook.com/${current.metaGraphVersion}/${encodeURIComponent(current.metaPhoneNumberId)}?fields=display_phone_number,verified_name,quality_rating`;
      const response = await fetch(endpoint, { headers: { Authorization: `Bearer ${token}` } });
      const result = await response.json() as Record<string, unknown>;
      if (!response.ok) throw new Error("Meta rechazó las credenciales");
      await markStatus(env, tenantId, target, "connected");
      return { status: "connected", displayPhoneNumber: result.display_phone_number ?? null, verifiedName: result.verified_name ?? null };
    }
    if (current.aiProvider === "workers-ai") {
      await env.AI.run(current.aiModel as Parameters<Ai["run"]>[0], { prompt: "Responde únicamente: OK", max_tokens: 2 } as never);
    } else {
      const apiKey = await reveal(env, tenantId, current.aiApiKeyEncrypted, "ai-api-key");
      if (!apiKey) throw new Error("Falta la API Key del proveedor");
      const endpoint = current.aiProvider === "openai"
        ? `https://api.openai.com/v1/models/${encodeURIComponent(current.aiModel)}`
        : current.aiProvider === "anthropic"
          ? `https://api.anthropic.com/v1/models/${encodeURIComponent(current.aiModel)}`
          : `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(current.aiModel)}`;
      const headers: Record<string, string> = current.aiProvider === "openai"
        ? { Authorization: `Bearer ${apiKey}` }
        : current.aiProvider === "anthropic"
          ? { "x-api-key": apiKey, "anthropic-version": "2023-06-01" }
          : { "x-goog-api-key": apiKey };
      const response = await fetch(endpoint, { headers });
      const providerName = current.aiProvider === "openai" ? "OpenAI" : current.aiProvider === "anthropic" ? "Anthropic" : "Google Gemini";
      if (!response.ok) throw new Error(`${providerName} rechazó la clave o el modelo`);
    }
    await markStatus(env, tenantId, target, "connected");
    return { status: "connected", provider: current.aiProvider, model: current.aiModel };
  } catch (error) {
    await markStatus(env, tenantId, target, "error");
    throw error;
  }
}
