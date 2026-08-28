# Community Bridge

Sistema de **sincronización bidireccional de comunidades** entre **WhatsApp** y **Discord**,
con un backend central que enruta mensajes en ambas direcciones, previene loops,
y auto-descubre/mapea grupos ↔ canales.

> Ver [`ANALYSIS.md`](./ANALYSIS.md) para el análisis de viabilidad de APIs (Fase 0, sección 32 del spec).
> Ver [`COMMUNITY_BRIDGE_SPEC.md`](./COMMUNITY_BRIDGE_SPEC.md) para el spec original.

## Decisiones del MVP (definidas por el dueño)

- **WhatsApp NO es OBA** → `WHATSAPP_IS_OBA=false`. Grupos WA que no se puedan
  crear/descubrir oficialmente quedan en `PENDING`. La arquitectura ya usa
  `AdapterCapabilities` + reconciliación, así que al tener OBA solo se cambia la
  variable (sin reescribir el core) y los mappings `PENDING` se auto-completan.
- **Una sola comunidad** (`community_id="default"`) y un número de WhatsApp. El
  `community_id` viaja en todos los modelos para permitir multi-comunidad después.
- **Discord**: auto-creación de canales con `Manage Channels` + `View Channels`,
  `Send Messages`, `Read Message History`, `Message Content` intent. **Sin Administrator**.
- **Webhook**: listo en `/api/v1/webhooks/whatsapp`. En dev usar ngrok/Cloudflare
  Tunnel; en prod, dominio propio + proxy inverso (sin dependencia permanente de ngrok).
- **Auth**: `ADMIN_API_KEY` vía capa `app/auth.py` (`admin_auth`). Mecanismo aislado para
  cambiar a OAuth/JWT luego sin tocar las rutas.
- **MVP de texto**: bidireccional por defecto (`BIDIRECTIONAL`). Auto-mapping, detección
  de canales Discord, creación automática de canales Discord, mappings, anti-loop,
  deduplicación, logs, dashboard, cola y reintentos. Multimedia/threads avanzados en fase 2.
- **Threads/replies**: se aplanan a mensajes normales; la referencia al mensaje original
  se conserva en `Message.meta.reply_to`.
- **Formato**: prefijos `🟢 [WhatsApp]` / `🟣 [Discord]` (configurables vía settings;
  extensibles a config por dashboard en fase 2).

## Arquitectura

```
WhatsApp (Meta Cloud API / Groups API) ──┐
                                          ├──► Community Bridge (FastAPI + Celery + Redis + Postgres) ◄──┐
Discord (Gateway + REST) ────────────────┘                                                              │
                                                                                                        │
                       Dashboard (Next.js) ◄──── /api/v1 ────► mappings, messages, dashboard, webhooks   │
```

Flujo de un mensaje:

```
Webhook/Gateway → Validate + HMAC → Redis (Celery broker) → Worker → Message Router
→ find Mapping → Adapter destino → send → loop-guard mark → message_mappings
```

El **Gateway de Discord** (WebSocket de larga duración) corre dentro del **worker** de Celery,
porque el worker es quien realmente envía mensajes vía el cliente de Discord.

## Stack

- Backend: Python + FastAPI
- Workers: Celery (broker/backend: Redis)
- Queue: Redis
- DB: PostgreSQL
- Frontend: Next.js (App Router)
- Discord: Discord API oficial (`discord.py`)
- WhatsApp: WhatsApp Business Platform / Cloud API + Groups API (Meta oficial)

## Puesta en marcha (Docker Compose)

```bash
cp .env.example .env
# Rellena DISCORD_BOT_TOKEN, WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID,
# WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN, DISCORD_GUILD_ID, ADMIN_API_KEY
docker compose up --build
```

- API:        http://localhost:8000
- Docs:       http://localhost:8000/docs
- Dashboard:   http://localhost:3000
- Worker:     `celery -A app.workers.celery_app.celery_app worker -Q bridge`

## Configuración de plataformas

### Discord
1. Crea una app/bot en https://discord.com/developers/applications
2. Invita el bot con permisos mínimos: `View Channels`, `Send Messages`,
   `Read Message History`, y `Manage Channels` (solo si quieres auto-creación).
3. Habilita el intent privilegiado **Message Content**.
4. Pega `DISCORD_BOT_TOKEN` y `DISCORD_GUILD_ID`.

### WhatsApp (Meta)
1. Crea una app con producto **WhatsApp** en Meta for Developers.
2. La **Groups API** requiere una cuenta **Official Business Account (OBA)**.
   Si `WHATSAPP_IS_OBA=false`, la creación automática de grupos y el discovery
   caen a `MANUAL` (mapping `PENDING`).
3. Configura el webhook HTTPS apuntando a `/api/v1/webhooks/whatsapp`
   con `WHATSAPP_VERIFY_TOKEN` y `WHATSAPP_APP_SECRET` (verificación HMAC).

## Funcionalidad MANUAL (limitaciones de API oficiales)

| Funcionalidad | Razón | Comportamiento |
| --- | --- | --- |
| Crear grupo de WhatsApp automático | Requiere OBA + Groups API | Si no es OBA → mapping `PENDING`; el admin crea el grupo y usa `POST /mappings/manual-link` |
| Jerarquía "comunidades" de WhatsApp | No existe API de comunidades | Se modela en BD; el admin mapea grupos manualmente |
| Mensajes interactivos/encuestas en grupos WA | No soportado por Groups API | No se reenvían |
| Verificación de empresa/cuenta | Proceso Meta fuera del código | Documentado arriba |

**Nunca** se usa scraping ni WhatsApp Web automatizado (sección 29 del spec).

## Prevención de loops (sección 10)

- Mensajes enviados por el bot de Discord se ignoran (`author.bot`).
- `bridge_generated` se marca en Redis por `platform:message_id` (TTL 24h).
- Deduplicación por firma `(source_platform, source_message_id, content)`.
- `message_mappings` guarda la correlación origen→destino.

## Estructura

```
backend/app/
  config.py            settings (Pydantic)
  database.py          engine / session
  models.py            17 tablas (sección 19)
  schemas.py           Pydantic
  logging.py           logs estructurados JSON
  security.py          HMAC webhook, admin key, replay
  adapters/            base (ABC) + discord_adapter + whatsapp_adapter + discord_bot (Gateway)
  services/            normalize, message_router, auto_discovery, reconciliation, dispatch
  events/bus.py        Redis queue + loop-guard + dedup
  workers/celery_app.py
  api/api.py           rutas (webhooks, mappings, messages, dashboard, events)
frontend/              Next.js dashboard
docker-compose.yml
```

## Endpoints principales (todas las admin requieren `Authorization: Bearer <ADMIN_API_KEY>`)

- `GET  /api/v1/health`
- `GET  /api/v1/webhooks/whatsapp`  (verificación Meta)
- `POST /api/v1/webhooks/whatsapp`  (recepcíon de mensajes/grupos)
- `GET  /api/v1/dashboard`
- `GET  /api/v1/mappings`, `POST /mappings`, `POST /mappings/manual-link`
- `PATCH /mappings/{id}/status`, `PATCH /mappings/{id}/direction`
- `DELETE /mappings/{id}`, `POST /mappings/{id}/sync-now`
- `GET  /api/v1/messages`, `GET /api/v1/events`, `GET /api/v1/connections`
