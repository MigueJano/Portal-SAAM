"""
Utilidades compartidas de la app Pedidos.

Incluye:
- validacion de RUT chileno
- render de listas genericas
- logger de eliminaciones
- flujo generico de eliminacion con doble confirmacion
"""

from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render


DELETE_CONFIRMATION_TEXT = "ELIMINAR"


def validacion_doble_check_eliminacion(request):
    """
    Valida el doble check requerido para cualquier eliminacion.
    """
    confirmacion_marcada = request.POST.get("confirmar_eliminacion") == "on"
    texto_confirmacion = (request.POST.get("texto_confirmacion") or "").strip().upper()
    return confirmacion_marcada and texto_confirmacion == DELETE_CONFIRMATION_TEXT


def validar_rut(rut):
    """
    Valida si un RUT chileno es correcto segun su digito verificador.
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
    Renderiza una lista generica de objetos para un modelo dado.
    """
    context = {context_name: modelo.objects.all()}
    return render(request, template, context)


def obtener_logger():
    """
    Crea o reutiliza un logger para registrar eliminaciones.
    """
    import logging
    import os

    logger = logging.getLogger("eliminaciones")
    if not logger.hasHandlers():
        log_dir = os.path.join("logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "eliminaciones.log")
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.setLevel(logging.INFO)
    return logger


def eliminar_generica(request, modelo, id, redirect_name, template="./views/apps/confirmar_eliminar.html"):
    """
    Vista generica para confirmar y eliminar instancias de cualquier modelo.
    """
    instancia = get_object_or_404(modelo, pk=id)
    logger = obtener_logger()

    campos = [
        {
            "nombre": f.verbose_name.title() if f.verbose_name else f.name,
            "valor": getattr(instancia, f.name, ""),
        }
        for f in modelo._meta.fields
    ]
    contexto = {
        "modelo": modelo.__name__,
        "campos": campos,
        "texto_confirmacion_requerido": DELETE_CONFIRMATION_TEXT,
        modelo.__name__.lower(): instancia,
    }

    if request.method == "POST":
        if not validacion_doble_check_eliminacion(request):
            messages.error(
                request,
                f"Debes marcar la confirmacion y escribir {DELETE_CONFIRMATION_TEXT} para eliminar.",
            )
            return render(request, template, contexto)

        try:
            with transaction.atomic():
                datos_eliminados = {
                    f.name: str(getattr(instancia, f.name))
                    if not isinstance(getattr(instancia, f.name), Decimal)
                    else f"{getattr(instancia, f.name):.2f}"
                    for f in modelo._meta.fields
                }
                logger.info(f"Eliminacion de {modelo.__name__} ID={id}: {datos_eliminados}")
                instancia.delete()

            messages.success(request, f"{modelo.__name__} eliminado correctamente.")
            return redirect(redirect_name)
        except Exception as e:
            logger.error(f"Error al eliminar {modelo.__name__} ID={id}: {e}")
            messages.error(request, f"No se pudo eliminar: {e}")
            return redirect(redirect_name)

    return render(request, template, contexto)
