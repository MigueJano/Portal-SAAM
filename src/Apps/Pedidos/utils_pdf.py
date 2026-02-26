"""
utils_pdf.py

Este módulo contiene funciones para generar archivos PDF de pedidos y cotizaciones
utilizando la biblioteca ReportLab. Incluye utilidades para formatear números,
diseñar encabezados con logotipo, y estructurar las tablas de productos y totales
para un aspecto profesional.

Autores: SAAM
Última actualización: 2025-08-05
"""

from io import BytesIO
from decimal import Decimal, ROUND_HALF_UP

from django.http import HttpResponse
from django.utils import timezone
from django.contrib.staticfiles import finders

from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen.canvas import Canvas

# --- Constantes Decimal ---
DOS_DEC = Decimal('0.01')
PESO    = Decimal('1')      # redondeo a peso
IVA    = Decimal('0.19')
FONTSIZE_HEADER = 9
FONTSIZE_BODY   = 9

# --------------------------
# Helpers numéricos seguros
# --------------------------
def _to_decimal(x):
    """Convierte a Decimal sin errores binarios si viene float."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(str(x))
    return Decimal(x or 0)

def formatear_miles_punto(num):
    """
    Formatea un número usando punto como separador de miles.
    """
    num = Decimal(num)
    return f"{num:,.0f}".replace(",", ".")

# --------------------------
# Footer / Pie de página
# --------------------------
def pie_de_contacto(canvas: Canvas, doc):
    """Línea de contacto centrada al pie."""
    canvas.saveState()
    canvas.setFont("Helvetica", 9)
    texto = "Teléfono: +56 9 5081 7567   |   Correo: saamspa25@gmail.com"
    width = canvas.stringWidth(texto, "Helvetica", 9)
    x = (doc.pagesize[0] - width) / 2
    canvas.drawString(x, 20, texto)
    canvas.restoreState()

def pie_de_pagina_factory(comentario: str):
    """
    Crea un callback para dibujar el comentario del pedido al fondo (sobre el pie)
    y luego el pie de contacto. Se ejecuta en cada página.
    """
    styles = getSampleStyleSheet()
    estilo_coment = ParagraphStyle(
        name='FooterComment',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#666666')
    )

    def on_page(canvas: Canvas, doc):
        canvas.saveState()
        # Área disponible entre márgenes
        page_w = doc.pagesize[0]
        left   = doc.leftMargin
        right  = doc.rightMargin
        width  = page_w - left - right

        # Comentario (si existe)
        if comentario:
            p = Paragraph(f"<b>Comentarios del pedido:</b> {comentario}", estilo_coment)
            # Alto máx. ~3 líneas
            w, h = p.wrap(width, 40)
            # Lo dibujamos sobre el pie de contacto (y=35 aprox)
            p.drawOn(canvas, left, 35 + 12)  # un poquito más arriba del contacto

        canvas.restoreState()
        # Finalmente, el pie de contacto (centrado)
        pie_de_contacto(canvas, doc)

    return on_page

# --------------------------
# PDF Pedido
# --------------------------
def generar_pdf_pedido(pedido, reservas):
    """
    Genera un archivo PDF con el detalle de un pedido y sus productos reservados.
    """
    buffer = BytesIO()
    doc_title = f"Pedido {pedido.id} - {pedido.nombre_cliente}"
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=80,
        bottomMargin=60,
        title=doc_title
    )
    elements = []
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='RightTitle', alignment=2, fontSize=16, leading=20, spaceAfter=5))

    # Encabezado con logo y título
    logo_path = finders.find('img/logo.jpg')
    if logo_path:
        logo = Image(logo_path, width=160, height=50)
        titulo = Paragraph(f"<b>PEDIDO</b><br/><b>N° {pedido.id}</b>", styles['RightTitle'])
        header_table = Table([[logo, titulo]], colWidths=[100, 400])
        header_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
        elements.append(header_table)

    elements.append(Spacer(1, 20))

    # Tabla de datos del pedido
    datos = [
        ["Cliente:", f"{pedido.nombre_cliente}"],
        ["Fecha:", timezone.now().strftime('%d-%m-%Y')],
        ["Vigencia:", "15 días"],
    ]
    tabla_datos = Table(datos, colWidths=[80, 350], hAlign='LEFT')
    tabla_datos.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (1, 0), (0, 0), 'LEFT'),
        ('INNERGRID', (0, 0), (-1, -1), 0, colors.white),
        ('BOX', (0, 0), (-1, -1), 0, colors.white),
    ]))
    elements.append(tabla_datos)
    elements.append(Spacer(1, 10))

    # Comentarios antes de la tabla de productos
    comentario = (getattr(pedido, 'comentario_pedido', '') or '').strip()
    if comentario:
        elements.append(Paragraph("<b>Comentarios</b>", ParagraphStyle('ComentariosTitulo',parent=styles['Normal'],leftIndent=5)))
        comentario_para = Paragraph(comentario.replace('\n', '<br/>'), styles['Normal'])
        comentario_box = Table([[comentario_para]], colWidths=[17.5*cm], hAlign='LEFT')
        comentario_box.setStyle(TableStyle([
            ('PADDING', (20, 0), (-1, -1), 6),
        ]))
        elements.append(comentario_box)
        elements.append(Spacer(1, 12))


    # --- Tabla de productos (agregando "Total c/ IVA") ---
    data = [["Producto", "Cantidad", "Empaque", "Precio Neto", "Precio c/IVA","Subtotal"]]
    total_neto = Decimal('0')

    for r in reservas:
        qty     = _to_decimal(r.qty)
        precio  = _to_decimal(r.precio_unitario)
        subtotal = qty * precio
        total_neto += subtotal

        # Nombre de empaque normalizado
        nombre_empaque = (
            r.producto.empaque_primario.nombre   if r.empaque == 'PRIMARIO'   and r.producto.empaque_primario   else
            r.producto.empaque_secundario.nombre if r.empaque == 'SECUNDARIO' and r.producto.empaque_secundario else
            r.producto.empaque_terciario.nombre  if r.empaque == 'TERCIARIO'  and r.producto.empaque_terciario  else
            r.empaque
        )

        # Precio IVA por línea (redondeado a peso)
        # Nota: IVA es un Decimal tipo Decimal('0.19')
        precio_iva = (precio * (Decimal('1') + IVA)).quantize(PESO, rounding=ROUND_HALF_UP)

        data.append([
            r.producto.nombre_producto[:30],
            f"{int(qty)}",
            nombre_empaque,
            f"${formatear_miles_punto(precio)}",
            f"${formatear_miles_punto(precio_iva)}",
            f"${formatear_miles_punto(subtotal)}",
        ])

    # Ajusta anchos de columna: agregamos 1 columna más
    table = Table(
        data,
        colWidths=[8*cm, 1.8*cm, 2*cm, 2.2*cm, 2.2*cm, 2.3*cm]  # total ≈ 18 cm
    )
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR',  (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, 0), FONTSIZE_HEADER),   # 🔹 tamaño para encabezados
        ('FONTSIZE',   (0, 1), (-1, -1), FONTSIZE_BODY),   # 🔹 tamaño para filas
        ('ALIGN',      (0, 0), (-1, 0), 'CENTER'),   # 🔹 títulos de columnas centrados
        ('ALIGN',      (0, 1), (0, -1), 'LEFT'),     # Producto
        ('ALIGN',      (1, 1), (-1, -1), 'CENTER'),  # Cantidad, Empaque
        ('ALIGN',      (3, 1), (-1, -1), 'RIGHT'),   # Precio, Subtotal, Total c/IVA
        ('GRID',       (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 15))


    # Totales (IVA redondeado a peso)
    total_neto = total_neto.quantize(DOS_DEC, rounding=ROUND_HALF_UP)
    iva   = (total_neto * IVA).quantize(PESO, rounding=ROUND_HALF_UP)   # usa IVA definido arriba
    total = (total_neto + iva).quantize(PESO, rounding=ROUND_HALF_UP)

    tabla_totales = Table([
        ["Total Neto:", f"${formatear_miles_punto(total_neto)}"],
        ["IVA (19%):", f"${formatear_miles_punto(iva)}"],
        ["Total:",     f"${formatear_miles_punto(total)}"]
    ], colWidths=[15.5*cm, 2.4*cm], hAlign='RIGHT')
    tabla_totales.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('LINEABOVE', (0, 2), (-1, 2), 1, colors.black),
    ]))
    elements.append(tabla_totales)

    # Solo pie de contacto (los comentarios ya van arriba)
    doc.build(elements, onFirstPage=pie_de_contacto, onLaterPages=pie_de_contacto)

    buffer.seek(0)
    return HttpResponse(buffer, content_type='application/pdf')

# --------------------------
# PDF Cotización
# --------------------------
def generar_pdf_cotizacion(request, cliente, items, cotizacion):
    """
    Genera un PDF con el detalle de una cotización para un cliente específico.

    Returns:
        BytesIO: Archivo PDF en memoria.
    """
    buffer = BytesIO()
    doc_title = f"Cotización - {cliente.nombre_cliente} - {timezone.now().strftime('%d-%m-%Y')}"
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=80,
        bottomMargin=60,
        title=doc_title
    )
    elements = []
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='RightTitle', alignment=2, fontSize=16, leading=20, spaceAfter=5))

    logo_path = finders.find('img/logo.jpg')
    if logo_path:
        logo = Image(logo_path, width=160, height=50)
        titulo = Paragraph(f"<b>COTIZACIÓN</b><br/><b>N° {cotizacion.num_cotizacion}</b>", styles['RightTitle'])
        header_table = Table([[logo, titulo]], colWidths=[100, 400])
        header_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
        elements.append(header_table)

    elements.append(Spacer(1, 20))

    datos = [
        ["Cliente:", cliente.nombre_cliente],
        ["Fecha:", timezone.now().strftime('%d-%m-%Y')],
        ["Vigencia:", "15 días"],
    ]

    tabla_datos = Table(datos, colWidths=[80, 350], hAlign='LEFT')
    tabla_datos.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (1, 0), (0, 0), 'LEFT'),
        ('INNERGRID', (0, 0), (-1, -1), 0, colors.white),
        ('BOX', (0, 0), (-1, -1), 0, colors.white),
    ]))
    elements.append(tabla_datos)
    elements.append(Spacer(1, 10))

    # Tabla de productos cotizados
    data = [["Producto", "Empaque", "Precio Neto", "IVA (19%)", "Precio Total"]]
    for item in items:
        precio_neto = _to_decimal(item['precio_unitario'])
        iva_item    = (precio_neto * IVA).quantize(PESO, rounding=ROUND_HALF_UP)
        precio_total = (precio_neto + iva_item).quantize(PESO, rounding=ROUND_HALF_UP)

        producto = item['producto']
        empaque_valor = item['empaque']
        empaque_nombre = (
            producto.empaque_primario.nombre  if empaque_valor == 'PRIMARIO'  and producto.empaque_primario  else
            producto.empaque_secundario.nombre if empaque_valor == 'SECUNDARIO' and producto.empaque_secundario else
            producto.empaque_terciario.nombre if empaque_valor == 'TERCIARIO' and producto.empaque_terciario else
            empaque_valor
        )

        data.append([
            item['producto_nombre'],
            empaque_nombre,
            f"${formatear_miles_punto(precio_neto)}",
            f"${formatear_miles_punto(iva_item)}",
            f"${formatear_miles_punto(precio_total)}"
        ])

    table = Table(data, colWidths=[9.2*cm, 2.2*cm, 2.2*cm, 2.2*cm, 2.2*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, 0), FONTSIZE_HEADER),   # 🔹 tamaño para encabezados
        ('FONTSIZE',   (0, 1), (-1, -1), FONTSIZE_BODY),   # 🔹 tamaño para fila
        ('ALIGN',      (0, 0), (-1, 0), 'CENTER'),   # 🔹 títulos de columnas centrados
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 30))

    # Pie estándar de contacto para cotización
    doc.build(elements, onFirstPage=pie_de_contacto, onLaterPages=pie_de_contacto)
    buffer.seek(0)
    return buffer

# --------------------------
# PDF Recepción
# --------------------------

def generar_pdf_entrega(pedido, reservas, receptor, firma_bytes=None):
    """
    Genera un PDF de Recepción de Pedido con el mismo estilo del PDF de pedido:
    - Encabezado con logo y título "RECEPCIÓN PEDIDO N° <pedido.id>"
    - Tabla de productos (como en pedido) y totales (Neto, IVA, Total)
    - Bloque final con datos del receptor (Nombre, RUT, Fecha/Hora) y firma

    Args:
        pedido: instancia Pedido
        reservas: QuerySet/iterable de Stock asociados al pedido
        receptor: dict {'nombre': str, 'rut': str, 'fecha': datetime, 'comentario': str|''}
        firma_bytes: bytes PNG de la firma (opcional)

    Returns:
        bytes del PDF
    """
    buf = BytesIO()

    doc_title = f"Recepción Pedido {pedido.id} - {pedido.nombre_cliente}"
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=40, leftMargin=40,
        topMargin=80, bottomMargin=60,
        title=doc_title
    )
    elements = []
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='RightTitle', alignment=2, fontSize=16, leading=20, spaceAfter=5))

    # --- Encabezado (logo + título a la derecha) ---
    logo_path = finders.find('img/logo.jpg')
    titulo = Paragraph(f"<b>RECEPCIÓN PEDIDO</b><br/><b>N° {pedido.id}</b>", styles['RightTitle'])
    if logo_path:
        logo = Image(logo_path, width=160, height=50)
        header_table = Table([[logo, titulo]], colWidths=[100, 400])
    else:
        header_table = Table([[Paragraph("", styles['Normal']), titulo]], colWidths=[100, 400])

    header_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
    elements.append(header_table)
    elements.append(Spacer(1, 20))

    # --- Datos del pedido (mismo bloque que en pedido) ---
    datos = [
        ["Cliente:", f"{pedido.nombre_cliente}"],
        ["Fecha:", timezone.now().strftime('%d-%m-%Y')],
        ["Vigencia:", "—"],  # en recepción ya no aplica "15 días", puedes dejar "—"
    ]
    tabla_datos = Table(datos, colWidths=[80, 350], hAlign='LEFT')
    tabla_datos.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (1, 0), (0, 0), 'LEFT'),
        ('INNERGRID', (0, 0), (-1, -1), 0, colors.white),
        ('BOX', (0, 0), (-1, -1), 0, colors.white),
    ]))
    elements.append(tabla_datos)
    elements.append(Spacer(1, 10))

    # --- Comentario (si viene) ---
    comentario = (receptor.get('comentario') or '').strip()
    if comentario:
        elements.append(Paragraph("<b>Comentarios</b>", ParagraphStyle(
            'ComentariosTitulo', parent=styles['Normal'], leftIndent=5)))
        comentario_para = Paragraph(comentario.replace('\n', '<br/>'), styles['Normal'])
        comentario_box = Table([[comentario_para]], colWidths=[17.5*cm], hAlign='LEFT')
        comentario_box.setStyle(TableStyle([('PADDING', (20, 0), (-1, -1), 6)]))
        elements.append(comentario_box)
        elements.append(Spacer(1, 12))

    # --- Tabla de productos (idéntica estructura a generar_pdf_pedido) ---
    data = [["Producto", "Cantidad", "Empaque", "Precio Unitario", "Subtotal"]]
    total_neto = Decimal('0')

    for r in reservas:
        qty = _to_decimal(getattr(r, 'qty', 0))
        precio = _to_decimal(getattr(r, 'precio_unitario', 0))
        subtotal = qty * precio
        total_neto += subtotal

        nombre_empaque = (
            r.producto.empaque_primario.nombre   if r.empaque == 'PRIMARIO'   and r.producto.empaque_primario   else
            r.producto.empaque_secundario.nombre if r.empaque == 'SECUNDARIO' and r.producto.empaque_secundario else
            r.producto.empaque_terciario.nombre  if r.empaque == 'TERCIARIO'  and r.producto.empaque_terciario  else
            r.empaque
        )

        data.append([
            r.producto.nombre_producto[:30],
            f"{int(qty)}",
            nombre_empaque,
            f"${formatear_miles_punto(precio)}",
            f"${formatear_miles_punto(subtotal)}"
        ])

    table = Table(data, colWidths=[8*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.5*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR',  (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, 0), FONTSIZE_HEADER),   # 🔹 tamaño para encabezados
        ('FONTSIZE',   (0, 1), (-1, -1), FONTSIZE_BODY),
        ('ALIGN',      (0, 0), (-1, 0), 'CENTER'),   # 🔹 títulos de columnas centrados
        ('ALIGN',      (0, 1), (0, -1), 'LEFT'),
        ('ALIGN',      (1, 1), (-1, -1), 'CENTER'),
        ('ALIGN',      (3, 1), (-1, -1), 'RIGHT'),
        ('GRID',       (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 15))

    # --- Totales (misma lógica) ---
    total_neto = total_neto.quantize(DOS_DEC, rounding=ROUND_HALF_UP)
    iva = (total_neto * IVA).quantize(PESO, rounding=ROUND_HALF_UP)
    total = (total_neto + iva).quantize(PESO, rounding=ROUND_HALF_UP)

    tabla_totales = Table([
        ["Total Neto:", f"${formatear_miles_punto(total_neto)}"],
        ["IVA (19%):",  f"${formatear_miles_punto(iva)}"],
        ["Total:",      f"${formatear_miles_punto(total)}"]
    ], colWidths=[15.5*cm, 2.4*cm], hAlign='RIGHT')
    tabla_totales.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('LINEABOVE', (0, 2), (-1, 2), 1, colors.black),
    ]))
    elements.append(tabla_totales)
    elements.append(Spacer(1, 18))

    # --- Bloque receptor + firma (al final) ---
    elements.append(Paragraph("<b>Recepción conforme</b>", styles['Normal']))
    info_receptor = [
        ["Nombre", receptor.get('nombre', '')],
        ["RUT", receptor.get('rut', '')],
        ["Fecha/Hora", receptor.get('fecha').strftime("%d-%m-%Y %H:%M") if receptor.get('fecha') else ""],
    ]
    tbl_receptor = Table(info_receptor, colWidths=[4*cm, 11*cm], hAlign='LEFT')
    tbl_receptor.setStyle(TableStyle([
        ('INNERGRID',  (0,0), (-1,-1), 0.25, colors.lightgrey),
        ('BOX',        (0,0), (-1,-1), 0.25, colors.lightgrey),
        ('VALIGN',     (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING',(0,0), (-1,-1), 6),
        ('RIGHTPADDING',(0,0), (-1,-1), 6),
    ]))
    elements.append(tbl_receptor)
    elements.append(Spacer(1, 8))

    if firma_bytes:
        elements.append(Paragraph("Firma del receptor", styles['Normal']))
        firma_img = Image(BytesIO(firma_bytes), width=14*cm, height=3*cm)
        firma_img.hAlign = 'LEFT'
        elements.append(firma_img)
        elements.append(Spacer(1, 6))

    # Pie de contacto corporativo
    doc.build(elements, onFirstPage=pie_de_contacto, onLaterPages=pie_de_contacto)
    pdf = buf.getvalue()
    buf.close()
    return pdf
