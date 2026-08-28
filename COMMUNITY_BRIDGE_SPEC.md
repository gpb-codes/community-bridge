# COMMUNITY BRIDGE
## Sistema bidireccional automático WhatsApp ↔ Discord

Plataforma que conecta una comunidad de WhatsApp con un servidor de Discord mediante un backend central.

La idea NO es crear simplemente un bot que reenvíe algunos anuncios.

Se crea un sistema de **sincronización bidireccional de comunidades**, donde cada grupo de WhatsApp tenga un canal correspondiente en Discord y cada canal sincronizado de Discord tenga su espacio correspondiente en WhatsApp.

Arquitectura conceptual:

WhatsApp
↓
Community Bridge
↓
Discord

Y en sentido contrario:

Discord
↓
Community Bridge
↓
WhatsApp

Ambas direcciones deben estar habilitadas.

---

# 1. OBJETIVO PRINCIPAL

Cuando una persona escriba en un grupo de WhatsApp conectado:

WhatsApp → Grupo "Inteligencia Artificial"
mensaje: "¿Qué modelo están utilizando?"

el Bridge debe detectar el mensaje y enviarlo automáticamente al canal correspondiente:

Discord → #inteligencia-artificial
🟢 **[WhatsApp] Gabriel**
¿Qué modelo están utilizando?

Si una persona responde desde Discord:

🟣 **[Discord] Pedro**
Estoy utilizando Qwen.

el sistema debe enviar automáticamente esa respuesta al grupo de WhatsApp correspondiente:

🟣 **[Discord] Pedro**
Estoy utilizando Qwen.

Los usuarios de ambas plataformas deben poder visualizar el contenido sincronizado.

No debe existir una plataforma principal. WhatsApp y Discord deben funcionar como dos interfaces de la misma conversación.

---

# 2. MAPEO AUTOMÁTICO

Cada espacio debe tener una relación:

WhatsApp Group ↔ Discord Channel

Ejemplo:
WhatsApp "IA" ↔ Discord #ia
WhatsApp "Programación" ↔ Discord #programacion
WhatsApp "Ciberseguridad" ↔ Discord #ciberseguridad

El sistema debe almacenar este vínculo en la base de datos:

mapping_id / whatsapp_group_id / discord_guild_id / discord_channel_id / status / created_at / updated_at

---

# 3. CREACIÓN AUTOMÁTICA

Detectar automáticamente nuevos espacios cuando la API oficial lo permita.

Nuevo grupo de WhatsApp "Desarrollo Web" → NEW_WHATSAPP_GROUP → buscar canal equivalente en Discord.
Si no existe: 1) Crear canal Discord, 2) Asignar nombre, 3) Crear mapping, 4) Registrar evento, 5) Activar sincronización.

Resultado: WhatsApp "Desarrollo Web" ↔ Discord #desarrollo-web

---

# 4. CREACIÓN DESDE DISCORD

Al revés cuando sea técnicamente posible.

Nuevo canal Discord #machine-learning → NEW_DISCORD_CHANNEL → comprobar grupo correspondiente en WhatsApp.
Si la API oficial de WhatsApp permite crear grupos: 1) Crear grupo, 2) Asignar nombre, 3) Crear mapping, 4) Activar sincronización.

Si WhatsApp NO permite crear grupos automáticamente: NO scraping, NO WhatsApp Web, NO métodos que bloqueen.
En ese caso: 1) Registrar canal como "Pending", 2) Mostrar en dashboard que requiere configuración manual, 3) Permitir al admin completar la vinculación, 4) Mantener preparado para automatizar si la API lo permite.

---

# 5. DETECCIÓN DE NUEVOS CANALES

El bot de Discord debe escuchar: creación/eliminación/modificación de canales, creación/modificación de categorías.

NEW_CHANNEL → Event → Bridge Core → Detect Channel → Check Mapping → Mapping exists?
├── YES → actualizar información
└── NO → crear/solicitar contraparte

---

# 6. DETECCIÓN DE NUEVOS GRUPOS DE WHATSAPP

