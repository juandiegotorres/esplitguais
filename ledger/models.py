from django.conf import settings
from django.db import models


class Group(models.Model):
    name = models.CharField("nombre", max_length=100)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_groups"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="Membership", related_name="expense_groups"
    )

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "grupo"

    def __str__(self) -> str:
        return self.name


class Membership(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships"
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["group", "user"], name="unique_membership"),
        ]
        verbose_name = "membresía"

    def __str__(self) -> str:
        return f"{self.user} en {self.group}"


class Category(models.TextChoices):
    GENERAL = "general", "General"
    FOOD = "comida", "Comida y bebida"
    GROCERIES = "supermercado", "Supermercado"
    TRANSPORT = "transporte", "Transporte"
    LODGING = "alojamiento", "Alojamiento"
    ENTERTAINMENT = "entretenimiento", "Entretenimiento"
    UTILITIES = "servicios", "Servicios"
    OTHER = "otros", "Otros"


class SplitType(models.TextChoices):
    EQUAL = "equal", "Partes iguales"
    EXACT = "exact", "Importes exactos"
    PERCENT = "percent", "Porcentajes"
    SHARES = "shares", "Partes"


class ExpenseQuerySet(models.QuerySet):
    def active(self):
        return self.filter(deleted_at__isnull=True)


class Expense(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="expenses")
    description = models.CharField("descripción", max_length=200)
    amount_cents = models.BigIntegerField("importe (centavos)")
    date = models.DateField("fecha")
    category = models.CharField(
        "categoría", max_length=30, choices=Category.choices, default=Category.GENERAL
    )
    split_type = models.CharField(
        "reparto", max_length=10, choices=SplitType.choices, default=SplitType.EQUAL
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_expenses"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = ExpenseQuerySet.as_manager()

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "gasto"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_cents__gt=0), name="expense_amount_positive"
            ),
        ]

    def __str__(self) -> str:
        return self.description


class ExpensePayer(models.Model):
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name="payers")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expense_payments"
    )
    paid_cents = models.BigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["expense", "user"], name="unique_expense_payer"),
        ]


class ExpenseShare(models.Model):
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name="shares")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expense_shares"
    )
    owed_cents = models.BigIntegerField()
    # Porcentaje (split percent) o cantidad de partes (split shares); null en equal/exact.
    input_value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["expense", "user"], name="unique_expense_share"),
        ]


class SettlementQuerySet(models.QuerySet):
    def active(self):
        return self.filter(deleted_at__isnull=True)


class Settlement(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="settlements")
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="settlements_paid"
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="settlements_received"
    )
    amount_cents = models.BigIntegerField("importe (centavos)")
    date = models.DateField("fecha")
    note = models.CharField("nota", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_settlements"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SettlementQuerySet.as_manager()

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "liquidación"
        verbose_name_plural = "liquidaciones"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_cents__gt=0), name="settlement_amount_positive"
            ),
            models.CheckConstraint(
                condition=~models.Q(from_user=models.F("to_user")),
                name="settlement_distinct_users",
            ),
        ]


class Activity(models.Model):
    class Verb(models.TextChoices):
        CREATED = "created", "creó"
        UPDATED = "updated", "editó"
        DELETED = "deleted", "borró"

    class TargetType(models.TextChoices):
        GROUP = "group", "grupo"
        MEMBERSHIP = "membership", "miembro"
        EXPENSE = "expense", "gasto"
        SETTLEMENT = "settlement", "liquidación"

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="activities")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="activities"
    )
    verb = models.CharField(max_length=10, choices=Verb.choices)
    target_type = models.CharField(max_length=20, choices=TargetType.choices)
    target_id = models.BigIntegerField()
    # Siempre incluye "summary": texto en castellano listo para mostrar.
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "actividad"
        verbose_name_plural = "actividades"
