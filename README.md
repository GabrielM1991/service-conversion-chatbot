# Plataforma de Conversión y Agendamiento Automatizado

Primera fase de un chatbot SaaS multi-tenant para empresas de servicios. El webhook acepta el mensaje inmediatamente y publica un evento; un worker ejecuta el pipeline, clasifica la intención y selecciona una estrategia de negocio.

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

Los datos en memoria hacen que el ejemplo se ejecute sin cuentas externas. Los límites hexagonales permiten cambiar cada fake por PostgreSQL, Redis, RabbitMQ, Google Calendar, Stripe y WhatsApp Cloud API sin modificar las reglas centrales.

## Ejecutar

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

## Pruebas

```bash
python -m unittest discover -s tests -v
# o pytest, si instalaste las dependencias de desarrollo
```

Cubren agendamiento, idempotencia, opt-out y aislamiento de tenant.

## Próximas fases

1. PostgreSQL con Row-Level Security y migraciones Alembic.
2. Redis para idempotencia y RabbitMQ/SQS para eventos durables con reintentos y DLQ.
3. Adaptador LLM con salida estructurada y guardrails.
4. Google/Outlook Calendar y prevención transaccional de dobles reservas.
5. Stripe/Mercado Pago mediante webhooks firmados.
6. WhatsApp Cloud API real, observabilidad y panel administrativo.