Mecanismo basado exclusivamente en capacidades oficiales de WhatsApp.
Analizar eventos disponibles para grupos, comunidades, mensajes, cambios de grupo, miembros, administración.
Si existe webhook/evento oficial para nuevos grupos, usarlo.
Si NO existe: NO inventar endpoint, NO scraping, NO WhatsApp Web automatizado.
Crear abstracción `WhatsAppGroupDiscoveryAdapter`.

---

# 7. SINCRONIZACIÓN BIDIRECCIONAL

Todos los mappings activos funcionan en ambos sentidos.
Estado normal: BIDIRECTIONAL.
Estados posibles: ACTIVE / DEGRADED / PENDING / DISABLED / ERROR.

---

# 8. MENSAJES

WhatsApp → Webhook/Event → Message Queue → Message Router → Find Mapping → Discord Adapter → Discord Channel.
Discord → Discord Event → Message Queue → Message Router → Find Mapping → WhatsApp Adapter → WhatsApp Group.

---

# 9. IDENTIFICACIÓN DE ORIGEN

WhatsApp → Discord:
🟢 [WhatsApp] Gabriel
Hola, ¿alguien está trabajando con agentes de IA?

Discord → WhatsApp:
🟣 [Discord] Pedro
Sí, estoy desarrollando uno en Python.

Los prefijos deben ser configurables.

---

# 10. EVITAR LOOPS

Crítico. Cada mensaje sincronizado debe tener metadata:
message_id / source_platform / source_message_id / source_channel_id / destination_platform / destination_channel_id / bridge_generated / created_at

bridge_generated = true en mensajes generados por el Bridge → no vuelven a la plataforma origen.
Implementar: deduplicación, idempotencia, correlation IDs, message mappings.

---

# 11. RESPUESTAS Y THREADS

Preservar contexto cuando ambas plataformas lo permitan. Convertir al formato disponible manteniendo referencia al mensaje original.

---

# 12. ARCHIVOS Y MULTIMEDIA

Soporte: texto, imágenes, documentos, audio, vídeo, archivos. Implementar cada tipo sólo cuando ambas APIs lo permitan.
Procesar mediante almacenamiento temporal seguro cuando sea necesario.

---

# 13. NOMBRES AUTOMÁTICOS

`normalize_channel_name()`:
"Inteligencia Artificial" → `inteligencia-artificial`
"Ciberseguridad Chile" → `ciberseguridad-chile`
"Programación 💻" → `programacion`
Evitar caracteres incompatibles con Discord. Mantener nombre original en DB.

---

# 14. CATEGORÍAS DE DISCORD

Reflejar estructura de comunidades/categorías de WhatsApp en Discord cuando sea posible.
Cada grupo tiene su mapping independiente.

---

# 15. DASHBOARD

Panel web de administración. Secciones: Dashboard, Connections, WhatsApp, Discord, Mappings, Channels, Groups, Messages, Users, Logs, Settings.

Dashboard:
WhatsApp CONNECTED / Discord CONNECTED
Mappings 18 / Active 17 / Pending 1 / Errors 0
Messages today 1,248

---

# 16. MAPINGS

Interfaz para visualizar:
WhatsApp Group | Discord Channel | Estado
IA | #ia | 🟢 Active
Permitir: desvincular, volver a vincular, cambiar canal, pausar, eliminar, sincronización manual.

---

# 17. AUTO-DISCOVERY

Servicio `AutoDiscoveryService`:
detect_new_whatsapp_spaces() / detect_new_discord_channels() / detect_deleted_spaces() / detect_renamed_spaces() / reconcile_mappings().
Eventos/webhooks cuando estén disponibles; polling sólo si es oficialmente permitido y necesario.
Reconciliación periódica cada X minutos.

---

# 18. RECONCILIACIÓN

Servicio `MappingReconciliationService`:
Detectar canales/grupos eliminados, renombrados, mappings rotos, duplicados.
Nunca eliminar información automáticamente sin registrar el cambio.

---

# 19. BASE DE DATOS

PostgreSQL. Tablas mínimas:
communities / platforms / platform_connections / users / platform_users / whatsapp_groups / discord_guilds / discord_channels / channel_mappings / messages / message_mappings / media / events / sync_rules / audit_logs / errors

