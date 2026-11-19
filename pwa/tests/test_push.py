import json
from unittest import mock

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from pywebpush import WebPushException

from pwa import push
from pwa.models import PushSubscription

User = get_user_model()

APPLE = "https://web.push.apple.com/QGuQyavXutnMH"
FCM = "https://fcm.googleapis.com/fcm/send/abc:123"
KEYS = {"p256dh": "BEl6", "auth": "c2VjcmV0"}


def subscription(endpoint=APPLE, keys=KEYS):
    return json.dumps({"endpoint": endpoint, "expirationTime": None, "keys": keys})


class SubscribeViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = User.objects.create_user("ana", password="x")
        cls.beto = User.objects.create_user("beto", password="x")

    def post(self, name, body):
        return self.client.post(reverse(name), body, content_type="application/json")

    def test_requires_login(self):
        response = self.post("pwa:push_subscribe", subscription())

        self.assertEqual(response.status_code, 302)
        self.assertFalse(PushSubscription.objects.exists())

    def test_device_moves_to_whoever_subscribes_last(self):
        self.client.force_login(self.ana)
        self.assertEqual(self.post("pwa:push_subscribe", subscription()).status_code, 204)
        self.client.force_login(self.beto)
        self.post("pwa:push_subscribe", subscription(keys={"p256dh": "nueva", "auth": "otra"}))

        sub = PushSubscription.objects.get()
        self.assertEqual((sub.user, sub.p256dh, sub.auth), (self.beto, "nueva", "otra"))

    def test_rejects_unknown_push_hosts_and_malformed_bodies(self):
        self.client.force_login(self.ana)
        bad = [
            subscription(endpoint="https://127.0.0.1/admin/"),
            subscription(endpoint="http://web.push.apple.com/x"),
            subscription(endpoint="https://web.push.apple.com.evil.com/x"),
            subscription(keys={"p256dh": "BEl6"}),
            json.dumps({"endpoint": APPLE, "keys": "x"}),
            json.dumps(["no"]),
            "no es json",
        ]
        for body in bad:
            with self.subTest(body=body):
                self.assertEqual(self.post("pwa:push_subscribe", body).status_code, 400)
        self.assertFalse(PushSubscription.objects.exists())

    def test_unsubscribe_only_removes_own_device(self):
        PushSubscription.objects.create(user=self.beto, endpoint=APPLE, **KEYS)
        self.client.force_login(self.ana)

        self.post("pwa:push_unsubscribe", json.dumps({"endpoint": APPLE}))
        self.assertTrue(PushSubscription.objects.exists())

        self.client.force_login(self.beto)
        self.post("pwa:push_unsubscribe", json.dumps({"endpoint": APPLE}))
        self.assertFalse(PushSubscription.objects.exists())


def failure(status):
    response = requests.Response()
    response.status_code = status
    return WebPushException(f"Push failed: {status}", response=response)


@override_settings(
    WEBPUSH_VAPID_PUBLIC_KEY="pub", WEBPUSH_VAPID_PRIVATE_KEY="priv", WEBPUSH_VAPID_SUBJECT="https://x"
)
class SendTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = User.objects.create_user("ana", password="x")
        cls.beto = User.objects.create_user("beto", password="x")
        cls.ana_phone = PushSubscription.objects.create(user=cls.ana, endpoint=APPLE, **KEYS)
        cls.ana_laptop = PushSubscription.objects.create(user=cls.ana, endpoint=FCM, **KEYS)
        cls.beto_phone = PushSubscription.objects.create(
            user=cls.beto, endpoint=APPLE + "beto", **KEYS
        )

    def note(self, body):
        return push.Notification(title="Viaje", body=body, url="/grupos/1/", tag="expense-1")

    @mock.patch("pywebpush.webpush")
    def test_sends_each_user_their_own_message_on_every_device(self, webpush):
        push.send({self.ana.pk: self.note("para ana")})

        sent = {c.kwargs["subscription_info"]["endpoint"]: c.kwargs for c in webpush.call_args_list}
        self.assertEqual(set(sent), {APPLE, FCM})
        payload = json.loads(sent[APPLE]["data"])
        self.assertEqual(payload["body"], "para ana")
        self.assertEqual(payload["url"], "/grupos/1/")
        self.assertEqual(sent[APPLE]["subscription_info"]["keys"], KEYS)

    @mock.patch("pywebpush.webpush")
    def test_expired_devices_are_removed_and_other_errors_are_swallowed(self, webpush):
        def fake(subscription_info, **kwargs):
            endpoint = subscription_info["endpoint"]
            if endpoint == APPLE:
                raise failure(410)
            if endpoint == FCM:
                raise requests.ConnectionError("sin red")
            raise failure(500)

        webpush.side_effect = fake

        with self.assertLogs("pwa.push", "WARNING") as logs:
            push.send({self.ana.pk: self.note("a"), self.beto.pk: self.note("b")})

        self.assertEqual(len(logs.records), 2)
        self.assertEqual(
            set(PushSubscription.objects.values_list("pk", flat=True)),
            {self.ana_laptop.pk, self.beto_phone.pk},
        )

    @override_settings(WEBPUSH_VAPID_PUBLIC_KEY="")
    @mock.patch("pywebpush.webpush")
    def test_disabled_without_keys(self, webpush):
        push.send({self.ana.pk: self.note("a")})

        webpush.assert_not_called()
