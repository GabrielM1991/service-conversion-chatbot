# Despliegue y migración a Cloudflare

El archivo `compose.yaml` describe el entorno local y no se publica directamente en Cloudflare. El repositorio ofrece ahora dos rutas: conservar FastAPI dentro de un Container durante la transición, o migrar progresivamente a la base nativa implementada en [`cloudflare/`](../cloudflare/README.md).

## Base nativa ya implementada

```text
WhatsApp / Panel
       |
Cloudflare Worker
       |---- D1 (identidad y auditoría global)
       |---- Durable Object SQLite por tenant
       |---- Queue -> consumidor idempotente -> DLQ
       |---- SQLite por tenant (textos y fragmentos)
       `---- Workers AI -> Vectorize (referencias con filtro tenantId)
```

La base recibe webhooks firmados, publica mensajes sin bloquear la petición, deduplica dentro del espacio privado del tenant y permite guardar/buscar texto de conocimiento. También incorpora panel responsive, propietarios, sesiones, roles, configuración del bot e integraciones cifradas de Meta/WhatsApp, Workers AI, OpenAI y Anthropic. PDF/imágenes, el uso conversacional efectivo del proveedor elegido y la respuesta saliente permanecen todavía en FastAPI.

## Ruta híbrida con el backend existente

```text
Internet / WhatsApp
        |
Cloudflare DNS + TLS + WAF + rate limiting
        |
Cloudflare Worker (routing y webhooks)
        |
Cloudflare Container (FastAPI)
        |---------------- PostgreSQL administrado
        |---------------- almacenamiento de objetos externo (PDF e imágenes)
        `---------------- Cloudflare Queues
```

| Componente local | Producción híbrida |
| --- | --- |
| Contenedor `api` | Cloudflare Container detrás de un Worker |
| PostgreSQL Docker | PostgreSQL administrado y con TLS |
| Redis Streams | Cloudflare Queues o Redis administrado durante la transición |
| Volumen `chatbot_uploads` | Almacenamiento de objetos compatible |
| Variables `.env` | Cloudflare Secrets |
| Worker Python permanente | Consumidor de Cloudflare Queues |

## Decisiones importantes

- **FastAPI:** Cloudflare documenta FastAPI en Python Workers, pero Python Workers permanece en beta. Containers exige menos reescritura para la ruta híbrida.
- **Base nativa:** D1 conserva identidad global; cada Durable Object proporciona almacenamiento SQLite privado y consistente para una empresa.
- **Conocimiento:** el texto y sus fragmentos viven en SQLite por tenant; no se requiere R2 para esta fase.
- **Archivos:** SQLite no es adecuado para PDF e imágenes grandes. Sus binarios requerirán R2 u otro almacenamiento de objetos cuando se implemente esa fase.
- **Eventos:** Queues entrega al menos una vez, por lo que la deduplicación es obligatoria. La base nativa ya la aplica por `tenant + message_id`.
- **Secretos:** claves de Meta, IA, cifrado y pagos deben configurarse como Secrets, nunca como variables públicas o archivos versionados.

## Orden de migración recomendado

1. Aprovisionar D1, Queues y Vectorize siguiendo el README de `cloudflare/`.
2. Desplegar el Worker y validar el webhook firmado con un tenant de prueba.
3. Crear propietarios desde `/setup`, validar sesiones y configurar bot e integraciones desde `/admin`.
4. Añadir extracción segura de PDF e imágenes y elegir almacenamiento de objetos para sus binarios.
5. Portar el orquestador, utilizar el proveedor configurado y habilitar el envío real mediante WhatsApp Cloud API.
6. Integrar Calendar y pagos con webhooks idempotentes.
7. Importar datos existentes, probar rollback y cambiar DNS cuando exista paridad funcional.

## Documentación oficial

- [Cloudflare Workers](https://developers.cloudflare.com/workers/)
- [Cloudflare D1](https://developers.cloudflare.com/d1/)
- [Cloudflare Durable Objects](https://developers.cloudflare.com/durable-objects/)
- [Cloudflare Queues](https://developers.cloudflare.com/queues/)
- [Garantías de entrega de Queues](https://developers.cloudflare.com/queues/reference/delivery-guarantees/)
- [Cloudflare Vectorize](https://developers.cloudflare.com/vectorize/)
- [Workers AI](https://developers.cloudflare.com/workers-ai/)
- [Cloudflare Secrets](https://developers.cloudflare.com/workers/configuration/secrets/)
