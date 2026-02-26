"""
Inicializador del paquete de vistas.

Importa todos los módulos de vistas organizados por dominio funcional:
- Proveedores
- Contactos
- Productos
- Clientes
- Cotizaciones
- Pedidos
- Ventas
"""
from .cliente import *
from .contacto import *
from .cotizacion import *
from .dashboard import *
from .listaprecios import *
from .pedido import *
from .producto import *
from .proveedor import *
from .recepcion import *
from .venta import *
from .views_ajax import *