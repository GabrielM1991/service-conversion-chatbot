import { constantTimeEqual } from "./security";
import type { Env } from "./types";

const encoder = new TextEncoder();
const SESSION_COOKIE = "serviceflow_session";
const SESSION_SECONDS = 12 * 60 * 60;

export interface AuthenticatedUser {
  id: string;
  email: string;
  csrfToken: string;
  expiresAt: string;
}

export interface Membership {
  tenantId: string;
  tenantName: string;
  role: "owner" | "admin" | "viewer";
}

function bytesToHex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function randomToken(bytes = 32): string {
  const data = crypto.getRandomValues(new Uint8Array(bytes));
  let binary = "";
  for (const byte of data) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

async function sha256(value: string): Promise<string> {
  return bytesToHex(await crypto.subtle.digest("SHA-256", encoder.encode(value)));
}

function cookieValue(request: Request, name: string): string | null {
  const cookie = request.headers.get("Cookie") ?? "";
  for (const part of cookie.split(";")) {
    const [key, ...value] = part.trim().split("=");
    if (key === name) return decodeURIComponent(value.join("="));
  }
  return null;
}

export function sessionCookie(token: string): string {
  return `${SESSION_COOKIE}=${encodeURIComponent(token)}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${SESSION_SECONDS}`;
}

export function clearSessionCookie(): string {
  return `${SESSION_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0`;
}

export function validEmail(value: string): boolean {
  return value.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

export async function createOwnerAccess(
  env: Env,
  input: { tenantId: string; tenantName: string; email: string },
): Promise<{ accessKey: string; userId: string }> {
  const email = input.email.trim().toLowerCase();
  const existing = await env.GLOBAL_DB.prepare("SELECT id FROM users WHERE email = ?")
    .bind(email)
    .first();
  if (existing) throw new Error("Ya existe una cuenta con ese correo");

  const userId = crypto.randomUUID();
  const accessKey = `sf_live_${randomToken()}`;
  const accessHash = `access_key_sha256$${await sha256(accessKey)}`;
  const auditId = crypto.randomUUID();
  await env.GLOBAL_DB.batch([
    env.GLOBAL_DB.prepare(
      `INSERT INTO tenants (id, name, active) VALUES (?, ?, 1)
       ON CONFLICT(id) DO UPDATE SET name = excluded.name, active = 1`,
    ).bind(input.tenantId, input.tenantName),
    env.GLOBAL_DB.prepare(
      `INSERT INTO tenant_settings (tenant_id, bot_name)
       VALUES (?, ?)
       ON CONFLICT(tenant_id) DO NOTHING`,
    ).bind(input.tenantId, `Asistente de ${input.tenantName}`),
    env.GLOBAL_DB.prepare(
      "INSERT INTO users (id, email, password_hash, active) VALUES (?, ?, ?, 1)",
    ).bind(userId, email, accessHash),
    env.GLOBAL_DB.prepare(
      "INSERT INTO tenant_memberships (tenant_id, user_id, role) VALUES (?, ?, 'owner')",
    ).bind(input.tenantId, userId),
    env.GLOBAL_DB.prepare(
      "INSERT INTO audit_events (id, tenant_id, user_id, action, metadata) VALUES (?, ?, ?, ?, ?)",
    ).bind(auditId, input.tenantId, userId, "owner.created", JSON.stringify({ email })),
  ]);
  return { accessKey, userId };
}

export async function login(
  env: Env,
  emailValue: string,
  accessKey: string,
): Promise<{ user: AuthenticatedUser; memberships: Membership[]; cookie: string } | null> {
  const email = emailValue.trim().toLowerCase();
  if (!validEmail(email) || !accessKey.startsWith("sf_live_") || accessKey.length > 100) return null;
  const account = await env.GLOBAL_DB.prepare(
    "SELECT id, email, password_hash FROM users WHERE email = ? AND active = 1",
  )
    .bind(email)
    .first<{ id: string; email: string; password_hash: string }>();
  if (!account) return null;
  const suppliedHash = `access_key_sha256$${await sha256(accessKey)}`;
  if (!constantTimeEqual(suppliedHash, account.password_hash)) return null;

  const token = randomToken();
  const csrfToken = randomToken(24);
  const expiresAt = new Date(Date.now() + SESSION_SECONDS * 1000).toISOString();
  await env.GLOBAL_DB.prepare(
    `INSERT INTO auth_sessions (id, user_id, token_hash, expires_at, csrf_token)
     VALUES (?, ?, ?, ?, ?)`,
  )
    .bind(crypto.randomUUID(), account.id, await sha256(token), expiresAt, csrfToken)
    .run();
  const user = { id: account.id, email: account.email, csrfToken, expiresAt };
  return { user, memberships: await membershipsForUser(env, account.id), cookie: sessionCookie(token) };
}

export async function authenticate(request: Request, env: Env): Promise<AuthenticatedUser | null> {
  const token = cookieValue(request, SESSION_COOKIE);
  if (!token) return null;
  return env.GLOBAL_DB.prepare(
    `SELECT u.id, u.email, s.csrf_token AS csrfToken, s.expires_at AS expiresAt
     FROM auth_sessions s
     JOIN users u ON u.id = s.user_id
     WHERE s.token_hash = ? AND datetime(s.expires_at) > datetime('now') AND u.active = 1`,
  )
    .bind(await sha256(token))
    .first<AuthenticatedUser>();
}

export async function membershipsForUser(env: Env, userId: string): Promise<Membership[]> {
  const result = await env.GLOBAL_DB.prepare(
    `SELECT m.tenant_id AS tenantId, t.name AS tenantName, m.role
     FROM tenant_memberships m
     JOIN tenants t ON t.id = m.tenant_id
     WHERE m.user_id = ? AND t.active = 1
     ORDER BY t.name`,
  )
    .bind(userId)
    .all<Membership>();
  return result.results;
}

export async function membershipForTenant(
  env: Env,
  userId: string,
  tenantId: string,
): Promise<Membership | null> {
  return env.GLOBAL_DB.prepare(
    `SELECT m.tenant_id AS tenantId, t.name AS tenantName, m.role
     FROM tenant_memberships m
     JOIN tenants t ON t.id = m.tenant_id
     WHERE m.user_id = ? AND m.tenant_id = ? AND t.active = 1`,
  )
    .bind(userId, tenantId)
    .first<Membership>();
}

export function validCsrf(request: Request, user: AuthenticatedUser): boolean {
  const supplied = request.headers.get("X-CSRF-Token") ?? "";
  return Boolean(supplied && constantTimeEqual(supplied, user.csrfToken));
}

export async function logout(request: Request, env: Env): Promise<void> {
  const token = cookieValue(request, SESSION_COOKIE);
  if (!token) return;
  await env.GLOBAL_DB.prepare("DELETE FROM auth_sessions WHERE token_hash = ?")
    .bind(await sha256(token))
    .run();
}
