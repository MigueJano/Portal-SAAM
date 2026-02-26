"""
Cotizaciones - Módulo de vistas para gestionar cotizaciones.

Incluye:
- Selección de cliente y productos.
- Generación y vista previa de PDF.
- Listado histórico de cotizaciones.
- Descarga de cotizaciones generadas.

Fecha de documentación: 2025-08-04
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.http import FileResponse
from django.utils import timezone
from django.core.files.base import ContentFile

from Apps.Pedidos.forms import SeleccionarClienteForm
from Apps.Pedidos.models import Cliente, ListaPrecios, Cotizacion

# --- Decimal helpers ---
from decimal import Decimal, ROUND_HALF_UP
DOS_DEC = Decimal('0.01')


def seleccionar_cliente_cotizacion(request):
    """
    Paso inicial para crear una cotización: seleccionar cliente.

    Redirige a la vista de selección de productos.
    """
    form_cliente = SeleccionarClienteForm(request.POST or None)
    if request.method == 'POST' and form_cliente.is_valid():
        cliente = form_cliente.cleaned_data['cliente']
        return redirect('seleccionar_productos_cotizacion', cliente_id=cliente.id)

    return render(request, './views/cotizacion/crear_cotizacion.html', {'form_cliente': form_cliente})


def seleccionar_productos_cotizacion(request, cliente_id):
    """
    Muestra los productos disponibles para el cliente y permite seleccionar.

    Args:
        cliente_id (int): ID del cliente al que se hará la cotización.
    """
    cliente = get_object_or_404(Cliente, id=cliente_id)
    productos = ListaPrecios.objects.filter(nombre_cliente=cliente)

    return render(request, "./views/cotizacion/seleccionar_productos.html", {
        "cliente": cliente,
        "productos": productos,
    })


def vista_previa_cotizacion(request):
    """
    Genera una cotización en PDF en base al cliente y productos seleccionados.

    Crea una instancia de Cotización, genera PDF, lo guarda en disco y lo vincula.

    Retorna:
        vista_previa_pdf.html con el enlace al PDF generado
    """
    if request.method == "POST":
        cliente_id = request.POST.get('cliente_id')
        productos_ids = request.POST.getlist('producto_id')

        if not cliente_id or not productos_ids:
            return render(request, 'views/cotizacion/error.html', {
                'mensaje': 'Faltan datos para generar la cotización.'
            })

        cliente = get_object_or_404(Cliente, id=cliente_id)
        precios = ListaPrecios.objects.filter(
            nombre_cliente=cliente,
            id__in=productos_ids
        ).select_related(
            'nombre_producto',
            'nombre_producto__empaque_primario',
            'nombre_producto__empaque_secundario',
            'nombre_producto__empaque_terciario'
        )

        # Armado de ítems con nombres de empaques según nivel
        items = []
        for precio in precios:
            producto = precio.nombre_producto
            nivel_empaque = precio.empaque
            if nivel_empaque == 'PRIMARIO' and producto.empaque_primario:
                nombre_empaque = producto.empaque_primario.nombre
            elif nivel_empaque == 'SECUNDARIO' and producto.empaque_secundario:
                nombre_empaque = producto.empaque_secundario.nombre
            elif nivel_empaque == 'TERCIARIO' and producto.empaque_terciario:
                nombre_empaque = producto.empaque_terciario.nombre
            else:
                nombre_empaque = nivel_empaque

            items.append({
                'producto': producto,
                'producto_nombre': producto.nombre_producto,
                'cantidad': 1,
                'empaque': nombre_empaque,
                # Mantén Decimal y 2 decimales con HALF_UP
                'precio_unitario': Decimal(precio.precio_venta).quantize(DOS_DEC, rounding=ROUND_HALF_UP),
            })

        # Crear la instancia de Cotización
        cotizacion = Cotizacion(fecha_cotizacion=timezone.localdate(), nombre_cliente=cliente)
        cotizacion.save()

        # Generar el PDF
        try:
            from Apps.Pedidos.utils_pdf import generar_pdf_cotizacion
            buffer = generar_pdf_cotizacion(request, cliente, items, cotizacion)
        except Exception as e:
            cotizacion.delete()
            return render(request, 'views/cotizacion/error.html', {
                'mensaje': f'No se pudo generar el PDF en este entorno: {e}'
            })

        nombre_archivo = f"cotizacion_{cotizacion.num_cotizacion}.pdf"
        cotizacion.archivo_pdf.save(nombre_archivo, ContentFile(buffer.getvalue()), save=True)
        request.session["ultima_cotizacion_id"] = cotizacion.id

        return render(request, 'views/cotizacion/vista_previa_pdf.html', {
            'cliente': cliente,
            'pdf_url': cotizacion.archivo_pdf.url,
            'cotizacion': cotizacion,
        })

    return render(request, 'views/cotizacion/error.html', {
        'mensaje': 'No se enviaron datos.'
    })


def descargar_cotizacion_pdf(request):
    """
    Permite descargar la última cotización generada, guardada en sesión.

    Retorna:
        FileResponse con el PDF (hexadecimal desde sesión).
    """
    cotizacion_id = request.GET.get("id") or request.session.get("ultima_cotizacion_id")
    if not cotizacion_id:
        return redirect("lista_cotizaciones")

    cotizacion = get_object_or_404(Cotizacion, id=cotizacion_id)
    if not cotizacion.archivo_pdf:
        return redirect("lista_cotizaciones")

    return FileResponse(
        cotizacion.archivo_pdf.open("rb"),
        as_attachment=True,
        filename=f"cotizacion_{cotizacion.num_cotizacion}.pdf"
    )


def lista_cotizaciones(request):
    """
    Muestra una lista de todas las cotizaciones generadas.

    Ordena por fecha descendente.
    """
    cotizaciones = Cotizacion.objects.select_related('nombre_cliente').order_by('-fecha_cotizacion')
    return render(request, './views/cotizacion/lista_cotizaciones.html', {
        'cotizaciones': cotizaciones
    })
