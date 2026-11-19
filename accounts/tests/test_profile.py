from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile
from ledger import services
from ledger.models import Category, SplitType
from ledger.services import PayerInput, ShareInput

User = get_user_model()


class ProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("juan", password="x", first_name="Juan")
        self.client.force_login(self.user)

    def save(self, alias="", first_name="Juan"):
        return self.client.post(reverse("profile"), {"first_name": first_name, "alias": alias})

    def save_alias(self, alias):
        return self.save(alias=alias)

    def test_accepts_bcra_alias_and_trims_spaces(self):
        for alias in ["abc.de", "JUAN.PEREZ-MP", "a" * 20, "  juan.perez.mp  "]:
            with self.subTest(alias=alias):
                self.assertRedirects(self.save_alias(alias), reverse("profile"))
                self.assertEqual(Profile.objects.get(user=self.user).alias, alias.strip())

    def test_rejects_invalid_alias_and_keeps_previous(self):
        self.save_alias("juan.perez.mp")
        for alias in ["abcde", "a" * 21, "peña.mp", "juan perez", "café.mp", "juan_perez"]:
            with self.subTest(alias=alias):
                response = self.save_alias(alias)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["alias_form"].errors["alias"])
                self.assertEqual(Profile.objects.get(user=self.user).alias, "juan.perez.mp")

    def test_empty_alias_removes_it(self):
        self.save_alias("juan.perez.mp")
        self.assertRedirects(self.save_alias(""), reverse("profile"))
        self.assertEqual(Profile.objects.get(user=self.user).alias, "")

    def test_name_is_saved_and_shown_to_the_group(self):
        self.assertRedirects(self.save(first_name="  Juancito  "), reverse("profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Juancito")
        group = services.create_group(name="Casa", actor=self.user, member_ids=[])
        response = self.client.get(reverse("ledger:balances", args=[group.pk]))
        self.assertEqual(response.context["rows"][0]["name"], "Juancito")

    def test_invalid_alias_does_not_save_name_either(self):
        response = self.save(alias="mal", first_name="Otro")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["name_form"]["first_name"].value(), "Otro")
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Juan")


class AliasInPaymentsTests(TestCase):
    """El alias de quien recibe aparece solo a quien le debe; nunca el de alguien ajeno."""

    @classmethod
    def setUpTestData(cls):
        cls.ana = User.objects.create_user("ana", password="x", first_name="Ana")
        cls.beto = User.objects.create_user("beto", password="x", first_name="Beto")
        cls.ajeno = User.objects.create_user("ajeno", password="x")
        Profile.objects.create(user=cls.ana, alias="ana.cobra.mp")
        Profile.objects.create(user=cls.ajeno, alias="ajeno.secreto")
        cls.group = services.create_group(
            name="Casa", actor=cls.ana, member_ids=[cls.beto.pk]
        )
        services.create_expense(
            group=cls.group,
            actor=cls.ana,
            description="Luz",
            amount_cents=10_000,
            date=date(2026, 11, 1),
            category=Category.GENERAL,
            split_type=SplitType.EQUAL,
            payers=[PayerInput(cls.ana.pk, 10_000)],
            shares=[ShareInput(cls.ana.pk), ShareInput(cls.beto.pk)],
        )

    def setUp(self):
        self.client.force_login(self.beto)

    def test_balances_shows_creditor_alias_with_copy_button(self):
        response = self.client.get(reverse("ledger:balances", args=[self.group.pk]))
        transfer = response.context["my_transfers"][0]
        self.assertTrue(transfer["i_pay"])
        self.assertEqual(transfer["to_alias"], "ana.cobra.mp")
        self.assertContains(response, 'data-copy="ana.cobra.mp"')
        self.assertNotContains(response, "ajeno.secreto")

    def test_creditor_does_not_see_her_own_alias_to_copy(self):
        self.client.force_login(self.ana)
        response = self.client.get(reverse("ledger:balances", args=[self.group.pk]))
        transfer = response.context["my_transfers"][0]
        self.assertFalse(transfer["i_pay"])
        self.assertNotIn("to_alias", transfer)
        self.assertNotContains(response, 'data-copy="ana.cobra.mp"')

    def test_settlement_form_only_exposes_member_aliases(self):
        response = self.client.get(reverse("ledger:settlement_create", args=[self.group.pk]))
        self.assertEqual(response.context["aliases"], {str(self.ana.pk): "ana.cobra.mp"})
        self.assertNotContains(response, "ajeno.secreto")

    def test_creditor_without_alias_is_prompted_to_add_one(self):
        Profile.objects.filter(user=self.ana).update(alias="")
        self.client.force_login(self.ana)
        response = self.client.get(reverse("ledger:balances", args=[self.group.pk]))
        self.assertTrue(response.context["suggest_alias"])
        self.assertContains(response, reverse("profile"))
