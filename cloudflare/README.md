# ServiceFlow en Cloudflare Workers

Esta carpeta contiene la primera base **Cloudflare-native** del producto. Convive con la aplicación FastAPI: permite migrar y comprobar cada flujo sin interrumpir la versión actual.

## Componentes incluidos

- Worker TypeScript como API y receptor de webhooks.
- D1 para tenants, usuarios, membresías, sesiones y auditoría global.
- Un Durable Object SQLite por tenant para mensajes, citas y fuentes de conocimiento.
- Cloudflare Queues con reintentos y Dead Letter Queue.
- SQLite privado por tenant para textos y fragmentos, con Vectorize + Workers AI para búsqueda semántica.
- Firma HMAC del webhook de Meta y secretos fuera del repositorio.
- Panel web responsive con propietarios, sesiones, roles y protección CSRF.
- Configuración del nombre, tono, bienvenida e instrucciones del bot.
- Pruebas unitarias y verificación automática en GitHub Actions.

Esta base todavía no reemplaza toda la aplicación Python. La extracción de PDF/imágenes, el agente conversacional, proveedores de IA externos y el envío de respuestas a WhatsApp se migrarán en las siguientes fases. No requiere una suscripción de R2: en esta etapa conserva texto y descripciones en SQLite; los binarios grandes necesitarán almacenamiento de objetos más adelante.

## 1. Instalar y comprobar localmente

Desde la raíz del repositorio:

```bash
cd cloudflare
npm install
cp .dev.vars.example .dev.vars
npm run check
```

Edita `.dev.vars` y sustituye los valores de ejemplo por secretos largos y únicos. El archivo está ignorado por Git. Wrangler puede emular D1, Durable Objects y Queues; Vectorize no tiene emulación local, por lo que los endpoints semánticos requieren el índice remoto.

## 2. Iniciar sesión y crear los recursos

```bash
npm run cf:login
npx wrangler d1 create serviceflow-global
npx wrangler queues create serviceflow-messages
npx wrangler queues create serviceflow-messages-dlq
npx wrangler vectorize create serviceflow-knowledge --dimensions=1024 --metric=cosine
npx wrangler vectorize create-metadata-index serviceflow-knowledge --property-name=tenantId --type=string
```

El primer comando devuelve el `database_id` real. Cópialo en `wrangler.jsonc`, sustituyendo `00000000-0000-0000-0000-000000000000`.

## 3. Aplicar D1

Para crear una base local y ejecutar las migraciones:

```bash
npx wrangler d1 migrations apply GLOBAL_DB --local
```

Para aplicarlas a producción:

```bash
npx wrangler d1 migrations apply GLOBAL_DB --remote
```

## 4. Guardar secretos de producción

Ejecuta cada comando y pega el valor cuando Wrangler lo solicite. No escribas el secreto directamente en el comando ni en GitHub.

```bash
npx wrangler secret put ADMIN_API_TOKEN
npx wrangler secret put META_APP_SECRET
npx wrangler secret put WHATSAPP_VERIFY_TOKEN
```

`wrangler.jsonc` utiliza `APP_ENV=production` por defecto para no devolver errores internos. `.dev.vars` lo sustituye localmente por `development` para facilitar el diagnóstico.

## 5. Probar y desplegar

```bash
npm run dev
```

La terminal mostrará la URL local. Para desplegar:

```bash
npm run check
npm run deploy
```

## 6. Crear el primer tenant

Abre `/setup` en el navegador, por ejemplo:

```text
https://TU-WORKER.workers.dev/setup
```

Introduce `ADMIN_API_TOKEN`, el identificador y nombre de la empresa y el correo del propietario. El sistema mostrará una clave `sf_live_...` una sola vez. Guárdala en un gestor de contraseñas y úsala junto al correo en `/login`.

Las claves de acceso tienen 256 bits aleatorios y solo se conserva su hash SHA-256. Esto evita una operación costosa de contraseña incompatible con el límite de CPU del plan Workers Free. Las sesiones se guardan como hash, vencen tras 12 horas y usan cookies `HttpOnly`, `Secure` y `SameSite=Strict`.

También se conserva el endpoint administrativo para automatización. Sustituye la URL y el token sin guardar el token en el historial del repositorio:


```bash
curl -X POST https://TU-WORKER.workers.dev/internal/tenants \
  -H 'Authorization: Bearer TU_ADMIN_API_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"id":"ClinicaDental_01","name":"Clínica Dental Demo"}'
```

El webhook que debes registrar en Meta será:

```text
https://TU-WORKER.workers.dev/webhooks/whatsapp/ClinicaDental_01
```

Meta usará `WHATSAPP_VERIFY_TOKEN` para verificar la URL y `META_APP_SECRET` para firmar cada mensaje recibido.

## Endpoints disponibles

| Método | Ruta | Protección | Uso |
|---|---|---|---|
| `GET` | `/health` | pública | Estado de Worker y D1 |
| `GET` | `/setup` | pública; alta protegida por token | Crear el primer propietario |
| `GET` | `/login` | pública | Iniciar sesión con correo y clave de acceso |
| `GET` | `/admin` | cookie de sesión | Panel de cada empresa |
| `GET` | `/api/session` | cookie de sesión | Usuario y membresías activas |
| `POST` | `/internal/tenants` | token administrador | Crear o reactivar tenant |
| `GET/POST` | `/webhooks/whatsapp/:tenantId` | token de verificación/firma Meta | Verificar y recibir mensajes |
| `POST` | `/api/tenants/:tenantId/knowledge/text` | sesión/membresía o token administrador | Guardar y vectorizar texto |
| `POST` | `/api/tenants/:tenantId/knowledge/search` | sesión/membresía o token administrador | Buscar contexto del tenant |
| `GET/DELETE` | `/api/tenants/:tenantId/knowledge[/sourceId]` | sesión y membresía | Listar o eliminar fuentes |
| `GET/PUT` | `/api/tenants/:tenantId/settings` | sesión y membresía | Configurar personalidad del bot |
| `GET` | `/api/tenants/:tenantId/summary` | sesión/membresía o token administrador | Consultar contadores privados |

## Aislamiento y seguridad

Los registros globales viven en D1. Los datos operativos, textos y fragmentos de cada empresa se almacenan en un Durable Object SQLite distinto, identificado por el tenant. Toda consulta a Vectorize exige el filtro `tenantId` y sus resultados se resuelven contra el SQLite del mismo tenant. Cada endpoint del panel vuelve a comprobar la membresía y el rol en el servidor; ocultar botones en la interfaz no se considera autorización. El Worker valida CSRF, origen, firma de Meta y deduplicación transaccional, y no expone errores internos cuando `APP_ENV=production`.
