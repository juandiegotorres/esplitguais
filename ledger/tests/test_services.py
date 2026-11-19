import random
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.test import SimpleTestCase, TestCase

from ledger.models import Activity, Category, Expense, ExpenseShare, Settlement, SplitType
from ledger.services import (
    PayerInput,
    ShareInput,
    Transfer,
    add_member,
    compute_shares,
    create_expense,
    create_group,
    create_settlement,
    delete_expense,
    delete_settlement,
    group_balances,
    group_spending,
    simplify_debts,
    update_expense,
)

D = Decimal
TODAY = date(2026, 11, 18)


class ComputeSharesTests(SimpleTestCase):
    def test_equal_remainder_goes_to_lowest_user_ids(self):
        shares = [ShareInput(9), ShareInput(2), ShareInput(5)]
        self.assertEqual(compute_shares(1000, SplitType.EQUAL, shares), {2: 334, 5: 333, 9: 333})
        self.assertEqual(
            compute_shares(1001, SplitType.EQUAL, shares), {2: 334, 5: 334, 9: 333}
        )
        self.assertEqual(compute_shares(1, SplitType.EQUAL, shares), {2: 1, 5: 0, 9: 0})

    def test_exact_must_sum_total(self):
        shares = [ShareInput(1, 600), ShareInput(2, 400)]
        self.assertEqual(compute_shares(1000, SplitType.EXACT, shares), {1: 600, 2: 400})
        with self.assertRaises(ValidationError) as ctx:
            compute_shares(1001, SplitType.EXACT, shares)
        self.assertIn("shares", ctx.exception.message_dict)
        with self.assertRaises(ValidationError):
            compute_shares(1000, SplitType.EXACT, [ShareInput(1, 1100), ShareInput(2, -100)])

    def test_percent_floor_and_remainder(self):
        shares = [ShareInput(3, D("33.33")), ShareInput(1, D("33.33")), ShareInput(2, D("33.34"))]
        # floors: 333 (33,33 %), 333, 333 (33,34 % de 1000 = 333,4) → resto 1 al user 1.
        self.assertEqual(
            compute_shares(1000, SplitType.PERCENT, shares), {1: 334, 2: 333, 3: 333}
        )
        four_decimals = [
            ShareInput(1, D("33.3333")),
            ShareInput(2, D("33.3333")),
            ShareInput(3, D("33.3334")),
        ]
        result = compute_shares(10000, SplitType.PERCENT, four_decimals)
        self.assertEqual(result, {1: 3334, 2: 3333, 3: 3333})
        self.assertEqual(
            compute_shares(999, SplitType.PERCENT, [ShareInput(1, 50), ShareInput(2, D("50"))]),
            {1: 500, 2: 499},
        )

    def test_percent_must_sum_100(self):
        for values in [(D("33.33"), D("33.33"), D("33.33")), (D("50"), D("50.01"), D("0"))]:
            with self.subTest(values=values):
                with self.assertRaises(ValidationError) as ctx:
                    compute_shares(
                        1000,
                        SplitType.PERCENT,
                        [ShareInput(i, v) for i, v in enumerate(values, start=1)],
                    )
                self.assertIn("shares", ctx.exception.message_dict)
        with self.assertRaises(ValidationError):
            compute_shares(1000, SplitType.PERCENT, [ShareInput(1, D("110")), ShareInput(2, D("-10"))])

    def test_shares_proportional_with_remainder(self):
        shares = [ShareInput(1, D("2")), ShareInput(2, D("1")), ShareInput(3, D("1"))]
        self.assertEqual(compute_shares(1001, SplitType.SHARES, shares), {1: 501, 2: 250, 3: 250})
        thirds = [ShareInput(5, D("1")), ShareInput(4, D("1")), ShareInput(6, D("1"))]
        self.assertEqual(compute_shares(100, SplitType.SHARES, thirds), {4: 34, 5: 33, 6: 33})
        fractional = [ShareInput(1, D("1.5")), ShareInput(2, D("0.5"))]
        self.assertEqual(compute_shares(1001, SplitType.SHARES, fractional), {1: 751, 2: 250})

    def test_shares_must_be_positive(self):
        for bad in [D("0"), D("-1")]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    compute_shares(1000, SplitType.SHARES, [ShareInput(1, D("1")), ShareInput(2, bad)])

    def test_rejects_empty_duplicates_and_bad_amount(self):
        with self.assertRaises(ValidationError):
            compute_shares(1000, SplitType.EQUAL, [])
        with self.assertRaises(ValidationError):
            compute_shares(1000, SplitType.EQUAL, [ShareInput(1), ShareInput(1)])
        for amount in [0, -100]:
            with self.assertRaises(ValidationError) as ctx:
                compute_shares(amount, SplitType.EQUAL, [ShareInput(1)])
            self.assertIn("amount_cents", ctx.exception.message_dict)
        with self.assertRaises(ValidationError):
            compute_shares(1000, SplitType.PERCENT, [ShareInput(1, D("100.00001"))])

    def test_always_sums_total(self):
        rng = random.Random(1234)
        for _ in range(300):
            n = rng.randint(1, 8)
            ids = rng.sample(range(1, 50), n)
            amount = rng.randint(1, 10**9)
            split = rng.choice([SplitType.EQUAL, SplitType.SHARES, SplitType.PERCENT])
            if split == SplitType.EQUAL:
                shares = [ShareInput(i) for i in ids]
            elif split == SplitType.SHARES:
                shares = [ShareInput(i, D(rng.randint(1, 400)) / 4) for i in ids]
            else:
                cuts = sorted(rng.sample(range(1, 1_000_000), n - 1))
                bounds = [0, *cuts, 1_000_000]
                shares = [
                    ShareInput(i, D(bounds[k + 1] - bounds[k]) / 10_000) for k, i in enumerate(ids)
                ]
            result = compute_shares(amount, split, shares)
            self.assertEqual(sum(result.values()), amount)
            self.assertEqual(set(result), set(ids))


