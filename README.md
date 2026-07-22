# Plataforma de Conversión y Agendamiento Automatizado

Chatbot SaaS multi-tenant para empresas de servicios. El webhook acepta el mensaje inmediatamente y publica un evento; un worker ejecuta el pipeline, clasifica la intención, selecciona una estrategia y persiste la conversación sin mezclar datos entre negocios.

## Arquitectura

```text
WhatsApp webhook -> EventPublisher -> Worker -> MessagePipeline
                                             -> ChatbotAgentFactory
                                             -> IntentStrategy
                                             -> Calendar / Payment / Chat ports
```

- `app/domain`: entidades y puertos sin dependencias de frameworks.
- `app/application`: casos de uso, Chain of Responsibility, Factory y Strategy.
- `app/infrastructure`: adaptadores sustituibles; en esta fase son locales y deterministas.
- `app/main.py`: adaptador HTTP de FastAPI y ciclo de vida del worker.
- `migrations`: esquema PostgreSQL versionado y políticas Row-Level Security.

Los límites hexagonales permiten cambiar cada fake por Redis, RabbitMQ, Google Calendar, Stripe y WhatsApp Cloud API sin modificar las reglas centrales.

## Dos modos de ejecución

- **Memoria:** inicio rápido sin infraestructura. Mantiene los tenants de demostración, pero reiniciar la API borra el estado.
- **PostgreSQL:** persistencia de tenants, servicios, clientes, conversaciones, mensajes y citas. Se activa al definir `DATABASE_URL`.

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
{"status":"ok","storage":"memory"}
```

## Ejecutar con PostgreSQL y Docker

Requiere Docker Desktop. El siguiente comando levanta PostgreSQL, ejecuta la migración, carga dos tenants y arranca la API:

```bash
docker compose up --build
```

Cuando aparezca `Uvicorn running on http://0.0.0.0:8000`, abre `http://127.0.0.1:8000/docs`. En este modo `/health` devuelve `"storage":"postgresql"` y cada interacción queda guardada.

Para detener los contenedores:

```bash
docker compose down
```

El volumen `chatbot_postgres_data` conserva la base de datos entre reinicios. Solo usa `docker compose down -v` cuando quieras borrar expresamente todos los datos locales.

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

1. Redis para idempotencia y RabbitMQ/SQS para eventos durables con reintentos y DLQ.
2. Adaptador LLM con salida estructurada y guardrails.
3. Google/Outlook Calendar y prevención transaccional de dobles reservas.
4. Stripe/Mercado Pago mediante webhooks firmados.
5. WhatsApp Cloud API real, observabilidad y panel administrativo.
