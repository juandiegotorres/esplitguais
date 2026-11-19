"""Restaura un backup SQLite sobre la base. Lo usan restore.sh (Docker) y restore-cpanel.sh.

Uso: python scripts/restore_db.py BACKUP DB

Verifica el backup (integrity_check), guarda la base actual como
backups/pre-restore-*.sqlite3 y copia el backup encima con la API de sqlite3
(escribe sobre el archivo existente, así no cambian dueño ni permisos).
"""

import sqlite3
import sys
import time
from pathlib import Path

backup = Path(sys.argv[1])
db = Path(sys.argv[2])

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
