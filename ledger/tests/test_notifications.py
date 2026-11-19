from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from ledger import services
from ledger.models import Expense

User = get_user_model()

PUSH_ON = override_settings(
    WEBPUSH_VAPID_PUBLIC_KEY="pub", WEBPUSH_VAPID_PRIVATE_KEY="priv", WEBPUSH_VAPID_SUBJECT="https://x"
)


@PUSH_ON
@mock.patch("pwa.push.send")
class NotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = User.objects.create_user("ana", password="x", first_name="Ana")
        cls.beto = User.objects.create_user("beto", password="x")
        cls.caro = User.objects.create_user("caro", password="x")
        cls.dani = User.objects.create_user("dani", password="x")
        cls.group = services.create_group(
            name="Viaje", actor=cls.ana, member_ids=[cls.beto.pk, cls.caro.pk, cls.dani.pk]
        )

    def setUp(self):
        self.client.force_login(self.ana)

    def _expense_data(self, payer, participants, **extra):
        data = {
            "description": "Asado",
            "amount": "1.000",
            "date": "2026-11-10",
            "category": "comida",
            "payer_mode": "single",
            "payer": str(payer.pk),
            "split_type": "equal",
            "participants": [str(u.pk) for u in participants],
        }
        data.update(extra)
        return data

    @staticmethod
    def _sent(send):
        """user_id → cuerpo de la notificación del último envío."""
        return {uid: n.body for uid, n in send.call_args.args[0].items()}

    def test_new_expense_notifies_participants_except_who_created_it(self, send):
        # Ana paga y lo carga; Beto tiene parte; Caro y Dani no participan.
        self.client.post(
            reverse("ledger:expense_create", args=[self.group.pk]),
            self._expense_data(self.ana, [self.ana, self.beto]),
        )

        sent = self._sent(send)
        self.assertEqual(set(sent), {self.beto.pk})
        self.assertEqual(sent[self.beto.pk], "Ana cargó «Asado» por $ 1.000,00. Debés $ 500,00.")
        notification = send.call_args.args[0][self.beto.pk]
        expense = Expense.objects.get()
        self.assertEqual(notification.title, "Viaje")
        self.assertEqual(
            notification.url, reverse("ledger:expense_detail", args=[self.group.pk, expense.pk])
        )

    def test_payer_without_share_is_notified(self, send):
        self.client.post(
            reverse("ledger:expense_create", args=[self.group.pk]),
            self._expense_data(self.caro, [self.ana, self.beto]),
        )

        sent = self._sent(send)
        self.assertEqual(set(sent), {self.beto.pk, self.caro.pk})
        self.assertTrue(sent[self.caro.pk].endswith("Te deben $ 1.000,00."))

    def test_edit_also_notifies_who_was_removed(self, send):
        self.client.post(
            reverse("ledger:expense_create", args=[self.group.pk]),
            self._expense_data(self.ana, [self.ana, self.beto]),
        )
        expense = Expense.objects.get()

        self.client.post(
            reverse("ledger:expense_edit", args=[self.group.pk, expense.pk]),
            self._expense_data(self.caro, [self.ana, self.caro]),
        )

        sent = self._sent(send)
        self.assertEqual(set(sent), {self.beto.pk, self.caro.pk})
        self.assertEqual(sent[self.beto.pk], "Ana editó «Asado» por $ 1.000,00. Ya no participás.")
        self.assertTrue(sent[self.caro.pk].endswith("Te deben $ 500,00."))

    def test_invalid_expense_sends_nothing(self, send):
        self.client.post(
            reverse("ledger:expense_create", args=[self.group.pk]),
            self._expense_data(self.ana, []),
        )

        send.assert_not_called()

    def test_settlement_notifies_the_other_party(self, send):
        url = reverse("ledger:settlement_create", args=[self.group.pk])
        data = {"amount": "250", "date": "2026-11-18", "note": ""}

        self.client.post(url, {**data, "from_user": self.beto.pk, "to_user": self.ana.pk})
        self.assertEqual(self._sent(send), {self.beto.pk: "Ana registró que le pagaste $ 250,00."})

        self.client.post(url, {**data, "from_user": self.ana.pk, "to_user": self.caro.pk})
        self.assertEqual(self._sent(send), {self.caro.pk: "Ana registró que te pagó $ 250,00."})

    @override_settings(WEBPUSH_VAPID_PRIVATE_KEY="")
    def test_nothing_is_sent_without_vapid_keys(self, send):
        self.client.post(
            reverse("ledger:expense_create", args=[self.group.pk]),
            self._expense_data(self.ana, [self.ana, self.beto]),
        )

        self.assertTrue(Expense.objects.exists())
        send.assert_not_called()
