from django.urls import path

from . import views


urlpatterns = [
    path("actas/", views.lista_actas, name="lista_actas"),
    path("actas/nueva/", views.crear_acta, name="crear_acta"),
    path("actas/<int:pk>/", views.detalle_acta, name="detalle_acta"),
    path("actas/<int:pk>/editar/", views.editar_acta, name="editar_acta"),
]
