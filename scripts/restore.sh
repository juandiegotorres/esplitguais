#!/bin/sh
# Restaura un backup sobre data/db.sqlite3. Corre en el HOST, desde cualquier carpeta:
#   scripts/restore.sh data/backups/db-20261118-031500.sqlite3
# Para el override de desarrollo:
#   COMPOSE="docker compose -f docker-compose.yml -f docker-compose.dev.yml" scripts/restore.sh ...
#
# Pasos: frena la app, guarda la base actual como data/backups/pre-restore-*.sqlite3,
# verifica el backup (integrity_check), lo copia sobre la base con la API de sqlite3
# (como el usuario de la app, así no cambian los permisos) y vuelve a levantar la app.
set -eu

if [ "$#" -ne 1 ]; then
    echo "Uso: $0 data/backups/db-YYYYmmdd-HHMMSS.sqlite3" >&2
    exit 2
fi

cd "$(dirname "$0")/.."
NAME="$(basename "$1")"
if [ ! -f "data/backups/${NAME}" ]; then
    echo "ERROR: no existe data/backups/${NAME} (el backup tiene que estar en data/backups/)" >&2
    exit 1
fi

COMPOSE="${COMPOSE:-docker compose}"

$COMPOSE stop app
# Pase lo que pase (backup corrupto incluido), la app vuelve a levantarse.
trap '$COMPOSE start app' EXIT
# El script se pasa por stdin: sirve aunque la imagen sea anterior a scripts/restore_db.py.
$COMPOSE run --rm --no-deps -T --entrypoint python app - \
    "/app/data/backups/${NAME}" /app/data/db.sqlite3 < scripts/restore_db.py
echo "Listo. La app se vuelve a levantar."
