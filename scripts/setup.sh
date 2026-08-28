#!/usr/bin/env bash
#
# Community Bridge - Instalación limpia en servidor nuevo
#
# Uso:
#   ./scripts/setup.sh                 # usa el directorio actual (ya clonado)
#   ./scripts/setup.sh --clone=URL     # clona el repo y luego despliega
#   ./scripts/setup.sh --no-build     # levanta sin reconstruir imagenes
#
# El script NUNCA contiene secretos. Copia .env.example -> .env y te pide
# que edites .env con tus credenciales antes de levantar los servicios.
#
set -euo pipefail

REPO_URL=""
CLONE=false
BUILD_ARGS=""

for arg in "$@"; do
  case "$arg" in
    --clone=*) CLONE=true; REPO_URL="${arg#*=}" ;;
    --no-build) BUILD_ARGS="--no-build" ;;
    -h|--help) echo "Uso: $0 [--clone=URL] [--no-build]"; exit 0 ;;
    *) echo "Argumento desconocido: $arg"; exit 1 ;;
  esac
done

echo "==> Verificando prerrequisitos"
command -v docker >/dev/null 2>&1 || { echo "ERROR: docker no encontrado"; exit 1; }
if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: docker compose v2 no encontrado (usa 'docker compose', no 'docker-compose')"; exit 1
fi

if [ "$CLONE" = true ]; then
  if [ -z "$REPO_URL" ]; then echo "ERROR: --clone requiere una URL"; exit 1; fi
  if [ -d community-bridge ]; then
    echo "==> community-bridge ya existe, omitiendo clone"
  else
    echo "==> Clonando $REPO_URL"
    git clone "$REPO_URL" community-bridge
  fi
  cd community-bridge
fi

echo "==> Preparando .env"
if [ -f .env ]; then
  echo "    .env ya existe, no se sobreescribe."
else
  if [ ! -f .env.example ]; then echo "ERROR: .env.example no encontrado"; exit 1; fi
  cp .env.example .env
  echo "    Se creo .env desde .env.example."
  echo "    EDITA .env con tus secretos (ADMIN_API_KEY, DISCORD_BOT_TOKEN,"
  echo "    DISCORD_GUILD_ID, WHATSAPP_TOKEN, WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN)."
  if [ -t 1 ] && command -v "${EDITOR:-nano}" >/dev/null 2>&1; then
    read -r -p "    ¿Abrir .env en el editor ahora? [y/N] " ans
    if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then "${EDITOR:-nano}" .env; fi
  fi
  read -r -p "    Pulsa ENTER tras editar .env para continuar (Ctrl-C para abortar)..."
fi

echo "==> Levantando servicios con Docker Compose"
docker compose up -d --build $BUILD_ARGS

echo "==> Esperando health check del backend (http://localhost:8000/api/v1/health)"
HEALTHY=false
for i in $(seq 1 30); do
  if curl -fsS http://localhost:8000/api/v1/health >/dev/null 2>&1; then
    HEALTHY=true
    echo "    Backend healthy."
    break
  fi
  sleep 3
done
if [ "$HEALTHY" = false ]; then
  echo "    ADVERTENCIA: el backend no responde aun. Revisa: docker compose logs -f backend"
fi

echo "==> Estado de los servicios"
docker compose ps

echo ""
echo "Despliegue iniciado."
echo "  Dashboard : http://localhost:3000"
echo "  API docs  : http://localhost:8000/docs"
echo "  Health    : http://localhost:8000/api/v1/health"
echo ""
echo "Para ver logs: docker compose logs -f backend worker"
echo "Para detener:  docker compose down"
