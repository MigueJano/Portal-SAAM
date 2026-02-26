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
from django.contrib import messages

from django.conf import settings
from django.utils import timezone

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
    if request.method == 'POST':
        form_cliente = SeleccionarClienteForm(request.POST)
        if form_cliente.is_valid():
            cliente = form_cliente.cleaned_data['cliente']
            print(f"[DEBUG] Cliente seleccionado: {cliente} (ID: {cliente.id})")
            return redirect('seleccionar_productos_cotizacion', cliente_id=cliente.id)
    else:
        form = SeleccionarClienteForm()

    return render(request, './views/cotizacion/crear_cotizacion.html', {'form_cliente': form})


def seleccionar_productos_cotizacion(request, cliente_id):
    """
    Muestra los productos disponibles para el cliente y permite seleccionar.

    Args:
        cliente_id (int): ID del cliente al que se hará la cotización.
    """
    cliente = get_object_or_404(Cliente, id=cliente_id)
    productos = ListaPrecios.objects.filter(nombre_cliente=cliente)

    if request.method == "POST":
        productos_seleccionados = request.POST.getlist("producto_id")
        print(f"[DEBUG] Productos seleccionados: {productos_seleccionados}")

        request.session["productos_seleccionados"] = productos_seleccionados
        request.session["cliente_id"] = cliente.id

        print("[DEBUG] Redirigiendo a vista previa...")
        return redirect("vista_previa_cotizacion")

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
    from Apps.Pedidos.utils_pdf import generar_pdf_cotizacion
    import os

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
        cotizacion = Cotizacion(fecha_cotizacion=timezone.now(), nombre_cliente=cliente)
        cotizacion.save()

        # Generar el PDF
        buffer = generar_pdf_cotizacion(request, cliente, items, cotizacion)

        from django.core.files.base import File
        import os

        nombre_archivo = f"cotizacion_{cotizacion.num_cotizacion}.pdf"
        ruta_relativa = f"cotizaciones_pdfs/{nombre_archivo}"
        ruta_completa = os.path.join(settings.MEDIA_ROOT, ruta_relativa)

        # ✅ ELIMINA SI YA EXISTE
        if os.path.exists(ruta_completa):
            os.remove(ruta_completa)

        # Crea carpeta si no existe
        os.makedirs(os.path.dirname(ruta_completa), exist_ok=True)

        # Guarda el archivo en disco
        with open(ruta_completa, 'wb') as f:
            f.write(buffer.getbuffer())

        # Asigna el archivo al campo archivo_pdf
        with open(ruta_completa, 'rb') as f:
            cotizacion.archivo_pdf.save(nombre_archivo, File(f), save=True)

        pdf_url = settings.MEDIA_URL + ruta_relativa

        return render(request, 'views/cotizacion/vista_previa_pdf.html', {
            'cliente': cliente,
            'pdf_url': pdf_url,
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
    from io import BytesIO

    data = request.session.get("cotizacion_pdf_bytes")
    if not data:
        return redirect("home")

    buffer = BytesIO(bytes.fromhex(data))
    return FileResponse(buffer, as_attachment=True, filename="cotizacion.pdf")


def lista_cotizaciones(request):
    """
    Muestra una lista de todas las cotizaciones generadas.

    Ordena por fecha descendente.
    """
    cotizaciones = Cotizacion.objects.select_related('nombre_cliente').order_by('-fecha_cotizacion')
    return render(request, './views/cotizacion/lista_cotizaciones.html', {
        'cotizaciones': cotizaciones
    })
