"""Entrada CGI para cPanel cuando LiteSpeed no tiene soporte WSGI (falta el paquete
`alt-python311-wsgi-lsapi`, que solo puede instalar el hosting).

Cada request arranca un proceso Python nuevo (~0,5 s). Si el hosting instala el
paquete, conviene pasar a Passenger (ver README, "Despliegue en cPanel").

Lo ejecuta `cgi-bin/app.cgi` del docroot (generado por scripts/deploy-cpanel.sh). El
`.htaccess` reescribe las URLs hacia ese script; la ruta se toma de REQUEST_URI (la URL
original) y SCRIPT_NAME se vacía para que Django no anteponga `/cgi-bin/app.cgi` a los links.
"""

import os
import sys
from pathlib import Path
from urllib.parse import unquote_to_bytes
from wsgiref.handlers import CGIHandler

sys.path.insert(0, str(Path(__file__).resolve().parent))

# wsgiref vuelve a codificar el entorno con el encoding del sistema de archivos al leerlo.
path = os.environ.get("REQUEST_URI", "/").split("?", 1)[0]
os.environ["PATH_INFO"] = unquote_to_bytes(path).decode(sys.getfilesystemencoding(), "surrogateescape")
os.environ["SCRIPT_NAME"] = ""

from passenger_wsgi import application  # noqa: E402  (carga .env)

CGIHandler().run(application)
