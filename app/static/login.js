const form = document.querySelector("#login-form");
const email = document.querySelector("#email");
const password = document.querySelector("#password");
const error = document.querySelector("#login-error");
const submit = document.querySelector("#submit-button");

document.querySelector("#toggle-password").addEventListener("click", (event) => {
  password.type = password.type === "password" ? "text" : "password";
  event.currentTarget.textContent = password.type === "password" ? "Ver" : "Ocultar";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.hidden = true;
  submit.disabled = true;
  submit.textContent = "Verificando…";
  try {
    const response = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email.value.trim(), password: password.value }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || "No fue posible iniciar sesión");
    }
    window.location.assign("/admin");
  } catch (reason) {
    error.textContent = reason.message;
    error.hidden = false;
    submit.disabled = false;
    submit.textContent = "Iniciar sesión";
  }
});
