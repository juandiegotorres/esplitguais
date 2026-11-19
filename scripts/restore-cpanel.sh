#!/bin/sh
# Restaura un backup sobre data/db.sqlite3 en cPanel. Corre en el SERVIDOR:
#   ~/esplitiguais/scripts/restore-cpanel.sh data/backups/db-20261118-063000.sqlite3
#
# Usa scripts/restore_db.py: verifica el backup, guarda la base actual como
# data/backups/pre-restore-*.sqlite3 y copia el backup encima con la API de sqlite3.
# Con CGI no hay procesos que frenar (cada request abre la base de nuevo); con
# Passenger, tmp/restart.txt hace que la app reabra la base.
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

PYTHON="${PYTHON:-${HOME}/virtualenv/$(basename "$(pwd)")/3.11/bin/python}"
"${PYTHON}" scripts/restore_db.py "data/backups/${NAME}" data/db.sqlite3
mkdir -p tmp
touch tmp/restart.txt
echo "Listo."
