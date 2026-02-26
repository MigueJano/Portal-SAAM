# Apps/indicadores/urls.py
from django.urls import path
from .views.financieros import dashboard_financiero_simple
from .views.ventas import dashboard_ventas

urlpatterns = [
    path('financiero-simple/', dashboard_financiero_simple, name='dashboard_financiero_simple'),
    path('ventas/', dashboard_ventas, name='dashboard_ventas'),
]
