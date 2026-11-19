from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ledger import services
from ledger.models import Category, Settlement, SplitType
from ledger.services import PayerInput, ShareInput

User = get_user_model()


class BalancesViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = [
            User.objects.create_user(f"amigo{i}", password="x", first_name=f"Amigo{i}")
            for i in range(8)
        ]
        cls.outsider = User.objects.create_user("ajeno", password="x")
        u = cls.users
        cls.group = services.create_group(
            name="Viaje", actor=u[0], member_ids=[x.pk for x in u]
        )

        def expense(desc, amount, split_type, payers, shares):
            services.create_expense(
                group=cls.group,
                actor=u[0],
                description=desc,
                amount_cents=amount,
                date=date(2026, 11, 1),
                category=Category.GENERAL,
                split_type=split_type,
                payers=payers,
                shares=shares,
            )

        # Partes iguales entre todos, un pagador, con resto de centavos.
        expense("Asado", 1_500_001, SplitType.EQUAL, [PayerInput(u[0].pk, 1_500_001)],
                [ShareInput(x.pk) for x in u])
        # Varios pagadores, importes exactos.
        expense("Nafta", 900_000, SplitType.EXACT,
                [PayerInput(u[1].pk, 600_000), PayerInput(u[2].pk, 300_000)],
                [ShareInput(u[3].pk, 400_000), ShareInput(u[4].pk, 250_000),
                 ShareInput(u[1].pk, 250_000)])
        # Porcentajes.
        expense("Cabaña", 3_333_333, SplitType.PERCENT, [PayerInput(u[5].pk, 3_333_333)],
                [ShareInput(u[5].pk, Decimal("33.3333")), ShareInput(u[6].pk, Decimal("33.3333")),
                 ShareInput(u[7].pk, Decimal("33.3334"))])
        # Partes.
        expense("Súper", 777_777, SplitType.SHARES,
                [PayerInput(u[6].pk, 500_000), PayerInput(u[3].pk, 277_777)],
                [ShareInput(u[0].pk, Decimal("2")), ShareInput(u[2].pk, Decimal("1")),
                 ShareInput(u[4].pk, Decimal("3"))])

    def setUp(self):
        self.client.force_login(self.users[0])

    def url(self, name, *args):
        return reverse(f"ledger:{name}", args=[self.group.pk, *args])

    def post_settlement(self, from_id, to_id, amount_text, **extra):
        data = {"from_user": from_id, "to_user": to_id, "amount": amount_text,
                "date": "2026-11-18", "note": ""}
        data.update(extra)
        return self.client.post(self.url("settlement_create"), data)

    def test_registering_every_suggested_transfer_settles_the_group(self):
        # Cada deudor ve sus pagos en "Mis deudas" y los registra con el formulario prellenado.
        pending = []
        for user in self.users:
            self.client.force_login(user)
            response = self.client.get(self.url("balances"))
            mine = response.context["my_transfers"]
            pending += [(user, t["url"]) for t in mine if t["i_pay"]]
        self.assertGreater(len(pending), 0)
        self.assertLessEqual(len(pending), 7)

        for user, url in pending:
            self.client.force_login(user)
            form_page = self.client.get(url)
            self.assertEqual(form_page.status_code, 200)
            initial = form_page.context["form"].initial
            query = parse_qs(urlparse(url).query)
            self.assertEqual(initial["from_user"], user.pk)
            self.assertEqual(initial["from_user"], int(query["from"][0]))
            self.assertEqual(initial["to_user"], int(query["to"][0]))
            response = self.post_settlement(initial["from_user"], initial["to_user"],
                                            initial["amount"])
            self.assertRedirects(response, self.url("balances"))

        response = self.client.get(self.url("balances"))
        self.assertEqual([r["cents"] for r in response.context["rows"]], [0] * 8)
        self.assertEqual(response.context["my_transfers"], [])
        self.assertEqual(response.context["group_transfers"], [])
        self.assertEqual(set(services.group_balances(self.group).values()), {0})
        self.assertEqual(Settlement.objects.active().filter(group=self.group).count(),
                         len(pending))

    def test_my_debts_are_separated_from_the_rest_of_the_group(self):
        me = self.users[0].pk
        transfers = services.simplify_debts(services.group_balances(self.group))
        response = self.client.get(self.url("balances"))
        mine = response.context["my_transfers"]
        others = response.context["group_transfers"]
        self.assertEqual(len(mine), sum(me in (t.from_user_id, t.to_user_id) for t in transfers))
        self.assertEqual(len(mine) + len(others), len(transfers))
        # Lo ajeno es solo informativo: sin botón para registrarlo ni alias para copiar.
        for t in others:
            self.assertNotIn("url", t)
            self.assertNotIn("to_alias", t)

    def test_success_message_names_payer_amount_and_receiver(self):
        u = self.users
        response = self.post_settlement(u[0].pk, u[2].pk, "40.000", note="transferencia")
        self.assertRedirects(response, self.url("balances"), fetch_redirect_response=False)
        page = self.client.get(response.url)
        self.assertContains(page, "Amigo0 le pagó $ 40.000,00 a Amigo2")

    def test_invalid_settlements_are_rejected_with_errors(self):
        u = self.users
        cases = [
            (u[1].pk, u[1].pk, "100", "to_user"),
            (u[1].pk, self.outsider.pk, "100", "to_user"),
            (u[1].pk, u[2].pk, "abc", "amount"),
            (u[1].pk, u[2].pk, "0", "amount"),
            # Pago entre otros dos: no le corresponde a quien lo registra.
            (u[1].pk, u[2].pk, "100", "__all__"),
        ]
        for from_id, to_id, amount, field in cases:
            with self.subTest(from_id=from_id, to_id=to_id, amount=amount):
                response = self.post_settlement(from_id, to_id, amount)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors.get(field))
        self.assertFalse(Settlement.objects.exists())

    def test_deleting_a_settlement_restores_balances(self):
        before = services.group_balances(self.group)
        u = self.users
        self.post_settlement(u[3].pk, u[0].pk, "1.234,56")
        settlement = Settlement.objects.get()
        self.assertNotEqual(services.group_balances(self.group), before)

        response = self.client.post(self.url("settlement_delete", settlement.pk))
        self.assertRedirects(response, self.url("balances"))
        self.assertEqual(services.group_balances(self.group), before)
        settlement.refresh_from_db()
        self.assertIsNotNone(settlement.deleted_at)
        # Ya borrada: no se puede volver a borrar.
        response = self.client.post(self.url("settlement_delete", settlement.pk))
        self.assertEqual(response.status_code, 404)

    def test_only_the_parties_can_delete_a_settlement(self):
        u = self.users
        settlement = services.create_settlement(
            group=self.group, actor=u[1], from_user_id=u[1].pk,
            to_user_id=u[2].pk, amount_cents=100, date=date(2026, 11, 18),
        )
        page = self.client.get(self.url("balances"))
        self.assertNotContains(page, self.url("settlement_delete", settlement.pk))
        response = self.client.post(self.url("settlement_delete", settlement.pk))
        self.assertEqual(response.status_code, 404)
        settlement.refresh_from_db()
        self.assertIsNone(settlement.deleted_at)

        self.client.force_login(u[2])
        response = self.client.post(self.url("settlement_delete", settlement.pk))
        self.assertRedirects(response, self.url("balances"))
        settlement.refresh_from_db()
        self.assertIsNotNone(settlement.deleted_at)

    def test_settlement_delete_requires_post(self):
        settlement = services.create_settlement(
            group=self.group, actor=self.users[0], from_user_id=self.users[0].pk,
            to_user_id=self.users[2].pk, amount_cents=100, date=date(2026, 11, 18),
        )
        response = self.client.get(self.url("settlement_delete", settlement.pk))
        self.assertEqual(response.status_code, 405)
        settlement.refresh_from_db()
        self.assertIsNone(settlement.deleted_at)

    def test_outsider_gets_404_everywhere(self):
        settlement = services.create_settlement(
            group=self.group, actor=self.users[1], from_user_id=self.users[1].pk,
            to_user_id=self.users[2].pk, amount_cents=5000, date=date(2026, 11, 18),
        )
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url("balances")).status_code, 404)
        self.assertEqual(self.client.get(self.url("activity")).status_code, 404)
        self.assertEqual(self.client.get(self.url("settlement_create")).status_code, 404)
        response = self.post_settlement(self.users[1].pk, self.users[2].pk, "100")
        self.assertEqual(response.status_code, 404)
        response = self.client.post(self.url("settlement_delete", settlement.pk))
        self.assertEqual(response.status_code, 404)

        self.assertEqual(Settlement.objects.active().count(), 1)

    def test_settlement_from_another_group_is_404(self):
        other = services.create_group(name="Otro", actor=self.users[0],
                                      member_ids=[self.users[1].pk])
        settlement = services.create_settlement(
            group=other, actor=self.users[0], from_user_id=self.users[1].pk,
            to_user_id=self.users[0].pk, amount_cents=5000, date=date(2026, 11, 18),
        )
        response = self.client.post(self.url("settlement_delete", settlement.pk))
        self.assertEqual(response.status_code, 404)
        settlement.refresh_from_db()
        self.assertIsNone(settlement.deleted_at)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(self.url("balances"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
