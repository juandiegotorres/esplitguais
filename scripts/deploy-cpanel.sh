#!/bin/sh
# Despliega en cPanel lo que está en origin/main. Corre en TU MÁQUINA, desde cualquier carpeta:
#   scripts/deploy-cpanel.sh
# Variables (con sus valores por defecto):
#   CPANEL_HOST=cpanel                          alias de ~/.ssh/config
#   CPANEL_APP_ROOT=esplitiguais                clon del repo en el home del servidor
#   CPANEL_DOCROOT=gastos.practicomercio.com.ar docroot del dominio en el home del servidor
#   CPANEL_SERVER=cgi                           cgi | passenger (ver README)
#
# Exige árbol limpio y HEAD local igual a origin/main (lo desplegado siempre es un commit
# publicado). En el servidor: `git pull --ff-only` y scripts/cpanel-update.sh.
set -eu

HOST="${CPANEL_HOST:-cpanel}"
APP="${CPANEL_APP_ROOT:-esplitiguais}"
DOCROOT="${CPANEL_DOCROOT:-gastos.practicomercio.com.ar}"
SERVER="${CPANEL_SERVER:-cgi}"

cd "$(dirname "$0")/.."

if [ -n "$(git status --porcelain)" ]; then
    echo "ERROR: hay cambios sin commitear; commitear y pushear antes de desplegar." >&2
    exit 1
fi
git fetch --quiet origin main
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
    echo "ERROR: HEAD no coincide con origin/main; pushear (o actualizar main) antes de desplegar." >&2
    exit 1
fi

ssh "${HOST}" "cd ~/'${APP}' && git pull --ff-only --quiet origin main \
    && CPANEL_DOCROOT='${DOCROOT}' CPANEL_SERVER='${SERVER}' scripts/cpanel-update.sh"
