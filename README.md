# Plataforma de Conversión y Agendamiento Automatizado

Chatbot SaaS multi-tenant para empresas de servicios. El webhook deduplica y publica cada mensaje en Redis Streams; un worker independiente ejecuta el pipeline, clasifica la intención, selecciona una estrategia y persiste la conversación sin mezclar datos entre negocios.

## Arquitectura

```text
WhatsApp webhook -> Redis Stream -> Consumer Group -> Worker
                                                    -> MessagePipeline
                                                    -> ChatbotAgentFactory
                                                    -> IntentStrategy
                                                    -> Calendar / Payment / Chat ports
                                      failures -> Retry -> Dead Letter Queue
```

- `app/domain`: entidades y puertos sin dependencias de frameworks.
- `app/application`: casos de uso, Chain of Responsibility, Factory y Strategy.
- `app/infrastructure`: adaptadores sustituibles; en esta fase son locales y deterministas.
- `app/worker.py`: consumidor independiente del proceso HTTP.
- `app/main.py`: adaptador HTTP de FastAPI y ciclo de vida del worker.
- `migrations`: esquema PostgreSQL versionado y políticas Row-Level Security.

Los límites hexagonales permiten cambiar cada fake por Redis, RabbitMQ, Google Calendar, Stripe y WhatsApp Cloud API sin modificar las reglas centrales.

## Dos modos de ejecución

- **Memoria:** inicio rápido sin infraestructura; API y worker comparten una cola local.
- **PostgreSQL:** persistencia de tenants, servicios, clientes, conversaciones, mensajes y citas. Se activa con `DATABASE_URL`.
- **Redis Streams:** cola durable, deduplicación y opt-out persistentes. Se activa con `REDIS_URL` y separa API/worker.

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
{"status":"ok","storage":"memory","broker":"memory"}
```

## Ejecutar con PostgreSQL y Docker

Requiere Docker Desktop. El siguiente comando levanta PostgreSQL, Redis con AOF, ejecuta la migración, carga dos tenants y arranca API y worker:

```bash
docker compose up --build
```

Cuando aparezcan la API y el worker como activos, abre `http://127.0.0.1:8000/docs`. En este modo `/health` devuelve:

```json
{"status":"ok","storage":"postgresql","broker":"redis-streams"}
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

Cubren agendamiento, idempotencia, opt-out, selección de adaptadores, persistencia del flujo y restricciones multi-tenant.

## Próximas fases

1. Adaptador LLM con salida estructurada y guardrails.
2. Google/Outlook Calendar y prevención transaccional de dobles reservas.
3. Stripe/Mercado Pago mediante webhooks firmados.
4. WhatsApp Cloud API real, observabilidad y panel administrativo.
