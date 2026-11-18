from django.contrib.auth import views as auth_views
from django.urls import path

from .forms import LoginForm

urlpatterns = [
    path(
        "entrar/",
        auth_views.LoginView.as_view(authentication_form=LoginForm, redirect_authenticated_user=True),
        name="login",
    ),
    path("salir/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "contrasena/",
        auth_views.PasswordChangeView.as_view(),
        name="password_change",
    ),
    path(
        "contrasena/listo/",
        auth_views.PasswordChangeDoneView.as_view(),
        name="password_change_done",
    ),
]