class SimplifyDebtsTests(SimpleTestCase):
    def apply(self, balances, transfers):
        result = dict(balances)
        for t in transfers:
            self.assertGreater(t.amount_cents, 0)
            self.assertNotEqual(t.from_user_id, t.to_user_id)
            result[t.from_user_id] += t.amount_cents
            result[t.to_user_id] -= t.amount_cents
        return result

    def test_eight_users(self):
        balances = {1: 50000, 2: 30000, 3: -10000, 4: -20000, 5: -25000, 6: -5000, 7: -15000, 8: -5000}
        transfers = simplify_debts(balances)
        self.assertLessEqual(len(transfers), 7)
        self.assertTrue(all(v == 0 for v in self.apply(balances, transfers).values()))

    def test_deterministic_tie_break_and_zero_ignored(self):
        balances = {4: 100, 2: 100, 3: -100, 1: -100, 9: 0}
        expected = [Transfer(1, 2, 100), Transfer(3, 4, 100)]
        self.assertEqual(simplify_debts(balances), expected)
        self.assertEqual(simplify_debts(dict(reversed(list(balances.items())))), expected)
        self.assertEqual(simplify_debts({1: 0, 2: 0}), [])

    def test_randomized_eight_users(self):
        rng = random.Random(20261118)
        for _ in range(500):
            values = [rng.randint(-10**8, 10**8) for _ in range(7)]
            values.append(-sum(values))
            if rng.random() < 0.3:
                values[rng.randrange(7)] = 0
                values[7] = 0
                values[7] = -sum(values)
            balances = dict(zip(rng.sample(range(1, 100), 8), values))
            transfers = simplify_debts(balances)
            nonzero = sum(1 for v in balances.values() if v)
            self.assertLessEqual(len(transfers), max(nonzero - 1, 0))
            self.assertLessEqual(len(transfers), 7)
            self.assertTrue(all(v == 0 for v in self.apply(balances, transfers).values()))
            self.assertEqual(transfers, simplify_debts(balances))

    def test_rejects_unbalanced(self):
        with self.assertRaises(ValueError):
            simplify_debts({1: 100, 2: -99})


class LedgerServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.users = [
            User.objects.create_user(username=f"u{i}", password="x", first_name=f"Amigo{i}")
            for i in range(1, 9)
        ]
        cls.outsider = User.objects.create_user(username="ajeno", password="x")

    def setUp(self):
        self.u = self.users
        self.group = create_group(
            name="Viaje", actor=self.u[0], member_ids=[u.pk for u in self.u[1:]]
        )

    def expense(self, **overrides):
        kwargs = {
            "group": self.group,
            "actor": self.u[0],
            "description": "Asado",
            "amount_cents": 1000,
            "date": TODAY,
            "category": Category.FOOD,
            "split_type": SplitType.EQUAL,
            "payers": [PayerInput(self.u[0].pk, 1000)],
            "shares": [ShareInput(u.pk) for u in self.u[:3]],
        }
        kwargs.update(overrides)
        return create_expense(**kwargs)

    def assert_balanced(self):
        balances = group_balances(self.group)
        self.assertEqual(set(balances), {u.pk for u in self.u})
        self.assertEqual(sum(balances.values()), 0)
        return balances

    def test_create_group_includes_actor(self):
        group = create_group(name="  Casa ", actor=self.u[3], member_ids=[self.u[4].pk])
        self.assertEqual(group.name, "Casa")
        self.assertEqual(
            set(group.memberships.values_list("user_id", flat=True)), {self.u[3].pk, self.u[4].pk}
        )
        with self.assertRaises(ValidationError):
            create_group(name="", actor=self.u[0], member_ids=[])

    def test_add_member_rejects_existing(self):
        group = create_group(name="Casa", actor=self.u[0], member_ids=[])
        add_member(group, self.u[1], actor=self.u[0])
        with self.assertRaises(ValidationError):
            add_member(group, self.u[1], actor=self.u[0])
        self.assertEqual(group.memberships.count(), 2)

    def test_create_expense_stores_rows(self):
        expense = self.expense(
            amount_cents=1001,
            split_type=SplitType.PERCENT,
            payers=[PayerInput(self.u[0].pk, 1001)],
            shares=[ShareInput(self.u[1].pk, D("25.5")), ShareInput(self.u[0].pk, D("74.5"))],
        )
        rows = {s.user_id: (s.owed_cents, s.input_value) for s in expense.shares.all()}
        self.assertEqual(rows, {self.u[0].pk: (746, D("74.5")), self.u[1].pk: (255, D("25.5"))})

    def test_payers_must_sum_total(self):
        cases = [
            [PayerInput(self.u[0].pk, 600), PayerInput(self.u[1].pk, 300)],
            [PayerInput(self.u[0].pk, 1001)],
            [PayerInput(self.u[0].pk, 1000), PayerInput(self.u[1].pk, 0)],
            [PayerInput(self.u[0].pk, 1100), PayerInput(self.u[1].pk, -100)],
            [PayerInput(self.u[0].pk, 500), PayerInput(self.u[0].pk, 500)],
            [],
        ]
        for payers in cases:
            with self.subTest(payers=payers):
                with self.assertRaises(ValidationError) as ctx:
                    self.expense(payers=payers)
                self.assertIn("payers", ctx.exception.message_dict)
        self.assertFalse(Expense.objects.exists())

    def test_percent_not_100_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self.expense(
                split_type=SplitType.PERCENT,
                shares=[ShareInput(self.u[0].pk, D("60")), ShareInput(self.u[1].pk, D("30"))],
            )
        self.assertIn("shares", ctx.exception.message_dict)
        self.assertFalse(Expense.objects.exists())

    def test_non_members_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self.expense(payers=[PayerInput(self.outsider.pk, 1000)])
        self.assertIn("payers", ctx.exception.message_dict)
        with self.assertRaises(ValidationError) as ctx:
            self.expense(shares=[ShareInput(self.u[0].pk), ShareInput(self.outsider.pk)])
        self.assertIn("shares", ctx.exception.message_dict)
        with self.assertRaises(ValidationError):
            create_settlement(
                group=self.group,
                actor=self.u[0],
                from_user_id=self.outsider.pk,
                to_user_id=self.u[0].pk,
                amount_cents=100,
                date=TODAY,
            )
        with self.assertRaises(ValidationError):
            create_settlement(
                group=self.group,
                actor=self.u[0],
                from_user_id=self.u[0].pk,
                to_user_id=self.u[0].pk,
                amount_cents=100,
                date=TODAY,
            )
        with self.assertRaises(ValidationError) as ctx:
            create_settlement(
                group=self.group,
                actor=self.u[0],
                from_user_id=self.u[1].pk,
                to_user_id=self.u[2].pk,
                amount_cents=100,
                date=TODAY,
            )
        self.assertIn(NON_FIELD_ERRORS, ctx.exception.message_dict)
        self.assertFalse(Expense.objects.exists())
        self.assertFalse(Settlement.objects.exists())

    def test_balances_mixed_scenario(self):
        u = [x.pk for x in self.u]
        self.expense(  # equal, 2 pagadores: 1000 entre 3 → 334/333/333
            payers=[PayerInput(u[0], 700), PayerInput(u[1], 300)],
            shares=[ShareInput(u[0]), ShareInput(u[1]), ShareInput(u[2])],
        )
        self.expense(
            amount_cents=5000,
            split_type=SplitType.EXACT,
            payers=[PayerInput(u[3], 5000)],
            shares=[ShareInput(u[3], 1000), ShareInput(u[4], 4000)],
        )
        self.expense(
            amount_cents=10001,
            split_type=SplitType.PERCENT,
            payers=[PayerInput(u[5], 10001)],
            shares=[ShareInput(u[6], D("50")), ShareInput(u[7], D("50"))],
        )
        self.expense(
            amount_cents=900,
            split_type=SplitType.SHARES,
            payers=[PayerInput(u[2], 400), PayerInput(u[7], 500)],
            shares=[ShareInput(u[0], D("2")), ShareInput(u[1], D("1"))],
        )
        deleted = self.expense(amount_cents=123456, payers=[PayerInput(u[4], 123456)])
        delete_expense(deleted, actor=self.u[0])
        create_settlement(
            group=self.group, actor=self.u[4], from_user_id=u[4], to_user_id=u[3],
            amount_cents=1500, date=TODAY,
        )
        gone = create_settlement(
            group=self.group, actor=self.u[6], from_user_id=u[6], to_user_id=u[5],
            amount_cents=99999, date=TODAY,
        )
        delete_settlement(gone, actor=self.u[6])

        balances = self.assert_balanced()
        self.assertEqual(
            balances,
            {
                u[0]: 700 - 334 - 600,
                u[1]: 300 - 333 - 300,
                u[2]: -333 + 400,
                u[3]: 5000 - 1000 - 1500,
                u[4]: -4000 + 1500,
                u[5]: 10001,
                u[6]: -5001,
                u[7]: -5000 + 500,
            },
        )

    def test_suggested_settlements_zero_all_balances(self):
        rng = random.Random(42)
        ids = [x.pk for x in self.u]
        for _ in range(30):
            amount = rng.randint(1, 10**7)
            payers_ids = rng.sample(ids, rng.randint(1, 3))
            cut = sorted(rng.sample(range(1, amount), len(payers_ids) - 1)) if amount > 3 else []
            if len(cut) != len(payers_ids) - 1:
                payers_ids, cut = payers_ids[:1], []
            bounds = [0, *cut, amount]
            payers = [PayerInput(p, bounds[k + 1] - bounds[k]) for k, p in enumerate(payers_ids)]
            participants = rng.sample(ids, rng.randint(1, 8))
            split = rng.choice(list(SplitType))
            if split == SplitType.EXACT:
                base = amount // len(participants)
                values = [base] * len(participants)
                values[-1] += amount - base * len(participants)
                shares = [ShareInput(p, v) for p, v in zip(participants, values)]
            elif split == SplitType.PERCENT:
                pct = [D(100) / len(participants)] * len(participants)
                pct = [p.quantize(D("0.0001")) for p in pct]
                pct[-1] += 100 - sum(pct)
                shares = [ShareInput(p, v) for p, v in zip(participants, pct)]
            elif split == SplitType.SHARES:
                shares = [ShareInput(p, D(rng.randint(1, 5))) for p in participants]
            else:
                shares = [ShareInput(p) for p in participants]
            self.expense(amount_cents=amount, split_type=split, payers=payers, shares=shares)

        transfers = simplify_debts(self.assert_balanced())
        self.assertLessEqual(len(transfers), 7)
        by_pk = {x.pk: x for x in self.u}
        for t in transfers:
            create_settlement(
                group=self.group, actor=by_pk[t.from_user_id], from_user_id=t.from_user_id,
                to_user_id=t.to_user_id, amount_cents=t.amount_cents, date=TODAY,
            )
        self.assertTrue(all(v == 0 for v in group_balances(self.group).values()))

    def test_balances_query_count_is_constant(self):
        for _ in range(5):
            self.expense()
        with self.assertNumQueries(5):
            group_balances(self.group)

    def test_spending_counts_active_expenses_only(self):
        u = [x.pk for x in self.u]
        self.expense()  # u0 paga 1000; u0, u1, u2 deben 334/333/333
        self.expense(
            amount_cents=600,
            category=Category.TRANSPORT,
            payers=[PayerInput(u[1], 400), PayerInput(u[2], 200)],
            shares=[ShareInput(u[0]), ShareInput(u[1])],
        )
        deleted = self.expense(amount_cents=5000, payers=[PayerInput(u[3], 5000)])
        delete_expense(deleted, actor=self.u[0])
        # Una liquidación mueve saldos pero no es gasto.
        create_settlement(
            group=self.group, actor=self.u[1], from_user_id=u[1], to_user_id=u[0],
            amount_cents=200, date=TODAY,
        )

        spending = group_spending(self.group)

        self.assertEqual((spending.total_cents, spending.expense_count), (1600, 2))
        self.assertEqual(set(spending.paid_by_user), set(u))
        self.assertEqual(
            {k: v for k, v in spending.paid_by_user.items() if v},
            {u[0]: 1000, u[1]: 400, u[2]: 200},
        )
        self.assertEqual(
            {k: v for k, v in spending.owed_by_user.items() if v},
            {u[0]: 634, u[1]: 633, u[2]: 333},
        )
        self.assertEqual(spending.by_category, {Category.FOOD: 1000, Category.TRANSPORT: 600})

    def test_update_expense_replaces_rows_and_logs_changes(self):
        u = [x.pk for x in self.u]
        expense = self.expense()
        update_expense(
            expense,
            actor=self.u[1],
            description="Asado del sábado",
            amount_cents=2000,
            date=TODAY,
            category=Category.FOOD,
            split_type=SplitType.SHARES,
            payers=[PayerInput(u[1], 2000)],
            shares=[ShareInput(u[0], D("3")), ShareInput(u[1], D("1"))],
        )
        expense.refresh_from_db()
        self.assertEqual(expense.amount_cents, 2000)
        self.assertEqual(dict(expense.payers.values_list("user_id", "paid_cents")), {u[1]: 2000})
        self.assertEqual(
            {s.user_id: (s.owed_cents, s.input_value) for s in expense.shares.all()},
            {u[0]: (1500, D("3")), u[1]: (500, D("1"))},
        )
        activity = Activity.objects.filter(verb=Activity.Verb.UPDATED).get()
        self.assertEqual(
            set(activity.payload["changes"]), {"description", "amount_cents", "split_type", "payers"}
        )
        self.assertIn("$ 10,00 → $ 20,00", activity.payload["summary"])
        balances = self.assert_balanced()
        self.assertEqual(balances[u[0]], -1500)

    def test_failed_update_keeps_previous_rows(self):
        expense = self.expense()
        with self.assertRaises(ValidationError):
            update_expense(
                expense, actor=self.u[0], description="Asado", amount_cents=1000, date=TODAY,
                category=Category.FOOD, split_type=SplitType.EQUAL,
                payers=[PayerInput(self.u[0].pk, 999)], shares=[ShareInput(self.u[0].pk)],
            )
        self.assertEqual(ExpenseShare.objects.filter(expense=expense).count(), 3)

    def test_update_deleted_expense_rejected(self):
        expense = self.expense()
        delete_expense(expense, actor=self.u[0])
        with self.assertRaises(ValidationError):
            update_expense(
                expense, actor=self.u[0], description="X", amount_cents=1000, date=TODAY,
                category=Category.FOOD, split_type=SplitType.EQUAL,
                payers=[PayerInput(self.u[0].pk, 1000)], shares=[ShareInput(self.u[0].pk)],
            )
        with self.assertRaises(ValidationError):
            delete_expense(expense, actor=self.u[0])

    def test_activity_logged_on_every_write(self):
        def last():
            return Activity.objects.order_by("-id").first()

        self.assertEqual(
            (last().verb, last().target_type), (Activity.Verb.CREATED, Activity.TargetType.GROUP)
        )
        group = create_group(name="Casa", actor=self.u[0], member_ids=[])
        membership = add_member(group, self.u[1], actor=self.u[0])
        self.assertEqual(
            (last().target_type, last().target_id), (Activity.TargetType.MEMBERSHIP, membership.pk)
        )
        expense = self.expense()
        self.assertEqual(
            (last().verb, last().target_id, last().payload["summary"]),
            (Activity.Verb.CREATED, expense.pk, "creó el gasto «Asado» por $ 10,00"),
        )
        update_expense(
            expense, actor=self.u[0], description="Asado", amount_cents=1000, date=TODAY,
            category=Category.FOOD, split_type=SplitType.EQUAL,
            payers=[PayerInput(self.u[0].pk, 1000)], shares=[ShareInput(u.pk) for u in self.u[:3]],
        )
        self.assertEqual((last().verb, last().target_id), (Activity.Verb.UPDATED, expense.pk))
        self.assertEqual(last().payload["changes"], [])
        delete_expense(expense, actor=self.u[0])
        self.assertEqual((last().verb, last().target_id), (Activity.Verb.DELETED, expense.pk))
        settlement = create_settlement(
            group=self.group, actor=self.u[1], from_user_id=self.u[1].pk,
            to_user_id=self.u[0].pk, amount_cents=4000000, date=TODAY,
        )
        self.assertEqual(
            last().payload["summary"], "registró que Amigo2 le pagó $ 40.000,00 a Amigo1"
        )
        delete_settlement(settlement, actor=self.u[1])
        self.assertEqual(
            (last().verb, last().target_type, last().target_id),
            (Activity.Verb.DELETED, Activity.TargetType.SETTLEMENT, settlement.pk),
        )
        self.assertEqual(Activity.objects.count(), 8)
        self.assertTrue(all(a.payload.get("summary") for a in Activity.objects.all()))
