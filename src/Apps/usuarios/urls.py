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
]
