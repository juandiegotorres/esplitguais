# Esplitiguais

App web para repartir gastos entre amigos, estilo Splitwise. Uso privado: los usuarios los crea el administrador a mano. Diseño y decisiones en [PLAN.md](PLAN.md).

Stack: Django 5.2 + SQLite + HTMX/Alpine.js. Dos formas de desplegarla: Docker (gunicorn + whitenoise, expuesta con Cloudflare Tunnel) o cPanel/Hostinger (LiteSpeed, detrás del proxy de Cloudflare). Producción hoy: **cPanel**.

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

No hay registro público ni email. Todo lo hace el administrador desde el servidor (con Docker `docker compose exec app python manage.py ...`; en cPanel `~/esplitiguais/scripts/cpanel-manage.sh ...`; en local sin Docker, `DEBUG=1 .venv/bin/python manage.py ...`):

```bash
docker compose exec app python manage.py crear_usuario juan       # pide la contraseña dos veces
docker compose exec app python manage.py resetear_password juan   # contraseña nueva; también lo desbloquea
docker compose exec app python manage.py createsuperuser          # cuenta con acceso a /admin
```

- Las contraseñas se validan (mínimo 8 caracteres, no comunes, no solo números, no parecidas al usuario) y se guardan hasheadas. Nunca insertarlas a mano en la base.
- `crear_usuario` rechaza nombres que ya existen aunque cambien mayúsculas (`Juan` vs `juan`). El login sí distingue mayúsculas.
- Para scripts: `--password-stdin` lee la contraseña de la primera línea de la entrada estándar, p. ej. `printf '%s\n' "$CLAVE" | docker compose exec -T app python manage.py crear_usuario juan --password-stdin`.
- Cada usuario cambia su propia contraseña y carga su **nombre** (el que ven los demás; si está vacío se usa el usuario) y su **alias** (CBU/CVU) desde **Mi cuenta**, tocando su inicial (avatar) arriba a la derecha. El alias se muestra con un botón "Copiar" solo a quien le tiene que pagar: en **Mis deudas** de la pantalla de saldos y al registrar un pago propio. También se editan desde `/admin`, en el usuario.
- En saldos, **Mis deudas** muestra lo que debés pagar y lo que te deben; **Deudas grupales**, lo que se deben los demás entre sí (solo informativo). Un pago solo lo pueden registrar quien lo hizo o quien lo recibió, y solo ellos (o quien lo cargó) lo pueden borrar.
- En **Gastos**, la pestaña **Estadísticas** muestra el total gastado en el grupo, cuánto pagó cada uno (y cuánto le tocaba según los repartos) y el gasto por categoría. Los pagos registrados entre miembros no cuentan como gasto.
- Desde `/admin` (superusuario) también se pueden crear, desactivar o editar usuarios.

### Bloqueo por intentos fallidos

`django-axes` bloquea **la combinación usuario + IP** tras 5 intentos fallidos, durante 1 hora. Un login correcto pone el contador en cero. Que un amigo se equivoque no bloquea a los demás ni a ese mismo usuario desde otra conexión.

