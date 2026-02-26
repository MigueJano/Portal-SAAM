"""
apps.py - Configuración de la aplicación 'Pedidos' para el proyecto Django SAAM.

Define metadatos esenciales para la correcta inicialización de la app,
como el nombre de la aplicación y el tipo de campo automático predeterminado.

Fecha de documentación: 2025-08-05
"""

from django.apps import AppConfig


class PedidosConfig(AppConfig):
    """
    Configuración de la app 'Pedidos', que gestiona:
    - Productos
    - Clientes
    - Proveedores
    - Cotizaciones
    - Recepciones
    - Pedidos
    - Stock
    """

    # Tipo de campo automático por defecto para los modelos de esta app
    default_auto_field = 'django.db.models.BigAutoField'

    # Ruta de la app dentro del proyecto
    name = 'Apps.Pedidos'
