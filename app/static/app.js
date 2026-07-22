const state = {
  tenants: [],
  tenantId: "",
  phone: "+584121234567",
  messages: [],
  waiting: false,
};

const elements = {
  tenantSelect: document.querySelector("#tenant-select"),
  tenantTone: document.querySelector("#tenant-tone"),
  phoneInput: document.querySelector("#phone-input"),
  chatName: document.querySelector("#chat-name"),
  tenantAvatar: document.querySelector("#tenant-avatar"),
  messageList: document.querySelector("#message-list"),
  chatCanvas: document.querySelector("#chat-canvas"),
  typing: document.querySelector("#typing-indicator"),
  form: document.querySelector("#message-form"),
  input: document.querySelector("#message-input"),
  sendButton: document.querySelector("#send-button"),
  systemStatus: document.querySelector("#system-status"),
  aiMode: document.querySelector("#ai-mode"),
  processingLabel: document.querySelector("#processing-label"),
};

function initials(name) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}

function formatTime(value) {
  return new Intl.DateTimeFormat("es", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function humanizeIntent(intent) {
  const labels = {
    agendar_cita: "Agendamiento",
    pregunta_frecuente: "Información",
    procesar_pago: "Pago",
    derivar_humano: "Asesor humano",
    desconocida: "Sin clasificar",
  };
  return labels[intent] || intent;
}

function scrollToLatest() {
  requestAnimationFrame(() => {
    elements.chatCanvas.scrollTop = elements.chatCanvas.scrollHeight;
  });
}

function makeEmptyState() {
  const box = document.createElement("div");
  box.className = "empty-state";
  const title = document.createElement("strong");
  title.textContent = "Inicia una conversación real";
  const copy = document.createElement("p");
  copy.textContent =
    "Prueba una consulta de precio, una solicitud de cita o pide hablar con una persona.";
  box.append(title, copy);
  return box;
}

function makeMessage(message) {
  const row = document.createElement("div");
  row.className = `message-row ${message.direction}`;

  const content = document.createElement("div");
  content.className = "message-content";

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.textContent = message.text;

  const meta = document.createElement("div");
  meta.className = "message-meta";
  const time = document.createElement("span");
  time.textContent = formatTime(message.created_at);
  meta.append(time);

  if (message.intent) {
    const tag = document.createElement("span");
    tag.className = "intent-tag";
    const confidence = message.confidence ? ` · ${Math.round(message.confidence * 100)}%` : "";
    tag.textContent = `${humanizeIntent(message.intent)}${confidence}`;
    meta.append(tag);
  }

  content.append(bubble, meta);
  row.append(content);
  return row;
}

function renderMessages(messages = state.messages) {
  elements.messageList.replaceChildren();
  if (!messages.length) {
    elements.messageList.append(makeEmptyState());
  } else {
    const fragment = document.createDocumentFragment();
    messages.forEach((message) => fragment.append(makeMessage(message)));
    elements.messageList.append(fragment);
  }
  scrollToLatest();
}

function setWaiting(waiting, label = "Procesando con el worker…") {
  state.waiting = waiting;
  elements.typing.hidden = !waiting;
  elements.sendButton.disabled = waiting;
  elements.tenantSelect.disabled = waiting;
  elements.phoneInput.disabled = waiting;
  elements.processingLabel.textContent = label;
  scrollToLatest();
}

async function fetchHealth() {
  try {
    const response = await fetch("/health", { cache: "no-store" });
    if (!response.ok) throw new Error("health unavailable");
    const health = await response.json();
    elements.systemStatus.textContent = "Sistema operativo";
    elements.aiMode.textContent = `IA: ${health.ai === "rules" ? "reglas locales" : "OpenAI + fallback"}`;
  } catch {
    elements.systemStatus.textContent = "Sin conexión";
    elements.aiMode.textContent = "IA: no disponible";
  }
}

async function fetchTenants() {
  const response = await fetch("/demo/tenants", { cache: "no-store" });
  if (!response.ok) throw new Error("No fue posible cargar las empresas");
  state.tenants = await response.json();
  elements.tenantSelect.replaceChildren();
  state.tenants.forEach((tenant) => {
    const option = document.createElement("option");
    option.value = tenant.id;
    option.textContent = tenant.name;
    elements.tenantSelect.append(option);
  });
  state.tenantId = state.tenants[0]?.id || "";
  updateTenantIdentity();
}

function updateTenantIdentity() {
  const tenant = state.tenants.find((item) => item.id === state.tenantId);
  if (!tenant) return;
  elements.chatName.textContent = tenant.name;
  elements.tenantAvatar.textContent = initials(tenant.name);
  elements.tenantTone.textContent = `Tono: ${tenant.tone}`;
}

async function fetchMessages() {
  if (!state.tenantId || !state.phone) return [];
  const params = new URLSearchParams({ phone: state.phone });
  const response = await fetch(`/demo/messages?${params}`, {
    cache: "no-store",
    headers: { "X-Tenant-ID": state.tenantId },
  });
  if (!response.ok) throw new Error("No fue posible recuperar la conversación");
  return response.json();
}

async function refreshConversation() {
  try {
    state.messages = await fetchMessages();
    renderMessages();
  } catch (error) {
    showLocalError(error.message);
  }
}

function showLocalError(text) {
  const errorMessage = {
    id: `error-${Date.now()}`,
    direction: "outbound",
    text,
    created_at: new Date().toISOString(),
    intent: null,
  };
  renderMessages([...state.messages, errorMessage]);
}

async function waitForReply(previousOutboundId, messageId) {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 500));
    const messages = await fetchMessages();
    const incomingPersisted = messages.some((message) => message.id === messageId);
    const outbound = messages.filter((message) => message.direction === "outbound");
    const newestOutbound = outbound[outbound.length - 1];
    if (incomingPersisted && newestOutbound && newestOutbound.id !== previousOutboundId) {
      return messages;
    }
  }
  throw new Error("El worker tardó más de lo esperado. Revisa sus logs e inténtalo nuevamente.");
}

