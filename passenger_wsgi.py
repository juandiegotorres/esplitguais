"""Entrada WSGI para cPanel (Application Manager / Passenger).

Application Manager arranca la app con el python3 del sistema (3.6 en Hostinger), así
que primero se relanza con el Python 3.11 del virtualenv de la app. Después carga
`.env` de la carpeta del proyecto (mismo formato que usa Docker: KEY=VALUE, sin
comillas) sin pisar variables ya definidas, y expone `application`.

Este archivo tiene que seguir siendo compatible con Python 3.6 hasta el `execl`.
"""

import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
VENV_PYTHON = Path.home() / "virtualenv" / APP_DIR.name / "3.11" / "bin" / "python"

if sys.executable != str(VENV_PYTHON):
    os.execl(str(VENV_PYTHON), str(VENV_PYTHON), *sys.argv)

ENV_FILE = APP_DIR / ".env"

if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

from config.wsgi import application  # noqa: E402
