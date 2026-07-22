# Plataforma de Conversión y Agendamiento Automatizado

Chatbot SaaS multi-tenant para empresas de servicios. El webhook deduplica y publica cada mensaje en Redis Streams; un worker independiente ejecuta el pipeline, clasifica la intención con salida estructurada, selecciona una estrategia y persiste la conversación sin mezclar datos entre negocios.

## Interfaz de demostración

Con la aplicación levantada, abre `http://127.0.0.1:8000/` para usar una interfaz responsive estilo mensajería. Permite cambiar de tenant, usar distintos teléfonos de prueba, enviar mensajes al webhook real y visualizar la respuesta que el worker guardó en PostgreSQL.

La interfaz incluye mensajes sugeridos, estado de salud, modo de IA activo, intención detectada y nivel de confianza. Los endpoints de apoyo `/demo/tenants` y `/demo/messages` solo están disponibles cuando `APP_ENV=development`; no se exponen en producción.

## Panel de empresa

Abre `http://127.0.0.1:8000/login` e inicia sesión con el usuario local inicial:

```text
Correo: admin@serviceflow.local
Contraseña: ServiceFlow-local-2026!
```

Después entrarás en `/admin`, donde cada usuario solo ve las empresas asignadas a su cuenta. El panel permite configurar nombre de empresa, nombre del bot, tono, bienvenida, instrucciones permanentes, proveedor, modelo y una API key propia. Los roles `owner` y `admin` pueden editar; `viewer` tiene acceso de solo lectura.

La autenticación usa contraseñas Argon2, sesiones opacas almacenadas como hash, cookies `HttpOnly`, vencimiento configurable y protección CSRF. Cambia las credenciales iniciales antes de cualquier despliegue:

```bash
export BOOTSTRAP_ADMIN_EMAIL='tu-correo@empresa.com'
export BOOTSTRAP_ADMIN_PASSWORD='una-contraseña-larga-y-única'
export SESSION_TTL_HOURS='12'
```

Las credenciales nunca se devuelven al navegador y se almacenan cifradas. Antes de guardar claves por tenant, genera una llave maestra y expórtala en la misma terminal desde la que levantas Docker:

```bash
export TENANT_SECRET_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
docker compose up --build
```

Conserva esa llave fuera de GitHub; si se pierde, las credenciales cifradas existentes no podrán recuperarse.

La biblioteca de conocimiento admite:

- texto directo de hasta 100.000 caracteres;
- PDF de hasta 10 MB y 200 páginas, con extracción de texto;
- imágenes PNG, JPG y WEBP de hasta 10 MB, acompañadas por una descripción que se incorpora al contexto;
- descarga y eliminación aisladas por tenant.

Los binarios se guardan en el volumen `chatbot_uploads` y sus metadatos en PostgreSQL. Las fuentes listas se incorporan dinámicamente al contexto del tenant. En producción, las cookies se marcan como `Secure` y las credenciales de arranque son obligatorias.

## Producción con Cloudflare

Sí: ya existe una base Cloudflare-native paralela en [`cloudflare/`](cloudflare/README.md). Usa Workers, D1, Durable Objects SQLite, Queues, Vectorize y Workers AI, sin depender de Docker, PostgreSQL, Redis ni R2 para esos flujos. Incluye recepción firmada de WhatsApp, cola asíncrona, aislamiento por tenant e ingesta/búsqueda semántica de texto.

La base Cloudflare ya incluye panel responsive, autenticación mediante claves de acceso de alta entropía, sesiones, configuración por tenant e integraciones cifradas para Meta/WhatsApp, Workers AI, OpenAI y Anthropic. La aplicación FastAPI sigue conservando las funciones aún no migradas: PDF/imágenes y la ejecución completa del agente con el proveedor seleccionado. La estrategia y limitaciones están documentadas en [`docs/cloudflare-production.md`](docs/cloudflare-production.md).

## Arquitectura

```text
WhatsApp webhook -> Redis Stream -> Consumer Group -> Worker
                                                    -> MessagePipeline
                                                    -> ChatbotAgentFactory
                                                    -> OpenAI Structured Output
                                                       -> confidence guardrail
                                                       -> deterministic fallback
                                                    -> IntentStrategy
                                                    -> Calendar / Payment / Chat ports
                                      failures -> Retry -> Dead Letter Queue
```

- `app/domain`: entidades y puertos sin dependencias de frameworks.
- `app/application`: casos de uso, Chain of Responsibility, Factory y Strategy.
- `app/infrastructure`: adaptadores sustituibles para OpenAI, Redis, PostgreSQL y servicios fake.
- `app/worker.py`: consumidor independiente del proceso HTTP.
- `app/main.py`: adaptador HTTP de FastAPI y ciclo de vida del worker.
- `migrations`: esquema PostgreSQL versionado y políticas Row-Level Security.

Los límites hexagonales permiten cambiar cada fake por Redis, RabbitMQ, Google Calendar, Stripe y WhatsApp Cloud API sin modificar las reglas centrales.

## Dos modos de ejecución

- **Memoria:** inicio rápido sin infraestructura; API y worker comparten una cola local.
- **PostgreSQL:** persistencia de tenants, servicios, clientes, conversaciones, mensajes y citas. Se activa con `DATABASE_URL`.
- **Redis Streams:** cola durable, deduplicación y opt-out persistentes. Se activa con `REDIS_URL` y separa API/worker.
- **IA local:** clasificador determinista disponible sin credenciales ni conexión externa.
- **OpenAI:** Responses API con Structured Outputs, prompt dinámico por tenant y fallback local automático.

