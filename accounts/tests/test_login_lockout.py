from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

PASSWORD = "asado-del-domingo-42"
IP_A = "190.0.0.1"
IP_B = "181.0.0.2"
# Detrás de Cloudflare Tunnel todas las requests llegan desde el contenedor cloudflared.
TUNNEL_ADDR = "172.18.0.5"


class LoginLockoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("juan", password=PASSWORD)
        self.url = reverse("login")

    def post(self, password, cf_ip=None, remote_addr=TUNNEL_ADDR, username="juan"):
        extra = {"REMOTE_ADDR": remote_addr}
        if cf_ip:
            extra["HTTP_CF_CONNECTING_IP"] = cf_ip
        return self.client.post(self.url, {"username": username, "password": password}, **extra)

    def assert_logged_in(self, response):
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
        self.client.logout()

    def fail_login(self, times, cf_ip=None, remote_addr=TUNNEL_ADDR):
        for _ in range(times):
            self.post("incorrecta", cf_ip=cf_ip, remote_addr=remote_addr)

    def test_same_cf_ip_is_locked_after_five_failures(self):
        self.fail_login(4, cf_ip=IP_A)
        response = self.post("incorrecta", cf_ip=IP_A)
        self.assertEqual(response.status_code, 429)

        response = self.post(PASSWORD, cf_ip=IP_A)
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_other_cf_ip_through_same_tunnel_is_not_locked(self):
        self.fail_login(5, cf_ip=IP_A)
        self.assert_logged_in(self.post(PASSWORD, cf_ip=IP_B))
        self.assertEqual(self.post(PASSWORD, cf_ip=IP_A).status_code, 429)

    def test_lock_is_per_username(self):
        other = User.objects.create_user("ana", password=PASSWORD)
        self.fail_login(5, cf_ip=IP_A)
        response = self.post(PASSWORD, cf_ip=IP_A, username="ana")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), other.pk)

    def test_successful_login_resets_failure_count(self):
        self.fail_login(4, cf_ip=IP_A)
        self.assert_logged_in(self.post(PASSWORD, cf_ip=IP_A))
        self.fail_login(4, cf_ip=IP_A)
        self.assert_logged_in(self.post(PASSWORD, cf_ip=IP_A))

    def test_without_cf_header_uses_remote_addr(self):
        self.fail_login(5, remote_addr="127.0.0.1")
        self.assertEqual(self.post(PASSWORD, remote_addr="127.0.0.1").status_code, 429)
        self.assert_logged_in(self.post(PASSWORD, remote_addr="127.0.0.2"))
