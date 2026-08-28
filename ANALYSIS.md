# COMMUNITY BRIDGE — Análisis de Viabilidad y Diseño (Fase 0)

Este documento es la entrega de la **PRIMERA TAREA** (sección 32 del spec). Se analizan
las APIs oficiales actuales (2026), sus limitaciones reales, y el diseño antes de escribir código.
**No se inventan APIs.** Todo lo aquí afirmado se basa en la documentación oficial de Meta y Discord.

---

## 1. Capacidades actuales de WhatsApp (Oficial Business Platform / Cloud API)

Fuente: Meta for Developers — Groups API (actualizado Jun 2026), Group Messaging, Webhooks.

### 1.1 Descubrimiento y gestión de grupos — ¡AHORA SÍ DISPONIBLE!
La **Groups API** está abierta desde 2026 para cuentas **Official Business Account (OBA)**.
Capacidades oficiales:
- **Crear grupo** (`POST /{phone_number_id}/groups`) — AUTO-CREACIÓN DESDE DISCORD POSIBLE.
- **Eliminar grupo**, **get group info**, **get active groups**, **reset invite link**.
- **Webhooks de lifecycle**: `group_lifecycle_update`, `group_participants_update`,
  `group_settings_update`, `group_status_update`. → AUTO-DISCOVERY DE NUEVOS GRUPOS POSIBLE vía webhook.
- **Recibir mensajes de grupo**: webhook `messages` incluye campo `group_id`.
- **Enviar mensaje a grupo**: `POST /{phone_number_id}/messages` con `recipient_type: "group"`.

### 1.2 Limitaciones / NO SOPORTADO en grupos (oficial)
- Máx **8 participantes** por grupo.
- Máx **10.000 grupos** por número de negocio.
- **No disponible** para números de la app de WhatsApp Business ni Multi-solution Conversations.
- Mensajes NO soportados en grupos: calling, disappearing, view-once, auth, commerce,
  **interactive messages**, edit message, delete message, admin hide participant list.
- No hay "comunidades" ni "categorías" expuestas vía API (no existe contraparte de las
  categorías de Discord). → Las categorías de Discord (sección 14) solo se reflejan
  **manualmente** desde Discord hacia la estructura lógica; WhatsApp no agrupa grupos por API.

### 1.3 Implicaciones para el spec
| Requisito spec | Veredicto oficial |
| --- | --- |
| 3. Crear grupo WhatsApp al crear canal Discord | ✅ POSIBLE (OBA + Groups API) |
| 6. Detección automática de nuevos grupos WhatsApp | ✅ POSIBLE (webhook `group_lifecycle_update`) |
| 14. Categorías/comunidades de WhatsApp→Discord | ⚠️ PARCIAL — no hay API de comunidades; se modela en DB pero sin auto-sync de jerarquía |
| 12. Multimedia en grupos | ✅ texto + media soportados |
| 11. Threads/replies | ⚠️ WhatsApp grupos no tienen threads API; se aplana a texto |

> **Nota de diseño**: Si la cuenta NO es OBA, la creación automática de grupos y el
> discovery quedan marcados `NOT_SUPPORTED` y el sistema cae al flujo manual (sección 4).

---

## 2. Capacidades actuales de Discord (API oficial)

Fuente: Discord Developer Portal — Channels, Gateway Events, Intents, Webhooks.

### 2.1 Totalmente soportado
- **Gateway (WebSocket)** para eventos en tiempo real: `MESSAGE_CREATE`, `CHANNEL_CREATE`,
  `CHANNEL_UPDATE`, `CHANNEL_DELETE`, `THREAD_CREATE`, `GUILD_CREATE`.
- **REST**: crear/editar/eliminar canal (`POST /guilds/{id}/channels`),
  enviar mensaje (`POST /channels/{id}/messages`), webhooks.
- **Intents requeridos**: `GUILDS`, `GUILD_MESSAGES`, y privilegiado `MESSAGE_CONTENT`.
- **Categorías**: los canales tienen `parent_id` (categoría) → sección 14 totalmente soportada.
- **Threads**: `THREAD_CREATE`, `Start Thread from Message` → sección 11 soportada (limitada).

