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
$COMPOSE run --rm --no-deps -T --entrypoint python app - "/app/data/backups/${NAME}" <<'EOF'
import sqlite3
import sys
import time
from pathlib import Path

backup = Path(sys.argv[1])
db = Path("/app/data/db.sqlite3")

src = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
result = src.execute("PRAGMA integrity_check").fetchone()[0]
if result != "ok":
    sys.exit(f"ERROR: {backup.name} no pasó integrity_check: {result}")

if db.exists():
    safety = db.parent / "backups" / f"pre-restore-{time.strftime('%Y%m%d-%H%M%S')}.sqlite3"
    current = sqlite3.connect(db)
    with sqlite3.connect(safety) as out:
        current.backup(out)
    current.close()
    print(f"Base anterior guardada en data/backups/{safety.name}")

dst = sqlite3.connect(db)
with dst:
    src.backup(dst)
dst.close()
src.close()
print(f"Restaurado {backup.name} sobre data/db.sqlite3")
EOF
echo "Listo. La app se vuelve a levantar."