async function sendMessage(text) {
  const cleanText = text.trim();
  if (!cleanText || state.waiting || !state.tenantId) return;

  const previousOutbound = [...state.messages]
    .reverse()
    .find((message) => message.direction === "outbound");
  const messageId = `demo-${Date.now()}-${crypto.randomUUID()}`;
  const optimistic = {
    id: messageId,
    direction: "inbound",
    text: cleanText,
    created_at: new Date().toISOString(),
  };

  renderMessages([...state.messages, optimistic]);
  setWaiting(true);

  try {
    const response = await fetch("/webhooks/whatsapp", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Tenant-ID": state.tenantId,
      },
      body: JSON.stringify({
        message_id: messageId,
        from_phone: state.phone,
        text: cleanText,
      }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || "El webhook rechazó el mensaje");
    }
    state.messages = await waitForReply(previousOutbound?.id, messageId);
    renderMessages();
  } catch (error) {
    showLocalError(error.message);
  } finally {
    setWaiting(false);
  }
}

elements.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = elements.input.value;
  elements.input.value = "";
  elements.input.style.height = "auto";
  await sendMessage(text);
  elements.input.focus();
});

elements.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.form.requestSubmit();
  }
});

elements.input.addEventListener("input", () => {
  elements.input.style.height = "auto";
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 110)}px`;
});

elements.tenantSelect.addEventListener("change", async () => {
  state.tenantId = elements.tenantSelect.value;
  updateTenantIdentity();
  await refreshConversation();
});

elements.phoneInput.addEventListener("change", async () => {
  state.phone = elements.phoneInput.value.trim();
  await refreshConversation();
});

document.querySelectorAll(".suggestion").forEach((button) => {
  button.addEventListener("click", () => {
    elements.input.value = button.textContent;
    elements.input.focus();
  });
});

async function initialize() {
  await fetchHealth();
  try {
    await fetchTenants();
    await refreshConversation();
  } catch (error) {
    elements.systemStatus.textContent = "Configuración incompleta";
    showLocalError(error.message);
  }
}

initialize();