### 2.2 Limitaciones
- Bot es un proceso **stateful** de larga duración (Gateway). Se ejecuta en su propio contenedor/thread.
- Permisos mínimos: `View Channels`, `Send Messages`, `Manage Channels` (solo para auto-creación),
  `Read Message History`. NO se piden permisos de admin global.
- A partir de Nov 2026: canales ofuscados si el bot no tiene `VIEW_CHANNEL` → el discovery debe
  ignorar canales ofuscados (`flags & CHANNEL_OBFUSCATED`).

---

## 3. Modelo de datos (PostgreSQL)

Se implementan las 17 tablas del spec (sección 19). Resumen de relaciones:

- `communities` 1—N `platform_connections` (whatsapp/discord)
- `whatsapp_groups` 1—1 `channel_mappings` (vía `discord_channels`)
- `discord_guilds` 1—N `discord_channels`
- `channel_mappings` (estado: ACTIVE/DEGRADED/PENDING/DISABLED/ERROR, dirección: BIDIRECTIONAL)
- `messages` → `message_mappings` (correlation / loop prevention)
- `media`, `events`, `sync_rules`, `audit_logs`, `errors` para trazabilidad.

Ver `backend/app/models.py`.

---

## 4. Eventos

```
WhatsApp webhook (Meta)         Discord Gateway event
  messages(group_id)    ──┐       MESSAGE_CREATE
  group_lifecycle_update─┤         CHANNEL_CREATE / UPDATE / DELETE
                         │         THREAD_CREATE
                         ▼
                  [ Validate + HMAC ]
                         ▼
                  [ Redis Event Queue ]
                         ▼
                  [ Celery Worker ]
                         ▼
                  [ Message Router / AutoDiscovery / Reconciliation ]
                         ▼
                  [ Adapter destino (send) ]
```

---

## 5. Sistema de Mappings + Auto-Discovery + Reconciliation

- `normalize_channel_name()` convierte "Inteligencia Artificial" → `inteligencia-artificial`.
- `AutoDiscoveryService`:
  - Discord: vía eventos `CHANNEL_CREATE`/`DELETE`/`UPDATE` (tiempo real) + reconcile periódico.
  - WhatsApp: vía webhook `group_lifecycle_update` + polling "get active groups" (oficial).
- `MappingReconciliationService`: detecta eliminados/renombrados/rotos/duplicados y registra en
  `audit_logs` SIN borrar datos automáticamente.

---

## 6. Message Router + Anti-Loop (sección 10)

Cada mensaje saliente del Bridge se marca en Redis (`bridge_generated:{platform}:{msg_id}`, TTL).
Al recibir evento:
1. ¿El `message_id` está en `bridge_generated`? → descartar (evita eco).
2. ¿Existe `channel_mappings` activo para el par? → si no, registrar y salir.
3. Construir payload con prefijo configurable `[WhatsApp]` / `[Discord]`.
4. Enviar vía adapter destino; guardar `message_mappings` (correlation id).

Idempotencia: dedupe por `source_message_id` + hash de contenido.

---

## 7. MVP (sección 30) — alcance implementado

1-15 del spec se implementan. Media/threads se implementan donde ambas APIs lo permiten
(texto + media en ambas; threads se aplanan en WhatsApp).

---

## 8. Funcionalidad MANUAL por limitaciones de API (sección 32.12)

| Funcionalidad | Razón | Solución en Community Bridge |
| --- | --- | --- |
| Crear grupo WhatsApp automático | Requiere cuenta **OBA** | Si no es OBA → mapping `PENDING` + vinculación manual en dashboard |
| Jerarquía de "comunidades" WhatsApp | No existe API de comunidades | Se modela en DB; el admin crea grupos y los mapea manualmente |
| Mensajes interactivos/encuestas en grupos WA | No soportado por Groups API | No se reenvían; se registra `NOT_SUPPORTED` |
| Verificación de número/empresa | Proceso Meta fuera del código | Documentado en README; el admin aporta tokens |

**Nunca** se usa scraping ni WhatsApp Web automatizado.
