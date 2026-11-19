from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ledger import services
from ledger.models import Membership

User = get_user_model()


class GroupViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ana = User.objects.create_user("ana", password="x")
        cls.beto = User.objects.create_user("beto", password="x")
        cls.caro = User.objects.create_user("caro", password="x")
        cls.inactive = User.objects.create_user("ivan", password="x", is_active=False)
        cls.group_a = services.create_group(name="Viaje", actor=cls.ana, member_ids=[])
        cls.group_b = services.create_group(name="Casa", actor=cls.beto, member_ids=[])

    def setUp(self):
        self.client.force_login(self.ana)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("ledger:group_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_list_shows_only_own_groups(self):
        response = self.client.get(reverse("ledger:group_list"))
        groups = [row["group"] for row in response.context["rows"]]
        self.assertEqual(groups, [self.group_a])

    def test_foreign_group_is_404_on_get_and_post(self):
        for name in ("ledger:group_detail", "ledger:group_members", "ledger:expense_stats"):
            url = reverse(name, args=[self.group_b.pk])
            with self.subTest(view=name):
                self.assertEqual(self.client.get(url).status_code, 404)
                self.assertEqual(
                    self.client.post(url, {"user": self.caro.pk}).status_code, 404
                )
        self.assertFalse(Membership.objects.filter(group=self.group_b, user=self.caro).exists())

    def test_create_group_with_selected_members(self):
        response = self.client.post(
            reverse("ledger:group_create"),
            {"name": "Asado", "members": [self.beto.pk]},
        )
        group = self.ana.expense_groups.get(name="Asado")
        self.assertRedirects(response, reverse("ledger:group_detail", args=[group.pk]))
        self.assertEqual(
            set(group.members.values_list("username", flat=True)), {"ana", "beto"}
        )

    def test_create_group_cannot_pick_inactive_users(self):
        response = self.client.post(
            reverse("ledger:group_create"),
            {"name": "Asado", "members": [self.inactive.pk]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["members"])
        self.assertFalse(self.ana.expense_groups.filter(name="Asado").exists())

    def test_add_member_only_offers_non_members(self):
        url = reverse("ledger:group_members", args=[self.group_a.pk])
        offered = set(self.client.get(url).context["form"].fields["user"].queryset)
        self.assertEqual(offered, {self.beto, self.caro})

        response = self.client.post(url, {"user": self.caro.pk})
        self.assertRedirects(response, url)
        self.assertTrue(Membership.objects.filter(group=self.group_a, user=self.caro).exists())

        # Ya es miembro: no se puede volver a agregar.
        response = self.client.post(url, {"user": self.caro.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Membership.objects.filter(group=self.group_a, user=self.caro).count(), 1
        )
