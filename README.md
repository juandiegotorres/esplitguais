# Esplitiguais

App web para repartir gastos entre amigos, estilo Splitwise. Uso privado: los usuarios los crea el administrador a mano. Diseño y decisiones en [PLAN.md](PLAN.md).

Stack: Django 5.2 + SQLite + HTMX/Alpine.js, servida con gunicorn + whitenoise en Docker y expuesta con Cloudflare Tunnel.

## Desarrollo local (sin Docker)

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p data
DEBUG=1 .venv/bin/python manage.py migrate
DEBUG=1 .venv/bin/python manage.py crear_usuario juan
DEBUG=1 .venv/bin/python manage.py runserver
```

Abrir <http://127.0.0.1:8000/>. **Todo comando local lleva `DEBUG=1`**: sin eso `config/settings.py` exige `SECRET_KEY` y cookies seguras (HTTPS).

Tests:

```bash
DEBUG=1 .venv/bin/python manage.py test
```

## Desarrollo local con Docker

`docker-compose.dev.yml` publica la app en `127.0.0.1:8000` y deja `cloudflared` apagado (perfil `tunnel`).

```bash
cp .env.example .env            # completar SECRET_KEY; el resto puede quedar así
mkdir -p data                   # ver "Permisos de ./data"
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app python manage.py crear_usuario juan
```

Abrir <http://127.0.0.1:8000/>. Para no repetir los `-f`: `export COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml`.

## Usuarios

No hay registro público ni email. Todo lo hace el administrador desde el servidor (en producción `docker compose exec app ...`; en local sin Docker, `DEBUG=1 .venv/bin/python manage.py ...`):

```bash
docker compose exec app python manage.py crear_usuario juan       # pide la contraseña dos veces
docker compose exec app python manage.py resetear_password juan   # contraseña nueva; también lo desbloquea
docker compose exec app python manage.py createsuperuser          # cuenta con acceso a /admin
```

- Las contraseñas se validan (mínimo 8 caracteres, no comunes, no solo números, no parecidas al usuario) y se guardan hasheadas. Nunca insertarlas a mano en la base.
- `crear_usuario` rechaza nombres que ya existen aunque cambien mayúsculas (`Juan` vs `juan`). El login sí distingue mayúsculas.
- Para scripts: `--password-stdin` lee la contraseña de la primera línea de la entrada estándar, p. ej. `printf '%s\n' "$CLAVE" | docker compose exec -T app python manage.py crear_usuario juan --password-stdin`.
- Cada usuario cambia su propia contraseña desde la app tocando su nombre arriba a la derecha.
- Desde `/admin` (superusuario) también se pueden crear, desactivar o editar usuarios.

### Bloqueo por intentos fallidos

`django-axes` bloquea **la combinación usuario + IP** tras 5 intentos fallidos, durante 1 hora. Un login correcto pone el contador en cero. Que un amigo se equivoque no bloquea a los demás ni a ese mismo usuario desde otra conexión.

La IP real sale del header `CF-Connecting-IP` que agrega Cloudflare (sin él, de `REMOTE_ADDR`). Es confiable porque la app no publica puertos: solo le llega tráfico a través de `cloudflared`.

Desbloquear antes de la hora: `resetear_password` (desbloquea al usuario) o `docker compose exec app python manage.py axes_reset_username juan`.

## Despliegue en el VPS (Cloudflare Tunnel)

Con el túnel, el VPS no abre ningún puerto web: `cloudflared` sale hacia Cloudflare y Cloudflare maneja HTTPS y certificados.

### 1. Crear el túnel

1. Cloudflare Zero Trust → Networks → Tunnels → **Create a tunnel** → tipo `cloudflared`, nombre `gastos`.
2. Copiar el **token** que aparece en el comando de instalación (lo que va después de `--token`). No instalar nada en el VPS: lo corre el contenedor.
3. **Public hostname**: subdominio `gastos`, dominio `practicomercio.com.ar`, servicio `HTTP` → `app:8000`.
4. En la zona `practicomercio.com.ar` → SSL/TLS → Edge Certificates: activar **Always Use HTTPS**.

### 2. Preparar el servidor

Requisitos: Docker Engine con el plugin Compose.

```bash
git clone <repo> esplitiguais && cd esplitiguais
cp .env.example .env
nano .env       # SECRET_KEY nueva, CLOUDFLARE_TUNNEL_TOKEN, dominio en ALLOWED_HOSTS y CSRF_TRUSTED_ORIGINS
chmod 600 .env
mkdir -p data && sudo chown 1000:1000 data
docker compose up -d --build
docker compose logs -f          # esperar "Registered tunnel connection" en cloudflared
docker compose exec app python manage.py createsuperuser
docker compose exec app python manage.py crear_usuario juan
```

Abrir `https://gastos.practicomercio.com.ar` en el celular: tiene que cargar sin advertencias de certificado.