La IP real sale del header `CF-Connecting-IP` que agrega Cloudflare, pero solo se le cree si la conexión viene de un borde de Cloudflare (rangos de <https://www.cloudflare.com/ips/> en `accounts/ip.py`) o de una red privada (el contenedor `cloudflared` en Docker). Si no, se usa `REMOTE_ADDR`: en cPanel cualquiera puede pegarle directo a la IP del servidor e inventarse el header para esquivar el bloqueo. Si Cloudflare publica rangos nuevos, actualizar la lista. (En Hostinger, LiteSpeed ya pone la IP real del cliente en `REMOTE_ADDR` cuando el pedido viene por Cloudflare.)

Desbloquear antes de la hora: `resetear_password` (desbloquea al usuario) o `manage.py axes_reset_username juan` (con el prefijo de Docker o cPanel de arriba).

## Notificaciones push

Avisan en el celular (o la compu) cuando alguien **carga o edita un gasto** en el que participás (pagaste o tenés parte; al editar, también si te sacaron) o **registra un pago** con vos. Quien hace el cambio no recibe aviso. Es Web Push estándar con claves VAPID (`pywebpush`): no hace falta servidor de correo ni cuentas externas.

Activarlas en el servidor, una sola vez (con el prefijo de Docker o cPanel de [Usuarios](#usuarios)):

```bash
python manage.py generar_vapid     # imprime WEBPUSH_VAPID_PUBLIC_KEY y WEBPUSH_VAPID_PRIVATE_KEY
```

Pegar las dos líneas en `.env` (la privada es secreta). Si las claves cambian, cada dispositivo tiene que volver a activarlas. Sin claves la función queda apagada y no aparece en la app.

Cada persona las activa en cada dispositivo desde **Mi cuenta → Notificaciones** (también en el menú del avatar):

- **iPhone/iPad**: solo con la app **instalada** en la pantalla de inicio (iOS 16.4 o más nuevo) y abierta desde ahí. En Safari común el botón no aparece.
- **Android y compu**: funciona también en el navegador.

El envío ocurre al guardar, en paralelo a todos los dispositivos, con 5 s de tope por envío: si el servicio de push de Apple o Google falla, el gasto se guarda igual y el error queda en el log. Los dispositivos que ya no existen (app desinstalada, permiso revocado) se borran solos. Las suscripciones se ven en `/admin`.

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

## Despliegue en cPanel (Hostinger)

El hosting compartido no tiene Docker ni root. La app corre así:

- **Código**: clon de GitHub (`main`) en `~/esplitiguais`; **base** en `~/esplitiguais/data/` (fuera del docroot y del repo); **virtualenv** con Python 3.11 en `~/virtualenv/esplitiguais/3.11` (el `python3` del sistema es 3.6).
- **Docroot** `~/gastos.practicomercio.com.ar`: `static/` (lo genera `collectstatic`; LiteSpeed lo sirve directo) y `cgi-bin/app.cgi`. El `.htaccess` manda el resto de las URLs a `app.cgi`, que corre Django con `cpanel_cgi.py`.
- **CGI**: LiteSpeed de Hostinger no trae soporte WSGI para Python (falta el paquete `alt-python311-wsgi-lsapi`, que solo instala el hosting). Cada request arranca Django de cero (~0,4 s en el servidor). Los estáticos no pasan por Python.
- **HTTPS**: Cloudflare (registro DNS *proxied*) → LiteSpeed con certificado AutoSSL de cPanel.

### 1. Preparar (una sola vez)

1. cPanel → **Domains** → crear `gastos.practicomercio.com.ar` con docroot `gastos.practicomercio.com.ar` (en el home, **no** dentro de `public_html`).
2. Por SSH en el servidor:

   ```bash
   /opt/alt/python311/bin/python3 -m venv ~/virtualenv/esplitiguais/3.11
   git clone https://github.com/juandiegotorres/esplitguais.git ~/esplitiguais && cd ~/esplitiguais
   (umask 077 && nano .env)   # SECRET_KEY nueva, DEBUG=0, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, SECURE_HSTS_SECONDS=0 (ver .env.example)
   scripts/cpanel-update.sh   # agrega STATIC_ROOT a .env si falta
   ```

3. Con el alias `cpanel` en `~/.ssh/config` de tu máquina, los siguientes deploys se hacen desde ahí (ver "Actualizar").
4. IP del dominio: `uapi DomainInfo single_domain_data domain=gastos.practicomercio.com.ar | grep ' ip:'` (no es la del hostname del servidor).
5. Cloudflare → zona `practicomercio.com.ar` → DNS: registro `A` `gastos` → esa IP, **Proxied**. Si existía un CNAME del túnel, reemplazarlo.
6. Certificado del origen: cPanel → **SSL/TLS Status** → *Run AutoSSL* (o `uapi SSL start_autossl_check`). Con el certificado emitido, Cloudflare → SSL/TLS → modo **Full (strict)** y **Always Use HTTPS**.
7. HSTS: dejar `SECURE_HSTS_SECONDS=0`. LiteSpeed de Hostinger ya envía `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload`, y Django lo duplicaría (`check --deploy` igual avisa W004).
8. Usuarios: `~/esplitiguais/scripts/cpanel-manage.sh createsuperuser` y `... crear_usuario juan`.

### Actualizar

Commitear y pushear a `main`, y después desde tu máquina:

```bash
scripts/deploy-cpanel.sh
```

Se niega a correr si hay cambios sin commitear o si `HEAD` no es `origin/main`, así lo desplegado siempre es un commit publicado. En el servidor hace `git pull --ff-only` (falla si alguien editó archivos ahí: nunca editar código en el servidor) y `scripts/cpanel-update.sh`: backup, dependencias, migraciones, `collectstatic` y el bloque `# BEGIN esplitiguais` del `.htaccess` (el resto del archivo es de cPanel y no se toca). Para re-aplicar sin código nuevo, en el servidor: `~/esplitiguais/scripts/cpanel-update.sh`.

### Pasar a Passenger (más rápido)

Si Hostinger instala `alt-python311-wsgi-lsapi`, Django queda cargado en memoria entre requests en vez de arrancar en cada uno:

```bash
CPANEL_SERVER=passenger scripts/deploy-cpanel.sh
```

Usa `passenger_wsgi.py` y reemplaza las reglas CGI por directivas `Passenger*` en el `.htaccess`. Sin el paquete, LiteSpeed responde 503 (`stderr.log` en `~/esplitiguais` dice `lswsgi: No such file or directory`); para volver: `scripts/deploy-cpanel.sh`. Desde entonces hay que usar siempre `CPANEL_SERVER=passenger`, o el deploy vuelve a CGI.

## Backups

`scripts/backup.sh` hace una copia consistente con la API de backup de SQLite (sirve con la app funcionando), la verifica con `integrity_check` y la deja en `data/backups/db-YYYYmmdd-HHMMSS.sqlite3` (hora UTC). Conserva las últimas 14 (`BACKUP_KEEP` para cambiarlo). Con Docker corre dentro del contenedor; en cPanel, con el Python del virtualenv:

```bash
docker compose exec -T app scripts/backup.sh                                                       # Docker
PYTHON=~/virtualenv/esplitiguais/3.11/bin/python ~/esplitiguais/scripts/backup.sh               # cPanel
```

### Cron diario

`crontab -e` en el servidor (en el VPS, con un usuario que pueda usar Docker):

```cron
# Docker
30 6 * * * cd /home/USUARIO/esplitiguais && docker compose exec -T app scripts/backup.sh >> data/backups/backup.log 2>&1
# cPanel (ya instalado en el servidor)
30 6 * * * PYTHON=$HOME/virtualenv/esplitiguais/3.11/bin/python $HOME/esplitiguais/scripts/backup.sh >> $HOME/esplitiguais/data/backups/backup.log 2>&1
```

06:30 UTC = 03:30 en Argentina. Revisar `data/backups/backup.log` de vez en cuando.

### Bajar copias a otra máquina

Un backup que vive en el mismo disco no sirve si se rompe el VPS. Desde tu computadora (o desde otro servidor, con su propio cron):

```bash
rsync -av usuario@vps:esplitiguais/data/backups/ ~/backups/esplitiguais/    # cPanel: cpanel:esplitiguais/data/backups/
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

Para restaurar una copia bajada a otra máquina, primero subirla a `data/backups/` del servidor (`scp` o `rsync`) y después correr el script.

En cPanel: `~/esplitiguais/scripts/restore-cpanel.sh data/backups/db-20261118-063000.sqlite3`. Hace los pasos 2 a 4 con `scripts/restore_db.py`, el mismo código que usa `restore.sh`. No hay nada que frenar: con CGI cada request abre la base de nuevo.

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
| `STATIC_ROOT` | Solo cPanel: carpeta `static` del docroot (la agrega `deploy-cpanel.sh`). Por defecto `staticfiles/` |
| `CLOUDFLARE_TUNNEL_TOKEN` | Solo Docker: token del túnel para `cloudflared` |
| `WEBPUSH_VAPID_PUBLIC_KEY` / `WEBPUSH_VAPID_PRIVATE_KEY` | Claves de las notificaciones push (`manage.py generar_vapid`). Vacías = apagadas |
| `WEBPUSH_VAPID_SUBJECT` | Opcional: contacto para Apple/Google (`https://...` o `mailto:...`). Por defecto, `https://` + el primer `ALLOWED_HOSTS` |
