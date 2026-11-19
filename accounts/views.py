from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render

from .forms import NameForm, ProfileForm
from .models import Profile


@login_required
def profile(request):
    instance, _ = Profile.objects.get_or_create(user=request.user)
    data = request.POST or None
    name_form = NameForm(data, instance=request.user)
    alias_form = ProfileForm(data, instance=instance)
    # Evaluar ambos para mostrar todos los errores de una vez.
    if request.method == "POST" and all([name_form.is_valid(), alias_form.is_valid()]):
        with transaction.atomic():
            name_form.save()
            alias_form.save()
        messages.success(request, "Guardamos tus datos.")
        return redirect("profile")
    return render(
        request, "accounts/profile.html", {"name_form": name_form, "alias_form": alias_form}
    )