Actualizar a una versión nueva: `git pull && docker compose up -d --build` (las migraciones corren solas al arrancar). Conviene hacer un backup antes.

### Permisos de `./data`

La app corre como usuario sin privilegios **uid 1000 / gid 1000** y necesita escribir en `./data` (base SQLite y backups). Si la carpeta la creó Docker o root, el contenedor no arranca y el log lo dice:

```bash
sudo chown -R 1000:1000 data
```

Para usar otro uid (por ejemplo el de tu usuario en el VPS): `docker compose build --build-arg APP_UID=$(id -u) --build-arg APP_GID=$(id -g)` y `chown` acorde.

### 3. Firewall (`ufw`)

Solo SSH. La app no publica puertos en `docker-compose.yml` a propósito: los puertos que publica Docker se saltean `ufw`.

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp           # o "sudo ufw limit 22/tcp" para frenar fuerza bruta
sudo ufw enable
sudo ufw status verbose
```

Verificar que no quedó nada expuesto: `docker compose ps` no debe mostrar `0.0.0.0:...` en ningún servicio, y `sudo ss -tlnp` solo debe listar el 22 (y servicios propios del VPS que ya existían).

## Backups

`scripts/backup.sh` corre dentro del contenedor y hace una copia consistente con la API de backup de SQLite (sirve con la app funcionando), la verifica con `integrity_check` y la deja en `data/backups/db-YYYYmmdd-HHMMSS.sqlite3` (hora UTC). Conserva las últimas 14 (`BACKUP_KEEP` para cambiarlo).

```bash
docker compose exec -T app scripts/backup.sh
```

### Cron diario

`crontab -e` en el VPS (con un usuario que pueda usar Docker):

```cron
30 6 * * * cd /home/USUARIO/esplitiguais && docker compose exec -T app scripts/backup.sh >> data/backups/backup.log 2>&1
```

06:30 UTC = 03:30 en Argentina. Revisar `data/backups/backup.log` de vez en cuando.

### Bajar copias a otra máquina

Un backup que vive en el mismo disco no sirve si se rompe el VPS. Desde tu computadora (o desde otro servidor, con su propio cron):

```bash
rsync -av usuario@vps:esplitiguais/data/backups/ ~/backups/esplitiguais/
```

Sin `--delete`: localmente se acumulan todas las copias aunque el VPS rote las 14 últimas.

### Restaurar

```bash
ls data/backups/
scripts/restore.sh data/backups/db-20261118-063000.sqlite3
```

`scripts/restore.sh` corre en el host y:

1. Frena la app (`docker compose stop app`).
2. Verifica el backup con `integrity_check`; si falla, no toca nada.
3. Guarda la base actual como `data/backups/pre-restore-*.sqlite3` (por si te equivocaste de archivo).
4. Copia el backup sobre `data/db.sqlite3` con el usuario de la app (no cambian los permisos).
5. Vuelve a levantar la app (también si algo falló).

Con el override de desarrollo: `COMPOSE="docker compose -f docker-compose.yml -f docker-compose.dev.yml" scripts/restore.sh ...`.

Para restaurar una copia bajada a otra máquina, primero subirla a `data/backups/` del VPS (`scp` o `rsync`) y después correr el script.

Probarlo de vez en cuando con una copia del proyecto (ver abajo) es la única forma de saber que los backups sirven.

#### Prueba de restauración

En una copia del repo, para no tocar la base real:

```bash
rsync -a --exclude .venv --exclude data ./ /tmp/esplitiguais-prueba/ && cd /tmp/esplitiguais-prueba
cp .env.example .env && mkdir -p data
export COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml COMPOSE_PROJECT_NAME=esplitiguais-prueba
docker compose up -d --build
docker compose exec -T app python manage.py crear_usuario prueba    # dato de ejemplo
docker compose exec -T app scripts/backup.sh
docker compose exec -T app python manage.py shell -c "from django.contrib.auth.models import User; User.objects.filter(username='prueba').delete()"
scripts/restore.sh data/backups/db-*.sqlite3                          # usar el nombre que imprimió backup.sh
docker compose exec -T app python manage.py shell -c "from django.contrib.auth.models import User; print(User.objects.filter(username='prueba').exists())"   # True
docker compose down
```

## Variables de entorno (`.env`)

| Variable | Uso |
|---|---|
| `SECRET_KEY` | Obligatoria con `DEBUG=0`. Larga y aleatoria |
| `DEBUG` | `0` en producción |
| `ALLOWED_HOSTS` | Dominio público, separado por comas |
| `CSRF_TRUSTED_ORIGINS` | Igual pero con `https://` |
| `SECURE_HSTS_SECONDS` | HSTS (`31536000` = un año); `0` lo desactiva |
| `SECURE_SSL_REDIRECT` | Opcional; Cloudflare ya redirige a HTTPS |
| `CLOUDFLARE_TUNNEL_TOKEN` | Token del túnel para `cloudflared` |
