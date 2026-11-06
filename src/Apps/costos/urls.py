from django.urls import path

from . import views

app_name = "costos"

urlpatterns = [
    path("", views.panel, name="panel"),
    path("configuracion/", views.configuracion, name="configuracion"),
    path("tiempo/iniciar/", views.iniciar_tiempo, name="iniciar_tiempo"),
    path("tiempo/<int:registro_id>/<str:accion>/", views.cambiar_tiempo, name="cambiar_tiempo"),
    path("pedido/<int:pedido_id>/", views.pedido_tiempos, name="pedido_tiempos"),
    path("recepcion/<int:recepcion_id>/gasto/", views.agregar_gasto_recepcion, name="agregar_gasto_recepcion"),
    path("gasto/<int:gasto_id>/eliminar/", views.eliminar_gasto_recepcion, name="eliminar_gasto_recepcion"),
]