---

# 20. ARQUITECTURA

Arquitectura modular. API/Core → Event System + Message Router → WhatsApp Adapter / Discord Adapter.
Separar lógica de negocio de APIs externas.

---

# 21. STACK

Backend: Python + FastAPI
Workers: Celery o alternativa
Queue: Redis
Database: PostgreSQL
Frontend: React / Next.js
Discord: Discord API oficial
WhatsApp: WhatsApp Business Platform / Cloud API oficial
Deployment: Docker Compose

---

# 22. SEGURIDAD

OAuth cuando corresponda, Webhook verification, Rate limiting, Permission system, Audit logs, Secret management, Token encryption, Input validation, Retry policies, Idempotency, Protección contra replay attacks, Control de acceso administrativo.
Nunca guardar contraseñas. Nunca incluir tokens reales en Git. Crear `.env.example`.

---

# 23. PERMISOS DE DISCORD

Solo permisos necesarios: leer mensajes, enviar mensajes, detectar creación/modificación de canales, administrar canales sólo si auto-creación lo requiere. No admin global innecesario.

---

# 24. COLA DE MENSAJES

Webhook → Validate → Event Queue → Worker → Router → Adapter → Destination.

---

# 25. REINTENTOS

Failed → Retry Queue → Retry (exponential backoff) → Success. No duplicar durante reintentos.

---

# 26. OBSERVABILIDAD

Logs estructurados. No registrar secretos.

---

# 27. SOPORTE MULTICOMUNIDAD

Community A/B/C cada una con sus propias conexiones y mappings. Un error en A no afecta B.

---

# 28. FUTURAS PLATAFORMAS

Adapters para WhatsApp, Discord, Telegram, Web, Matrix, Slack.
`class PlatformAdapter: receive_event() / send_message() / create_space() / update_space() / delete_space() / list_spaces()`
Cada plataforma implementa sólo lo que soporte.

---

# 29. REGLA FUNDAMENTAL SOBRE WHATSAPP

Antes de implementar cualquier funcionalidad de WhatsApp: INVESTIGAR capacidades actuales de la API oficial.
No asumir que WhatsApp permite detectar/crear/leer/enviar/modificar grupos arbitrarios.
Si no está disponible oficialmente: NO simular, NO scraping, NO WhatsApp Web automatizado, NO evadir restricciones.
Marcar capacidad como `NOT_SUPPORTED` y dar alternativa manual.

---

# 30. MVP

1. Conectar Discord
2. Conectar WhatsApp vía API oficial
3. Detectar mensajes
4. Crear mappings
5. Sincronizar WhatsApp → Discord
6. Sincronizar Discord → WhatsApp
7. Evitar loops
8. Registrar mensajes
9. Dashboard
10. Sistema de mappings
11. Auto-discovery de Discord
12. Auto-discovery de WhatsApp sólo si API oficial lo permite
13. Reintentos
14. Logs
15. Docker Compose

Después: multimedia, threads, respuestas, usuarios vinculados, categorías, estadísticas, múltiples comunidades, más plataformas.

---

# 31. RESULTADO ESPERADO

Una única comunidad aunque los miembros usen plataformas distintas. El Bridge determina automáticamente origen, mapping, destino, formato, anti-loop y registro de relación entre mensajes. El admin interviene sólo cuando una plataforma no permita automatizar.

---

# 32. PRIMERA TAREA

NO empezar escribiendo código inmediatamente. Primero:
1. Analizar arquitectura
2. Analizar APIs oficiales actuales de WhatsApp y Discord
3. Determinar qué funcionalidades son posibles
4. Identificar limitaciones de WhatsApp
5. Identificar limitaciones de Discord
6. Diseñar modelo de datos
7. Diseñar eventos
8. Diseñar sistema de mappings
9. Diseñar AutoDiscovery
10. Diseñar Message Router
11. Definir MVP
12. Explicar funcionalidad manual por limitaciones de API

Después de ese análisis, construir el proyecto.
NO inventar APIs. NO implementar funcionalidades que las plataformas no permitan.
