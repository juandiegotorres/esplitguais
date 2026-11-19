from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

# Reglas del BCRA para el alias de CBU/CVU: 6 a 20 caracteres; letras sin ñ, números, punto y guion.
alias_validator = RegexValidator(
    r"^[A-Za-z0-9.-]{6,20}$",
    "El alias tiene de 6 a 20 caracteres: letras (sin ñ ni tildes), números, punto o guion.",
)


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    alias = models.CharField(
        "alias para transferencias", max_length=20, blank=True, validators=[alias_validator]
    )

    class Meta:
        verbose_name = "perfil"

    def __str__(self) -> str:
        return f"Perfil de {self.user}"


def aliases_for(user_ids) -> dict[int, str]:
    """user_id → alias, solo para quienes cargaron uno."""
    return dict(
        Profile.objects.filter(user_id__in=list(user_ids))
        .exclude(alias="")
        .values_list("user_id", "alias")
    )