## Inicio rápido en memoria

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload
```

En otra terminal:

```bash
curl -i http://127.0.0.1:8000/webhooks/whatsapp \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-ID: ClinicaDental_01' \
  -d '{"message_id":"wamid-demo-1","from_phone":"+584121234567","text":"Quiero una cita para limpieza dental"}'
```

La API devuelve `202 Accepted` sin esperar a la IA ni al calendario. La documentación interactiva queda en `http://127.0.0.1:8000/docs`.

El endpoint `GET /health` indica qué adaptador está activo:

```json
{"status":"ok","storage":"memory","broker":"memory","ai":"tenant-configurable"}
```

## Activar la IA real

El proyecto funciona sin una clave. Para activar OpenAI, define la variable únicamente en tu terminal; nunca la escribas en el código, en `.env.example` ni la subas a GitHub:

```bash
export OPENAI_API_KEY='tu-clave-de-openai'
docker compose up --build
```

Opcionalmente puedes cambiar el modelo, la versión lógica del prompt y el umbral de confianza:

```bash
export OPENAI_MODEL='gpt-5.6-sol'
export OPENAI_PROMPT_VERSION='intent-router-v1'
export LLM_MINIMUM_CONFIDENCE='0.72'
```

Con clave configurada, `/health` muestra `"ai":"openai-with-fallback"`. Sin clave muestra `"ai":"rules"`.

El adaptador usa la [Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses) y salida Pydantic estricta. Para cada tenant construye las instrucciones con su nombre, tono, catálogo y conocimiento. El mensaje del cliente se delimita como dato no confiable y la respuesta se valida antes de escoger una estrategia.

Guardrails incorporados:

- conjunto cerrado de intenciones y confianza entre `0` y `1`;
- rechazo de servicios que no pertenezcan al tenant;
- derivación humana explícita o por confianza insuficiente;
- `safety_identifier` estable y seudónimo, sin enviar el teléfono como identificador;
- `store=False` para no solicitar almacenamiento de la respuesta;
- timeout, un reintento del SDK y fallback determinista ante fallo del proveedor;
- el webhook y el worker continúan funcionando aunque no exista una clave.

## Ejecutar con PostgreSQL y Docker

Requiere Docker Desktop. El siguiente comando levanta PostgreSQL, Redis con AOF, ejecuta la migración, carga dos tenants y arranca API y worker:

```bash
docker compose up --build
```

Cuando aparezcan la API y el worker como activos, abre `http://127.0.0.1:8000/docs`. En este modo `/health` devuelve:

```json
{"status":"ok","storage":"postgresql","broker":"redis-streams","ai":"tenant-configurable"}
```

`GET /ready` comprueba realmente PostgreSQL y Redis y devuelve `503` si una dependencia no está disponible.

Para detener los contenedores:

```bash
docker compose down
```

Los volúmenes `chatbot_postgres_data` y `chatbot_redis_data` conservan base de datos y eventos entre reinicios. Solo usa `docker compose down -v` cuando quieras borrar expresamente todos los datos locales.

## Procesamiento durable

- El webhook responde `202 Accepted` después de publicar, sin esperar al worker.
- Redis deduplica por `tenant_id + message_id` durante 24 horas.
- El consumer group distribuye eventos entre varios workers.
- Un evento se confirma con `XACK` únicamente después de procesarse.
- Los eventos abandonados por un worker son reclamados por otro tras superar el tiempo de inactividad.
- Los fallos se reencolan con backoff exponencial; tras agotar tres reintentos terminan en `whatsapp_messages_dlq`.

Comandos operativos útiles:

```bash
# Estado de servicios
docker compose ps

# Logs del worker
docker compose logs -f worker

# Eventos pendientes del consumer group
docker compose exec redis redis-cli XPENDING whatsapp_messages chatbot_workers

# Inspeccionar la Dead Letter Queue
docker compose exec redis redis-cli XRANGE whatsapp_messages_dlq - +

# Ejecutar tres workers concurrentes
docker compose up -d --scale worker=3
```

## Persistencia multi-tenant

El esquema aplica aislamiento en tres niveles:

1. Todas las tablas de negocio incluyen `tenant_id` e índices orientados a sus consultas.
2. Las claves foráneas compuestas impiden relaciones cruzadas entre tenants.
3. PostgreSQL Row-Level Security usa `app.tenant_id`, establecido dentro de cada transacción por el repositorio.

La migración inicial crea:

- `tenants` y `services` para la configuración de cada empresa;
- `customers`, `conversations` y `messages` para la trazabilidad del chat;
- `appointments` para reservas, calendario y referencia de pago.

Las respuestas salientes también conservan la fuente de clasificación, modelo, versión del prompt, confianza, necesidad de intervención humana, tokens de entrada/salida, latencia y uso del fallback. No se fija un costo monetario en código porque las tarifas pueden cambiar; los tokens permiten calcularlo externamente con la tarifa vigente.

Para ejecutar manualmente las migraciones fuera de Docker:

```bash
export DATABASE_URL='postgresql+asyncpg://chatbot:chatbot@localhost:5432/chatbot'
alembic upgrade head
python -m app.infrastructure.seed
```

## Pruebas

```bash
python -m unittest discover -s tests -v
# o pytest, si instalaste las dependencias de desarrollo
```

Cubren autenticación, roles, sesiones, CSRF, agendamiento, idempotencia, opt-out, selección de adaptadores, salida estructurada, prompts dinámicos, fallback, persistencia y restricciones multi-tenant.

## Próximas fases

1. Google/Outlook Calendar y prevención transaccional de dobles reservas.
2. Stripe/Mercado Pago mediante webhooks firmados.
3. WhatsApp Cloud API real, métricas agregadas y panel administrativo.
