#!/bin/sh
# manage.py en cPanel con las variables de .env y el Python del virtualenv de la app.
# Corre en el SERVIDOR, desde cualquier carpeta:
#   ~/esplitiguais/scripts/cpanel-manage.sh crear_usuario juan
set -eu

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-${HOME}/virtualenv/$(basename "$(pwd)")/3.11/bin/python}"

set -a
. ./.env
set +a

exec "${PYTHON}" manage.py "$@"
