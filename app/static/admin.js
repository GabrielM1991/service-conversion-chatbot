const $ = (selector) => document.querySelector(selector);
const state = { user: null, tenants: [], tenantId: "", settings: null, sources: [] };
const fields = {
  tenant: $("#tenant-select"), business: $("#business-name"), bot: $("#bot-name"),
  tone: $("#tone"), welcome: $("#welcome"), instructions: $("#instructions"),
  provider: $("#provider"), model: $("#model"), apiKey: $("#api-key"),
};

async function api(url, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = document.cookie.split("; ").find((item) => item.startsWith("serviceflow_csrf="))?.split("=")[1];
    if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf));
  }
  const response = await fetch(url, { cache: "no-store", ...options, headers });
  if (response.status === 401) {
    window.location.assign("/login");
    throw new Error("Tu sesión terminó. Inicia sesión nuevamente.");
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "No fue posible completar la operación");
  }
  return response.status === 204 ? null : response.json();
}

async function loadUser() {
  state.user = await api("/auth/me");
  $("#user-email").textContent = state.user.email;
}

function toast(message, error = false) {
  const node = $("#toast"); node.textContent = message; node.className = `toast${error ? " error" : ""}`;
  node.hidden = false; window.setTimeout(() => { node.hidden = true; }, 3200);
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

async function loadTenants() {
  state.tenants = await api("/admin/api/tenants"); fields.tenant.replaceChildren();
  state.tenants.forEach((tenant) => { const option = document.createElement("option"); option.value = tenant.id; option.textContent = tenant.name; fields.tenant.append(option); });
  state.tenantId = state.tenants[0]?.id || "";
}

async function loadSettings() {
  state.settings = await api(`/admin/api/tenants/${state.tenantId}/settings`);
  fields.business.value = state.settings.business_name; fields.bot.value = state.settings.bot_name;
  fields.tone.value = state.settings.tone; fields.welcome.value = state.settings.welcome_message;
  fields.instructions.value = state.settings.system_instructions; fields.provider.value = state.settings.provider;
  fields.model.value = state.settings.model; fields.apiKey.value = "";
  $("#bot-summary").textContent = state.settings.bot_name; $("#provider-summary").textContent = state.settings.provider === "openai" ? "OpenAI" : state.settings.provider;
  $("#key-status").textContent = state.settings.api_key_configured ? `Credencial guardada: ${state.settings.api_key_hint}` : "Todavía no hay una credencial propia configurada.";
  $("#encryption-warning").hidden = state.settings.encryption_available;
  const readonly = state.settings.role === "viewer";
  document.body.classList.toggle("readonly", readonly);
  $("#readonly-banner").hidden = !readonly;
  $("#active-role").textContent = `Rol: ${state.settings.role}`;
  $("#user-role").textContent = state.settings.role;
}

function renderSources() {
  const list = $("#source-list"); list.replaceChildren(); $("#source-count").textContent = `${state.sources.length} ${state.sources.length === 1 ? "fuente" : "fuentes"}`;
  $("#library-status").textContent = `${state.sources.filter((item) => item.status === "ready").length} listas para contexto`;
  if (!state.sources.length) { const empty = document.createElement("div"); empty.className = "empty"; empty.textContent = "Aún no hay fuentes. Agrega texto, un PDF o una imagen."; list.append(empty); return; }
  state.sources.forEach((source) => {
    const item = document.createElement("article"); item.className = "source-item";
    const badge = document.createElement("span"); badge.className = "kind-badge"; badge.textContent = source.kind.toUpperCase();
    const info = document.createElement("div"); const title = document.createElement("strong"); title.textContent = source.title;
    const meta = document.createElement("small"); meta.textContent = `${source.status === "ready" ? "Lista" : "Guardada"} · ${formatSize(source.size_bytes)} · ${source.characters} caracteres`;
    info.append(title, meta); const remove = document.createElement("button"); remove.type = "button"; remove.dataset.write = "true"; remove.textContent = "Eliminar";
    remove.addEventListener("click", async () => { if (!window.confirm(`¿Eliminar “${source.title}”?`)) return; try { await api(`/admin/api/tenants/${state.tenantId}/knowledge/${source.id}`, { method: "DELETE" }); await loadSources(); toast("Fuente eliminada"); } catch (error) { toast(error.message, true); } });
    item.append(badge, info, remove); list.append(item);
  });
}

async function loadSources() { state.sources = await api(`/admin/api/tenants/${state.tenantId}/knowledge`); renderSources(); }
async function loadTenant() { await Promise.all([loadSettings(), loadSources()]); }

$("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault(); $("#save-status").textContent = "Guardando…";
  const payload = { business_name: fields.business.value, bot_name: fields.bot.value, tone: fields.tone.value, welcome_message: fields.welcome.value, system_instructions: fields.instructions.value, provider: fields.provider.value, model: fields.model.value };
  if (fields.apiKey.value.trim()) payload.api_key = fields.apiKey.value.trim();
  try { await api(`/admin/api/tenants/${state.tenantId}/settings`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); await loadSettings(); $("#save-status").textContent = "Cambios guardados"; toast("Configuración actualizada"); }
  catch (error) { $("#save-status").textContent = ""; toast(error.message, true); }
});

$("#text-form").addEventListener("submit", async (event) => {
  event.preventDefault(); try { await api(`/admin/api/tenants/${state.tenantId}/knowledge/text`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: $("#text-title").value, text: $("#text-content").value }) }); event.target.reset(); await loadSources(); toast("Texto añadido a la IA"); } catch (error) { toast(error.message, true); }
});

$("#file-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const file = $("#knowledge-file").files[0]; if (!file) return;
  const data = new FormData(); data.append("title", $("#file-title").value); data.append("description", $("#file-description").value); data.append("file", file);
  try { await api(`/admin/api/tenants/${state.tenantId}/knowledge/file`, { method: "POST", body: data }); event.target.reset(); $("#file-label").textContent = "Selecciona un archivo"; await loadSources(); toast("Archivo procesado correctamente"); } catch (error) { toast(error.message, true); }
});

$("#knowledge-file").addEventListener("change", (event) => { $("#file-label").textContent = event.target.files[0]?.name || "Selecciona o arrastra un archivo"; });
$("#toggle-key").addEventListener("click", () => { fields.apiKey.type = fields.apiKey.type === "password" ? "text" : "password"; $("#toggle-key").textContent = fields.apiKey.type === "password" ? "Ver" : "Ocultar"; });
fields.tenant.addEventListener("change", async () => { state.tenantId = fields.tenant.value; await loadTenant(); });
$("#logout").addEventListener("click", async () => { try { await api("/auth/logout", { method: "POST" }); window.location.assign("/login"); } catch (error) { toast(error.message, true); } });

async function initialize() { try { await loadUser(); await loadTenants(); await loadTenant(); } catch (error) { toast(error.message, true); } }
initialize();
