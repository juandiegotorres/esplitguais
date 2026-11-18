#!/bin/sh
set -eu

if [ ! -w "${DATA_DIR}" ]; then
    echo "ERROR: ${DATA_DIR} no es escribible por el usuario $(id -u):$(id -g)." >&2
    echo "En el host, desde la carpeta del proyecto: sudo chown -R $(id -u):$(id -g) data" >&2
    exit 1
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput --verbosity 0

exec "$@"
