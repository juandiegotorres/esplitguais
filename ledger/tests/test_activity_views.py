from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ledger import services
from ledger.models import Activity, Category, SplitType
from ledger.services import PayerInput, ShareInput

User = get_user_model()


class ActivityViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = User.objects.create_user("ana", password="x", first_name="Ana")
        cls.juan = User.objects.create_user("juan", password="x", first_name="Juan")
        cls.group = services.create_group(name="Casa", actor=cls.ana, member_ids=[cls.juan.pk])

    def setUp(self):
        self.client.force_login(self.juan)
        self.url = reverse("ledger:activity", args=[self.group.pk])

    def expense_kwargs(self, description, amount_cents):
        return dict(
            description=description,
            amount_cents=amount_cents,
            date=date(2026, 11, 10),
            category=Category.FOOD,
            split_type=SplitType.EQUAL,
            payers=[PayerInput(self.ana.pk, amount_cents)],
            shares=[ShareInput(self.ana.pk), ShareInput(self.juan.pk)],
        )

    def test_shows_expense_and_settlement_lifecycle_newest_first(self):
        expense = services.create_expense(
            group=self.group, actor=self.ana, **self.expense_kwargs("Pizza", 1_000_000)
        )
        services.update_expense(expense, actor=self.juan, **self.expense_kwargs("Pizzas", 1_200_000))
        services.delete_expense(expense, actor=self.ana)
        settlement = services.create_settlement(
            group=self.group, actor=self.juan, from_user_id=self.juan.pk,
            to_user_id=self.ana.pk, amount_cents=600_000, date=date(2026, 11, 11),
        )
        services.delete_settlement(settlement, actor=self.juan)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        entries = response.context["entries"]
        expected = list(
            Activity.objects.filter(group=self.group).order_by("-created_at", "-id")
        )
        self.assertEqual([e["summary"] for e in entries], [a.payload["summary"] for a in expected])

        lifecycle = [
            (a.target_type, a.verb) for a in reversed(expected)
            if a.target_type in (Activity.TargetType.EXPENSE, Activity.TargetType.SETTLEMENT)
        ]
        self.assertEqual(lifecycle, [
            ("expense", "created"), ("expense", "updated"), ("expense", "deleted"),
            ("settlement", "created"), ("settlement", "deleted"),
        ])
        # Más reciente primero: el borrado de la liquidación encabeza la lista y se marca.
        self.assertTrue(entries[0]["is_deleted"])
        self.assertEqual(entries[0]["actor"], "Juan")
        self.assertEqual(sum(e["is_deleted"] for e in entries), 2)
        for activity in expected:
            self.assertContains(response, activity.payload["summary"])

    def test_paginates_by_fifty(self):
        for i in range(60):
            Activity.objects.create(
                group=self.group, actor=self.ana, verb=Activity.Verb.CREATED,
                target_type=Activity.TargetType.EXPENSE, target_id=i,
                payload={"summary": f"evento {i}"},
            )
        total = Activity.objects.filter(group=self.group).count()

        first = self.client.get(self.url)
        self.assertEqual(len(first.context["entries"]), 50)
        self.assertEqual(first.context["entries"][0]["summary"], "evento 59")

        second = self.client.get(self.url, {"page": 2})
        self.assertEqual(len(second.context["entries"]), total - 50)
        summaries = [e["summary"] for e in first.context["entries"] + second.context["entries"]]
        self.assertEqual(len(set(summaries)), total)
