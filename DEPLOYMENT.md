# DEPLOYMENT.md — Community Bridge

Guía para desplegar Community Bridge en un servidor nuevo usando Docker Compose.
El objetivo es que tras clonar el repo y configurar `.env` puedas levantar todo con:

```bash
git clone <REPO>
cd community-bridge
cp .env.example .env
# editar .env con tus secretos reales
docker compose up -d --build
```

---

## 1. Requisitos del servidor

- Linux (Ubuntu 22.04+ / Debian 12 recomendado), o cualquier host con Docker.
- Docker Engine 24+ y Docker Compose v2 (`docker compose` plugin).
- Al menos 1 vCPU y 1 GB RAM (2 GB recomendado para Postgres + Redis + 2 contenedores Python).
- Puertos: `80/443` (proxy/HTTPS), `8000` (API, opcional exponer solo tras proxy),
  `3000` (frontend, opcional tras proxy). Redis/Postgres NO se exponen públicamente.
- Un nombre de dominio propio (para el webhook HTTPS de WhatsApp y el dashboard).
- Cuenta de Discord con permisos para crear una app/bot.
- Cuenta de Meta Business + número de WhatsApp (OBA recomendado; ver README).

---

## 2. Instalación de Docker

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER   # cierra sesión y vuelve a entrar
docker compose version          # verifica
```

---

## 3. Clonación del repositorio

```bash
git clone <REPO> community-bridge
cd community-bridge
cp .env.example .env
```

> **Nunca** commits `.env`. Está en `.gitignore`. Solo `.env.example` (placeholders) se sube.

---

## 4. Configuración de `.env`

Edita `.env` y completa al menos:

| Variable | Para qué |
| --- | --- |
| `ADMIN_API_KEY` | Autenticación del dashboard/API. **Cámbiala** por un secreto fuerte. |
| `DISCORD_BOT_TOKEN` | Token del bot de Discord. |
| `DISCORD_GUILD_ID` | ID del servidor donde se auto-crean canales. |
| `WHATSAPP_IS_OBA` | `true` si tu cuenta es Official Business Account. |
| `WHATSAPP_TOKEN` | Token de sistema (Bearer) del Cloud API. |
| `WHATSAPP_PHONE_NUMBER_ID` | ID del número de teléfono. |
| `WHATSAPP_APP_SECRET` | App Secret (verificación HMAC del webhook). |
| `WHATSAPP_VERIFY_TOKEN` | Token que tú defines para el challenge de Meta. |
| `DATABASE_URL` / `REDIS_URL` | Déjalos igual si usas los servicios de compose. |

No pongas `Administrator` en el bot de Discord. No incluyas tokens reales en el repo.

---

## 5. Configuración de PostgreSQL

El compose levanta Postgres con usuario/clave/db `bridge`. Para producción puedes:

- **Opción A (simple):** dejar el servicio `postgres` de compose. Cambia la clave en
  `docker-compose.yml` (o vía `.env` si parametrizas) y en `DATABASE_URL`.
- **Opción B (gestionado):** apunta `DATABASE_URL` a tu instancia gestionada y elimina el
  servicio `postgres` del compose.

El esquema se crea automáticamente al arrancar el backend (`init_db` → `create_all`).
No se requieren migraciones manuales para el MVP. (Ver "Migraciones" abajo.)

---

## 6. Configuración de Redis

El compose levanta Redis. Para producción: usa Redis con contraseña (`redis://:pass@host:6379/0`)
o una instancia gestionada, y actualiza `REDIS_URL`, `CELERY_BROKER_URL` y `CELERY_RESULT_BACKEND`.
Redis solo debe ser accesible desde la red interna (no lo expongas).

---

## 7. Ejecución de Docker Compose

```bash
docker compose up -d --build
```

Esto construye y levanta: `postgres`, `redis`, `backend` (FastAPI), `worker` (Celery) y `frontend` (Next.js).
Ver estado:

```bash
docker compose ps
docker compose logs -f backend
```

---

## 8. Migraciones de base de datos

No hay un paso de migración separado: el backend ejecuta `Base.metadata.create_all` al iniciar
(lifespan → `init_db`) y crea las 17 tablas + la comunidad `default` y las conexiones de plataforma.
Para un flujo de migraciones versionadas en el futuro, se recomienda agregar **Alembic**; mientras
tanto, los cambios de esquema se aplican recreando/actualizando tablas en desarrollo.

Si cambias el modelo (`app/models.py`), en desarrollo puedes borrar el volumen (`docker compose down -v`)
para recrear el esquema; en producción haz un backup antes.

---

## 9. Seed de desarrollo

El seed mínimo (comunidad `default` + filas `platform_connections`) es **automático** en `init_db`.
No se incluye aún un seed de mappings de ejemplo; los mappings se crean por auto-discovery (Discord)
o manualmente desde el dashboard (`POST /api/v1/mappings/manual-link`). Cuando se implemente un seed
de prueba, se documentará aquí y se ejecutará con un comando tipo `docker compose exec backend python -m app.seed`.

---

## 10. Health checks

