"""
utils.py

Este módulo contiene funciones utilitarias generales utilizadas en el sistema SAAM,
incluyendo validaciones (como RUT chileno), renderizado de listas genéricas de modelos,
manejo de logs de auditoría, y una vista genérica para eliminar objetos.

Estas funciones permiten reutilización de lógica común en múltiples vistas y formularios,
facilitando la consistencia y mantenimiento del código.

Funciones principales:
- validar_rut: Valida el RUT chileno según su dígito verificador.
- lista_generica: Renderiza cualquier modelo en una plantilla de lista.
- obtener_logger: Crea un logger reutilizable para registrar acciones como eliminaciones.
- eliminar_generica: Vista para confirmar y eliminar instancias de cualquier modelo.

Autor: Miguel Plasencia
Proyecto: Portal SAAM
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from decimal import Decimal

# --- Funciones utilitarias generales ---

def validar_rut(rut):
    """
    Valida si un RUT chileno es correcto según su dígito verificador.

    Args:
        rut (str): RUT ingresado con o sin puntos y guión.

    Returns:
        bool: True si el RUT es válido, False en caso contrario.
    """
    rut = rut.replace(".", "").replace("-", "").upper()
    if len(rut) < 2:
        return False
    cuerpo, dv = rut[:-1], rut[-1]
    if not cuerpo.isdigit():
        return False
    suma, multiplicador = 0, 2
    for c in reversed(cuerpo):
        suma += int(c) * multiplicador
        multiplicador = 2 if multiplicador == 7 else multiplicador + 1
    dv_calc = 11 - (suma % 11)
    dv_calc = {11: "0", 10: "K"}.get(dv_calc, str(dv_calc))
    return dv == dv_calc

def lista_generica(request, modelo, template, context_name):
    """
    Renderiza una lista genérica de objetos para un modelo determinado.

    Args:
        request (HttpRequest): La solicitud HTTP.
        modelo (Model): El modelo de Django a listar.
        template (str): Ruta al template a usar.
        context_name (str): Nombre del contexto para los objetos.

    Returns:
        HttpResponse: Página renderizada con el listado del modelo.
    """
    context = {context_name: modelo.objects.all()}
    return render(request, template, context)

def obtener_logger():
    """
    Crea o reutiliza un logger para registrar eliminaciones en el sistema.

    Returns:
        logging.Logger: Logger configurado para archivo 'logs/eliminaciones.log'.
    """
    import logging
    import os
    logger = logging.getLogger('eliminaciones')
    if not logger.hasHandlers():
        log_dir = os.path.join('logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'eliminaciones.log')
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.setLevel(logging.INFO)
    return logger

def eliminar_generica(request, modelo, id, redirect_name, template='./views/apps/confirmar_eliminar.html'):
    """
    Vista genérica para confirmar y eliminar instancias de cualquier modelo.

    Esta función:
    - Recupera una instancia del modelo basado en su `id`.
    - Muestra un formulario de confirmación al usuario.
    - Si se confirma por POST, elimina la instancia de forma transaccional.
    - Registra la eliminación en un log (`logs/eliminaciones.log`).
    - Muestra un mensaje de éxito o error y redirige a una vista dada.

    Args:
        request (HttpRequest): La solicitud HTTP del usuario.
        modelo (Model): Clase del modelo de Django (ej. Cliente, Producto).
        id (int): ID de la instancia a eliminar.
        redirect_name (str): Nombre de la vista a redirigir después.
        template (str): Template HTML para mostrar la confirmación (opcional).

    Returns:
        HttpResponse: Página de confirmación o redirección con mensaje.
    """
    # Obtiene la instancia del modelo o lanza 404 si no existe
    instancia = get_object_or_404(modelo, pk=id)
    
    # Obtiene logger para registrar acciones
    logger = obtener_logger()

    # Si el usuario confirma la eliminación vía POST
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Extrae todos los campos y valores de la instancia como texto
                datos_eliminados = {
                    f.name: str(getattr(instancia, f.name)) if not isinstance(getattr(instancia, f.name), Decimal)
                    else f"{getattr(instancia, f.name):.2f}"
                    for f in modelo._meta.fields
                }

                # Registra los datos en el log
                logger.info(f"Eliminación de {modelo.__name__} ID={id}: {datos_eliminados}")

                # Elimina la instancia de forma segura
                instancia.delete()

            # Muestra mensaje de éxito al usuario
            messages.success(request, f"{modelo.__name__} eliminado correctamente.")
            return redirect(redirect_name)

        except Exception as e:
            # Registra error y muestra mensaje si algo falla
            logger.error(f"Error al eliminar {modelo.__name__} ID={id}: {e}")
            messages.error(request, f"No se pudo eliminar: {e}")
            return redirect(redirect_name)

    # Si es GET, prepara los campos a mostrar en la página de confirmación
    campos = [
        {
            'nombre': f.verbose_name.title() if f.verbose_name else f.name,
            'valor': getattr(instancia, f.name, '')
        }
        for f in modelo._meta.fields
    ]

    # Contexto para renderizar el template de confirmación
    contexto = {
        'modelo': modelo.__name__,
        'campos': campos,
        modelo.__name__.lower(): instancia
    }

    return render(request, template, contexto)
