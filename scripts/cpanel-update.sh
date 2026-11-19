#!/bin/sh
# Deja andando en cPanel el código que ya está en la carpeta (después de `git pull`).
# Corre en el SERVIDOR; normalmente lo llama scripts/deploy-cpanel.sh:
#   ~/esplitiguais/scripts/cpanel-update.sh
# Variables (con sus valores por defecto):
#   CPANEL_DOCROOT=gastos.practicomercio.com.ar docroot del dominio en el home
#   CPANEL_SERVER=cgi                           cgi | passenger (solo si el hosting instaló
#                                               alt-python311-wsgi-lsapi; ver README)
#
# Pasos: backup (si ya hay base), dependencias, migraciones, collectstatic al docroot y
# el bloque propio del .htaccess. No toca .env (salvo agregar STATIC_ROOT si falta) ni data/.
set -eu

cd "$(dirname "$0")/.."
APP_DIR="$(pwd)"
APP="$(basename "${APP_DIR}")"
DOCROOT_DIR="${HOME}/${CPANEL_DOCROOT:-gastos.practicomercio.com.ar}"
SERVER="${CPANEL_SERVER:-cgi}"
PYTHON="${HOME}/virtualenv/${APP}/3.11/bin/python"
case "${SERVER}" in
    cgi | passenger) ;;
    *) echo "ERROR: CPANEL_SERVER debe ser cgi o passenger" >&2; exit 2 ;;
esac

mkdir -p data tmp
chmod 700 data
if [ -f data/db.sqlite3 ]; then
    PYTHON="${PYTHON}" scripts/backup.sh
fi
"${PYTHON}" -m pip install --quiet --disable-pip-version-check -r requirements.txt

# Estáticos al docroot: los sirve LiteSpeed directo (sin arrancar Python).
STATIC_DIR="${DOCROOT_DIR}/static"
grep -q '^STATIC_ROOT=' .env || echo "STATIC_ROOT=${STATIC_DIR}" >> .env

scripts/cpanel-manage.sh migrate --noinput
scripts/cpanel-manage.sh collectstatic --noinput --verbosity 0
chmod -R a+rX "${STATIC_DIR}"

# .htaccess: reemplaza solo el bloque propio y conserva lo que genera cPanel.
if [ "${SERVER}" = passenger ]; then
    # Requiere alt-python311-wsgi-lsapi en el servidor (sin él LiteSpeed responde 503).
    rm -f "${DOCROOT_DIR}/cgi-bin/app.cgi"
    BLOCK="Options -Indexes
PassengerAppRoot \"${APP_DIR}\"
PassengerBaseURI \"/\"
PassengerPython \"${PYTHON}\"
PassengerAppType wsgi
PassengerStartupFile passenger_wsgi.py"
else
    mkdir -p "${DOCROOT_DIR}/cgi-bin"
    printf '#!%s\nimport runpy\nrunpy.run_path("%s", run_name="__main__")\n' \
        "${PYTHON}" "${APP_DIR}/cpanel_cgi.py" > "${DOCROOT_DIR}/cgi-bin/app.cgi"
    chmod 755 "${DOCROOT_DIR}/cgi-bin/app.cgi"
    # Todo lo que no es estático va a Django (cpanel_cgi.py toma la ruta de REQUEST_URI).
    BLOCK='Options -Indexes
RewriteEngine On
RewriteCond %{REQUEST_URI} !^/(cgi-bin|static|\.well-known)/
RewriteRule ^ cgi-bin/app.cgi [L]'
fi
HTACCESS="${DOCROOT_DIR}/.htaccess"
touch "${HTACCESS}"
{
    echo "# BEGIN esplitiguais (generado por scripts/cpanel-update.sh, modo ${SERVER})"
    printf '%s\n' "${BLOCK}"
    echo "# END esplitiguais"
    awk '/^# BEGIN esplitiguais/{skip=1} !skip{print} /^# END esplitiguais/{skip=0}' "${HTACCESS}"
} > "${HTACCESS}.new"
mv "${HTACCESS}.new" "${HTACCESS}"
chmod 644 "${HTACCESS}"

# Passenger reinicia la app al ver este archivo; con CGI no hace falta.
touch tmp/restart.txt
echo "Deploy OK ($(git rev-parse --short HEAD 2>/dev/null || echo sin git), modo ${SERVER})"