- `postgres` y `redis` tienen healthcheck nativo en compose.
- `backend` tiene healthcheck contra `GET /api/v1/health` (requiere `200`).
- Comprueba: `curl https://tu-dominio/api/v1/health` → `{"status":"ok","redis":true}`.

---

## 11. Configuración del dominio

Apunta tu dominio (ej. `bridge.tudominio.com`) al servidor. Expón `80/443` y haz proxy inverso al
contenedor `backend:8000` (y `frontend:3000` si lo sirves público). No exponas Postgres/Redis.

---

## 12. HTTPS

Usa un proxy con TLS automático. Ejemplo con **Caddy**:

```Caddyfile
bridge.tudominio.com {
    reverse_proxy backend:8000
}
dashboard.tudominio.com {
    reverse_proxy frontend:3000
}
```

```bash
docker run -d --name caddy -p 80:80 -p 443:443 \
  -v $PWD/Caddyfile:/etc/caddy/Caddyfile \
  -v caddy_data:/data/caddy \
  --network community-bridge_default \
  caddy:2
```

Renueva certificados solo. El webhook de WhatsApp **exige HTTPS**; no uses HTTP plano en producción.

---

## 13. Webhook de WhatsApp

1. En Meta for Developers → tu app → WhatsApp → **Configuration**, pon la URL del webhook:
   `https://bridge.tudominio.com/api/v1/webhooks/whatsapp`
2. `Verify token` = el valor de `WHATSAPP_VERIFY_TOKEN` en tu `.env`.
3. Suscríbete a los campos: `messages` y `group_lifecycle_update` (este último si usas Groups API).
4. El backend valida la firma HMAC con `WHATSAPP_APP_SECRET` (`X-Hub-Signature-256`).
   En desarrollo puedes usar un túnel (Cloudflare Tunnel / ngrok) apuntando al puerto 8000;
   en producción usa tu dominio definitivo.

---

## 14. Configuración del bot de Discord

1. https://discord.com/developers/applications → New Application → Bot.
2. Copia el **Token** → `DISCORD_BOT_TOKEN` en `.env`.
3. En **Bot → Privileged Gateway Intents**, habilita **Message Content**.
4. Invita el bot con permisos mínimos:
   `View Channels`, `Send Messages`, `Read Message History` y `Manage Channels`
   (este último solo para auto-creación de canales). **No uses Administrator.**
   URL de invitación (sustituye `CLIENT_ID`):
   `https://discord.com/api/oauth2/authorize?client_id=CLIENT_ID&permissions=3145984&scope=bot`
5. En `.env`, `DISCORD_GUILD_ID` = ID del servidor (modo desarrollador → clic derecho en servidor).
6. El bot auto-descubre canales y crea mappings `PENDING`/`ACTIVE` al arrancar.

---

## 15. Actualización del sistema

```bash
git pull
docker compose up -d --build
docker compose exec backend python -c "from app.database import Base, engine; Base.metadata.create_all(engine)"
docker image prune -f   # limpia imágenes viejas
```

Si hubo cambios de esquema incompatibles, haz backup primero (ver abajo).

---

## 16. Backups

Postgres (desde el host):

```bash
docker compose exec -T postgres pg_dump -U bridge community_bridge > backup_$(date +%F).sql
```

Restaurar:

```bash
docker compose exec -T postgres psql -U bridge -d community_bridge < backup_YYYY-MM-DD.sql
```

Redis se usa como cola/caché; no requiere backup (los mensajes ya están en Postgres).

---

## 17. Logs

```bash
docker compose logs -f backend     # API + struct logs JSON
docker compose logs -f worker      # Celery (envíos, reintentos)
docker compose logs -f frontend
```

Los logs son JSON estructurado (`ts`, `level`, `logger`, `msg`, campos). No contienen secretos.
Para agregarlos a un agregador, apunta la salida stdout de los contenedores.

---

## 18. Troubleshooting

| Síntoma | Causa probable | Solución |
| --- | --- | --- |
| `403` en webhook de WhatsApp | `WHATSAPP_APP_SECRET` o `VERIFY_TOKEN` incorrectos | Revisa ambos; el challenge usa `VERIFY_TOKEN` |
| Mensajes no llegan de Discord | Intent `Message Content` desactivado o bot sin permisos | Habilita intent y revisa permisos en el servidor |
| El bot no se conecta | `DISCORD_BOT_TOKEN` inválido | Regenera token en Discord Developers |
| `401` al enviar a WhatsApp | `WHATSAPP_TOKEN` expirado | Usa token de sistema permanente, no temporal |
| Mensajes duplicados | No debería ocurrir | Verifica `bridge_generated`/dedup; revisar logs `MESSAGE_DUPLICATE_SKIPPED` |
| Mappings en `PENDING` | No-OBA y grupo WA no creado/viculado | Crea el grupo en WhatsApp y usa `manual-link` |
| `redis: False` en health | Redis caído | `docker compose restart redis` |

---

## Seguridad

- `.env` está ignorado por git. Solo `.env.example` se versiona.
- Ningún token/secreto está hardcodeado en el código.
- El webhook de WhatsApp valida HMAC; el dashboard usa `ADMIN_API_KEY`.
- Postgres y Redis no se exponen públicamente (solo red interna de compose).
