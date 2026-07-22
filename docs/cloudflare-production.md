# Despliegue de producción con Cloudflare

## Respuesta corta

La aplicación puede ejecutarse en producción con Cloudflare, pero el archivo `compose.yaml` actual describe un entorno local y no se despliega directamente. La opción más compatible con el backend actual es ejecutar la imagen de FastAPI en **Cloudflare Containers**, delante de un Worker, y mover los componentes con disco o procesos persistentes a servicios administrados.

## Arquitectura recomendada

```text
Internet / WhatsApp
        |
Cloudflare DNS + TLS + WAF + rate limiting
        |
Cloudflare Worker (routing y webhooks)
        |
Cloudflare Container (FastAPI)
        |---------------- PostgreSQL administrado
        |---------------- Cloudflare R2 (PDF e imágenes)
        |---------------- Cloudflare Queues (eventos asíncronos)
                                 |
                         Consumer Worker / Container
```

### Correspondencia con el entorno local

| Componente local | Producción propuesta |
| --- | --- |
| Contenedor `api` | Cloudflare Container detrás de un Worker |
| PostgreSQL Docker | PostgreSQL administrado y con TLS |
| Redis Streams | Cloudflare Queues o Redis administrado durante la transición |
| Volumen `chatbot_uploads` | Cloudflare R2 mediante API compatible con S3 |
| Variables `.env` | Cloudflare Secrets |
| Worker Python permanente | Consumidor de Cloudflare Queues |

## Decisiones importantes

- **FastAPI:** Cloudflare documenta soporte de FastAPI en Python Workers, pero Python Workers permanece en beta. Cloudflare Containers ejecuta la imagen Docker existente y es la opción con menos reescritura.
- **Arquitectura de CPU:** la imagen de Container debe construirse para `linux/amd64`.
- **Plan:** Containers requiere Workers Paid. Las instancias se inician bajo demanda y su ciclo de vida se controla desde un Worker.
- **Base de datos:** Cloudflare no sustituye el PostgreSQL relacional de este proyecto. Puede conectarse un PostgreSQL público administrado; Hyperdrive ofrece pool y aceleración para conexiones originadas en Workers.
- **Archivos:** el disco del Container es efímero. PDF e imágenes deben pasar a R2 antes de producción.
- **Eventos:** Queues entrega al menos una vez, por lo que debe conservarse la deduplicación por `tenant_id + message_id` ya presente en el dominio.
- **Secretos:** claves de base de datos, cifrado y proveedores de IA deben configurarse como Secrets, nunca como variables públicas ni archivos versionados.

## Ruta de migración

1. Mantener el backend actual y probar la imagen para `linux/amd64`.
2. Sustituir `KnowledgeFileStore` por un adaptador R2 compatible con el puerto actual.
3. Añadir un adaptador de Cloudflare Queues manteniendo Redis como opción local.
4. Crear el Worker de entrada que enrute tráfico al Container.
5. Conectar PostgreSQL administrado con TLS y ejecutar `alembic upgrade head` como tarea de despliegue.
6. Configurar dominio, TLS, WAF, rate limiting del login y secretos.
7. Probar restauración, observabilidad, webhooks, reintentos y rollback antes de habilitar tráfico real.

## Documentación oficial

- [Cloudflare Containers](https://developers.cloudflare.com/containers/)
- [FastAPI en Python Workers](https://developers.cloudflare.com/workers/languages/python/packages/fastapi/)
- [Cloudflare Hyperdrive](https://developers.cloudflare.com/hyperdrive/get-started/)
- [Cloudflare Queues](https://developers.cloudflare.com/queues/)
- [Garantías de entrega de Queues](https://developers.cloudflare.com/queues/reference/delivery-guarantees/)
- [Cloudflare R2 con API S3](https://developers.cloudflare.com/r2/get-started/s3/)
- [Cloudflare Secrets](https://developers.cloudflare.com/workers/configuration/secrets/)
