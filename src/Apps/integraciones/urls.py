from django.urls import path

from . import views

app_name = "integraciones"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("correo/", views.correo, name="correo"),
    path("correo/redactar/", views.redactar_correo, name="redactar_correo"),
    path("documentos/", views.documentos_tributarios, name="documentos_tributarios"),
    path("banco/", views.conciliacion_bancaria, name="conciliacion_bancaria"),
    path("banco/sincronizar/", views.sincronizar_banco, name="sincronizar_banco"),
    path("banco/<int:movimiento_id>/proponer/", views.proponer_movimiento, name="proponer_movimiento"),
    path("banco/<int:movimiento_id>/asignar/", views.crear_conciliacion_manual, name="crear_conciliacion_manual"),
    path("banco/conciliacion/<int:conciliacion_id>/confirmar/", views.confirmar, name="confirmar"),
]

