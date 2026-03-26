"""
URL configuration for the usuarios app.

Define las rutas relacionadas con autenticación (login y logout)
y utilidades administrativas como la descarga de respaldo de la base de datos.
"""

from django.urls import path
from . import views

urlpatterns = [
    # 🔐 Inicio de sesión
    path('login/', views.login_view, name='login'),

    # 🔐 Cierre de sesión
    path('logout/', views.logout_view, name='logout'),

    # 🗄️ Clonación de BD
    path('base-datos/clonar/', views.clonar_base_datos, name='clonar_base_datos'),

    # 🗄️ Descarga de respaldo de BD
    path('base-datos/', views.base_datos, name='base_datos'),
]
