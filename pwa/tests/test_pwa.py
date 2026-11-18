import json
import re
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.test import TestCase
from django.urls import reverse


def static_file_for(url: str):
    prefix = static("")
    assert url.startswith(prefix), url
    return finders.find(url[len(prefix):])


class ManifestTests(TestCase):
    def test_manifest_is_valid_and_installable(self):
        response = self.client.get(reverse("pwa:manifest"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        data = json.loads(response.content)
        self.assertEqual(data["name"], "Esplitiguais")
        self.assertEqual(data["start_url"], "/")
        self.assertEqual(data["display"], "standalone")
        sizes = {(icon["sizes"], icon.get("purpose", "any")) for icon in data["icons"]}
        self.assertTrue({("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes)
        for icon in data["icons"]:
            self.assertIsNotNone(static_file_for(icon["src"]), icon["src"])


class ServiceWorkerTests(TestCase):
    def test_served_from_root_with_full_scope_and_no_long_cache(self):
        response = self.client.get("/sw.js")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("application/javascript"))
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertEqual(response["Cache-Control"], "no-cache")

    def test_every_precached_asset_exists(self):
        # Si un archivo precacheado no existe, cache.addAll falla y el SW nunca se instala.
        body = self.client.get("/sw.js").content.decode()
        block = re.search(r"PRECACHE_STATIC = \[(.*?)\];", body, re.S).group(1)
        urls = re.findall(r'"([^"]+)"', block)

        self.assertIn(static("css/app.css"), urls)
        for url in urls:
            self.assertIsNotNone(static_file_for(url), url)
        self.assertNotIn("__SW_VERSION__", body)

    def test_cache_version_changes_when_a_hashed_asset_changes(self):
        # En producción un deploy cambia los hashes: el SW nuevo debe usar otra
        # caché y borrar la vieja en activate.
        def sw_version():
            body = self.client.get("/sw.js").content.decode()
            return re.search(r'const VERSION = "([0-9a-f]+)";', body).group(1)

        def hashed(digest):
            return lambda name: re.sub(r"\.(\w+)$", rf".{digest}.\1", name)

        with mock.patch("config.storage.StaticStorage.stored_name", side_effect=hashed("aaaaaaaaaaaa")):
            before = sw_version()
            self.assertEqual(before, sw_version())
        with mock.patch("config.storage.StaticStorage.stored_name", side_effect=hashed("bbbbbbbbbbbb")):
            after = sw_version()

        self.assertNotEqual(before, after)


class PublicPagesTests(TestCase):
    def test_offline_and_install_do_not_require_login(self):
        for name in ("pwa:offline", "pwa:install"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)

    def test_offline_page_never_contains_session_data(self):
        # El SW guarda esta página: no puede llevar usuario ni token CSRF de quien la pidió.
        user = get_user_model().objects.create_user("lucia", password="clave-segura-123")
        self.client.force_login(user)

        response = self.client.get(reverse("pwa:offline"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "lucia")
        self.assertNotContains(response, reverse("logout"))
        self.assertNotIn(settings.CSRF_COOKIE_NAME, response.cookies)
