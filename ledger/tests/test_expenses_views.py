from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ledger import services
from ledger.models import Expense, SplitType

User = get_user_model()


class ExpenseViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = User.objects.create_user("ana", password="x")
        cls.beto = User.objects.create_user("beto", password="x")
        cls.caro = User.objects.create_user("caro", password="x")
        cls.group = services.create_group(
            name="Viaje", actor=cls.ana, member_ids=[cls.beto.pk, cls.caro.pk]
        )
        cls.other_group = services.create_group(name="Casa", actor=cls.beto, member_ids=[])

    def setUp(self):
        self.client.force_login(self.ana)

    def _equal_expense(self, group, actor, members, amount=90000, description="Nafta"):
        return services.create_expense(
            group=group,
            actor=actor,
            description=description,
            amount_cents=amount,
            date=date(2026, 11, 1),
            category="transporte",
            split_type=SplitType.EQUAL,
            payers=[services.PayerInput(user_id=actor.pk, paid_cents=amount)],
            shares=[services.ShareInput(user_id=m.pk) for m in members],
        )

    def _post_data(self, **overrides):
        data = {
            "description": "Asado",
            "amount": "1.000",
            "date": "2026-11-10",
            "category": "comida",
            "payer_mode": "multiple",
            "payer": str(self.ana.pk),
            f"payer_amount_{self.ana.pk}": "600",
            f"payer_amount_{self.beto.pk}": "400,00",
            f"payer_amount_{self.caro.pk}": "",
            "split_type": "percent",
            f"percent_{self.ana.pk}": "50",
            f"percent_{self.beto.pk}": "30",
            f"percent_{self.caro.pk}": "20",
        }
        data.update(overrides)
        return data

    def test_foreign_group_and_expense_are_404_on_get_and_post(self):
        foreign = self._equal_expense(self.other_group, self.beto, [self.beto])
        urls = [
            reverse("ledger:expense_create", args=[self.other_group.pk]),
            reverse("ledger:expense_detail", args=[self.other_group.pk, foreign.pk]),
            reverse("ledger:expense_edit", args=[self.other_group.pk, foreign.pk]),
            reverse("ledger:expense_delete", args=[self.other_group.pk, foreign.pk]),
            # Gasto ajeno colgado de un grupo propio.
            reverse("ledger:expense_detail", args=[self.group.pk, foreign.pk]),
            reverse("ledger:expense_edit", args=[self.group.pk, foreign.pk]),
            reverse("ledger:expense_delete", args=[self.group.pk, foreign.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
                self.assertEqual(self.client.post(url, self._post_data()).status_code, 404)
        foreign.refresh_from_db()
        self.assertIsNone(foreign.deleted_at)
        self.assertEqual(foreign.description, "Nafta")
        self.assertEqual(Expense.objects.filter(group=self.other_group).count(), 1)

    def test_create_with_several_payers_and_percent_split(self):
        response = self.client.post(
            reverse("ledger:expense_create", args=[self.group.pk]), self._post_data()
        )
        self.assertRedirects(response, reverse("ledger:group_detail", args=[self.group.pk]))
        expense = Expense.objects.get(group=self.group)
        self.assertEqual(expense.amount_cents, 100000)
        self.assertEqual(expense.split_type, SplitType.PERCENT)
        self.assertEqual(expense.created_by, self.ana)
        self.assertEqual(
            dict(expense.payers.values_list("user_id", "paid_cents")),
            {self.ana.pk: 60000, self.beto.pk: 40000},
        )
        shares = {s.user_id: (s.owed_cents, s.input_value) for s in expense.shares.all()}
        self.assertEqual(
            shares,
            {
                self.ana.pk: (50000, Decimal("50")),
                self.beto.pk: (30000, Decimal("30")),
                self.caro.pk: (20000, Decimal("20")),
            },
        )

    def test_single_payer_pays_whole_amount(self):
        self.client.post(
            reverse("ledger:expense_create", args=[self.group.pk]),
            self._post_data(
                payer_mode="single",
                payer=str(self.beto.pk),
                amount="15.000,50",
                split_type="equal",
                participants=[self.ana.pk, self.beto.pk, self.caro.pk],
            ),
        )
        expense = Expense.objects.get(group=self.group)
        self.assertEqual(
            list(expense.payers.values_list("user_id", "paid_cents")),
            [(self.beto.pk, 1500050)],
        )
        self.assertEqual(sum(expense.shares.values_list("owed_cents", flat=True)), 1500050)

    def test_validation_error_rerenders_with_message_and_data(self):
        url = reverse("ledger:expense_create", args=[self.group.pk])
        response = self.client.post(
            url, self._post_data(**{f"percent_{self.caro.pk}": "10"})
        )
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertTrue(form.section_errors["shares"])
        self.assertContains(response, form.section_errors["shares"][0])
        self.assertEqual(form.alpine_state()["percent"][str(self.caro.pk)], "10")
        self.assertContains(response, 'value="Asado"')
        self.assertFalse(Expense.objects.filter(group=self.group).exists())

        # Pagos que no suman el total: error en pagadores.
        response = self.client.post(
            url, self._post_data(**{f"payer_amount_{self.beto.pk}": "300"})
        )
        self.assertTrue(response.context["form"].section_errors["payers"])
        # Importe ilegible: error en el campo.
        response = self.client.post(url, self._post_data(amount="mil"))
        self.assertTrue(response.context["form"].errors["amount"])
        self.assertFalse(Expense.objects.filter(group=self.group).exists())

    def test_edit_prefills_and_replaces_payers_and_shares(self):
        self.client.post(
            reverse("ledger:expense_create", args=[self.group.pk]), self._post_data()
        )
        expense = Expense.objects.get(group=self.group)
        url = reverse("ledger:expense_edit", args=[self.group.pk, expense.pk])

        state = self.client.get(url).context["form"].alpine_state()
        self.assertEqual(state["amount"], "1.000,00")
        self.assertEqual(state["payerMode"], "multiple")
        self.assertEqual(state["payerAmounts"][str(self.ana.pk)], "600,00")
        self.assertEqual(state["splitType"], "percent")
        self.assertEqual(state["percent"][str(self.caro.pk)], "20")

        response = self.client.post(
            url,
            self._post_data(
                description="Asado editado",
                payer_mode="single",
                payer=str(self.caro.pk),
                split_type="exact",
                **{
                    f"exact_{self.ana.pk}": "250",
                    f"exact_{self.beto.pk}": "750",
                    f"exact_{self.caro.pk}": "",
                },
            ),
        )
        self.assertRedirects(
            response, reverse("ledger:expense_detail", args=[self.group.pk, expense.pk])
        )
        expense.refresh_from_db()
        self.assertEqual(expense.description, "Asado editado")
        self.assertEqual(expense.split_type, SplitType.EXACT)
        self.assertEqual(
            list(expense.payers.values_list("user_id", "paid_cents")),
            [(self.caro.pk, 100000)],
        )
        self.assertEqual(
            dict(expense.shares.values_list("user_id", "owed_cents")),
            {self.ana.pk: 25000, self.beto.pk: 75000},
        )

    def test_delete_is_logical_and_hides_expense(self):
        expense = self._equal_expense(self.group, self.ana, [self.ana, self.beto])
        detail_url = reverse("ledger:expense_detail", args=[self.group.pk, expense.pk])
        list_url = reverse("ledger:group_detail", args=[self.group.pk])
        self.assertIn(expense, self.client.get(list_url).context["expenses"])

        delete_url = reverse("ledger:expense_delete", args=[self.group.pk, expense.pk])
        self.assertEqual(self.client.get(delete_url).status_code, 200)  # confirmación
        self.assertIsNone(Expense.objects.get(pk=expense.pk).deleted_at)

        response = self.client.post(delete_url)
        self.assertRedirects(response, list_url)
        self.assertIsNotNone(Expense.objects.get(pk=expense.pk).deleted_at)
        self.assertNotIn(expense, self.client.get(list_url).context["expenses"])
        self.assertEqual(self.client.get(detail_url).status_code, 404)
        self.assertEqual(
            self.client.get(
                reverse("ledger:expense_edit", args=[self.group.pk, expense.pk])
            ).status_code,
            404,
        )
