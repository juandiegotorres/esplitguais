from django.urls import path

from . import views

app_name = "pwa"

urlpatterns = [
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("offline/", views.offline, name="offline"),
    path("instalar/", views.install, name="install"),
    path("notificaciones/suscribir/", views.push_subscribe, name="push_subscribe"),
    path("notificaciones/desuscribir/", views.push_unsubscribe, name="push_unsubscribe"),
]
