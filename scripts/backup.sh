#!/bin/sh
# Copia consistente de la base SQLite (API de backup de sqlite3, segura con la app andando).
# Docker: corre DENTRO del contenedor; desde el host:
#   docker compose exec -T app scripts/backup.sh
# cPanel: con el Python del virtualenv de la app (el python3 del sistema es 3.6):
#   PYTHON=~/virtualenv/esplitiguais/3.11/bin/python ~/esplitiguais/scripts/backup.sh
# Deja data/backups/db-YYYYmmdd-HHMMSS.sqlite3 y conserva las últimas $BACKUP_KEEP (14).
set -eu

DATA_DIR="${DATA_DIR:-$(cd "$(dirname "$0")/.." && pwd)/data}"
DB="${DATA_DIR}/db.sqlite3"
DEST="${DATA_DIR}/backups"
KEEP="${BACKUP_KEEP:-14}"
PYTHON="${PYTHON:-python}"

if [ ! -f "${DB}" ]; then
    echo "ERROR: no existe ${DB}" >&2
    exit 1
fi

mkdir -p "${DEST}"
OUT="${DEST}/db-$(date +%Y%m%d-%H%M%S).sqlite3"
TMP="${OUT}.tmp"
rm -f "${TMP}"

"${PYTHON}" - "${DB}" "${TMP}" <<'EOF'
import sqlite3
import sys

src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
result = dst.execute("PRAGMA integrity_check").fetchone()[0]
dst.close()
src.close()
if result != "ok":
    sys.exit(f"ERROR: la copia no pasó integrity_check: {result}")
EOF

mv "${TMP}" "${OUT}"
echo "Backup: ${OUT}"

# Rotación: los nombres llevan fecha ordenable, así que el orden alfabético es cronológico.
ls -1 "${DEST}"/db-*.sqlite3 | sort -r | tail -n +"$((KEEP + 1))" | while read -r old; do
    rm -f -- "${old}"
    echo "Borrado por rotación: ${old}"
done
