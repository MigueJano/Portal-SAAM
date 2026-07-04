from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from xml.etree import ElementTree as ET

from django.core.files.base import ContentFile
from django.utils import timezone

from Apps.Pedidos.models import BoletaElectronica, ConfiguracionBoletaSii, Venta
from Apps.Pedidos.services.pedido_items import items_comerciales_pedido
from Apps.Pedidos.utils import validar_rut


DOS_DEC = Decimal("0.01")
RUT_CONSUMIDOR_FINAL = "66666666-6"
NOMBRE_CONSUMIDOR_FINAL = "Consumidor Final"


def _q2(value: Decimal | int | str | None) -> Decimal:
    return Decimal(value or 0).quantize(DOS_DEC, rounding=ROUND_HALF_UP)


def _money_str(value: Decimal | int | str | None) -> str:
    return f"{_q2(value):.2f}"


def _text(value: str | None) -> str:
    return (value or "").strip()


def _safe_rut(rut: str | None) -> str:
    return _text(rut).replace(".", "").upper()


def _configuracion_boleta_activa() -> ConfiguracionBoletaSii | None:
    return ConfiguracionBoletaSii.objects.filter(activa=True).order_by("id").first()


def _requiere_identificacion_receptor(venta: Venta, config: ConfiguracionBoletaSii | None) -> bool:
    if config is None:
        return False
    monto_tope = _q2(getattr(config, "monto_identificacion_receptor_boleta", 0))
    return monto_tope > 0 and _q2(venta.venta_total_pedido) > monto_tope


def _receptor_boleta(venta: Venta, requiere_identificacion: bool) -> dict:
    cliente = venta.pedidoid.nombre_cliente
    rut_cliente = _text(cliente.rut_cliente)
    rut_cliente_valido = bool(rut_cliente and validar_rut(rut_cliente))
    nombre_cliente = _text(cliente.nombre_tributario)

    if requiere_identificacion or rut_cliente_valido:
        rut = _safe_rut(rut_cliente)
        nombre = nombre_cliente
    else:
        rut = RUT_CONSUMIDOR_FINAL
        nombre = nombre_cliente or NOMBRE_CONSUMIDOR_FINAL

    return {
        "rut": rut,
        "nombre": nombre,
        "giro": _text(cliente.giro_cliente),
        "direccion": _text(cliente.direccion_cliente),
        "comuna": _text(cliente.comuna_cliente),
        "ciudad": _text(cliente.ciudad_cliente),
        "email": _text(cliente.correo_cliente),
        "identificacion_obligatoria": requiere_identificacion,
    }


def _detalle_desde_venta(venta: Venta) -> list[dict]:
    detalle = []
    pedido = venta.pedidoid
    for numero_linea, item in enumerate(items_comerciales_pedido(pedido), start=1):
        if item["origen"] == "linea":
            linea = item["linea"]
            descripcion = _text(linea.descripcion) or _text(linea.producto.nombre_producto)
            empaque = _text(linea.empaque)
            cantidad = Decimal(linea.cantidad or 0)
            precio_unitario = _q2(linea.precio_unitario)
        else:
            legacy = item["legacy"]
            producto = item["producto"]
            descripcion = _text(getattr(producto, "nombre_producto", "")) or _text(legacy["producto__nombre_producto"])
            empaque = _text(legacy["empaque"])
            cantidad = Decimal(legacy["qty_sum"] or 0)
            precio_unitario = _q2(legacy["precio_unitario"])

        subtotal = _q2(precio_unitario * cantidad)
        detalle.append(
            {
                "nro_linea": numero_linea,
                "descripcion": descripcion,
                "empaque": empaque,
                "cantidad": str(cantidad),
                "precio_unitario": _money_str(precio_unitario),
                "subtotal": _money_str(subtotal),
            }
        )
    return detalle


def _errores_configuracion(config: ConfiguracionBoletaSii | None) -> list[str]:
    if config is None:
        return ["No existe una configuracion SII activa para boleta electronica."]

    errores = []
    campos_obligatorios = {
        "rut_emisor": "RUT emisor",
        "razon_social": "Razon social emisor",
        "giro": "Giro emisor",
        "direccion_origen": "Direccion origen",
        "comuna_origen": "Comuna origen",
        "ciudad_origen": "Ciudad origen",
    }
    for campo, etiqueta in campos_obligatorios.items():
        if not _text(getattr(config, campo, "")):
            errores.append(f"Falta configurar {etiqueta}.")

    rut_emisor = _text(getattr(config, "rut_emisor", ""))
    if rut_emisor and not validar_rut(rut_emisor):
        errores.append("El RUT emisor configurado no es valido.")

    if not getattr(config, "habilita_boleta", False):
        errores.append("La configuracion SII activa no tiene habilitada la boleta electronica.")

    if not _text(getattr(config, "ruta_caf_tipo_39", "")):
        errores.append("Falta registrar la ruta o referencia del CAF tipo 39.")

    return errores


def _errores_venta_boleta(venta: Venta, detalle: list[dict], config: ConfiguracionBoletaSii | None) -> list[str]:
    errores = []
    cliente = venta.pedidoid.nombre_cliente
    requiere_identificacion = _requiere_identificacion_receptor(venta, config)

    if venta.documento_pedido != "Boleta":
        errores.append("La venta no esta marcada como Boleta.")

    if requiere_identificacion:
        rut_cliente = _text(cliente.rut_cliente)
        if not rut_cliente:
            errores.append("La boleta supera el monto configurado para 135 UF y el receptor no tiene RUT.")
        elif not validar_rut(rut_cliente):
            errores.append("La boleta supera el monto configurado para 135 UF y el RUT del receptor no es valido.")

        if not _text(cliente.nombre_tributario):
            errores.append("La boleta supera el monto configurado para 135 UF y el receptor no tiene nombre tributario.")

    if not detalle:
        errores.append("La venta no tiene detalle comercial para construir la boleta.")

    if _q2(venta.venta_total_pedido) <= 0:
        errores.append("El total de la venta debe ser mayor a cero.")

    return errores


def _payload_boleta(venta: Venta, config: ConfiguracionBoletaSii | None, detalle: list[dict]) -> dict:
    requiere_identificacion = _requiere_identificacion_receptor(venta, config)
    return {
        "meta": {
            "tipo_dte": 39,
            "documento": "Boleta Electronica",
            "ambiente": config.ambiente if config else "",
            "folio": None,
            "fecha_emision": venta.fecha_venta.isoformat(),
            "pedido_id": venta.pedidoid_id,
            "venta_id": venta.id,
            "idempotency_key": f"venta-{venta.id}-boleta-39",
            "generado_en": timezone.now().isoformat(),
            "requiere_identificacion_receptor": requiere_identificacion,
            "monto_identificacion_receptor_boleta": _money_str(getattr(config, "monto_identificacion_receptor_boleta", 0)),
        },
        "emisor": {
            "rut": _safe_rut(getattr(config, "rut_emisor", "")),
            "razon_social": _text(getattr(config, "razon_social", "")),
            "giro": _text(getattr(config, "giro", "")),
            "direccion": _text(getattr(config, "direccion_origen", "")),
            "comuna": _text(getattr(config, "comuna_origen", "")),
            "ciudad": _text(getattr(config, "ciudad_origen", "")),
            "resolucion_numero": getattr(config, "resolucion_numero", None),
            "resolucion_fecha": config.resolucion_fecha.isoformat() if config and config.resolucion_fecha else "",
            "caf_tipo_39": _text(getattr(config, "ruta_caf_tipo_39", "")),
        },
        "receptor": _receptor_boleta(venta, requiere_identificacion),
        "totales": {
            "neto": _money_str(venta.venta_neto_pedido),
            "iva": _money_str(venta.venta_iva_pedido),
            "total": _money_str(venta.venta_total_pedido),
        },
        "detalle": detalle,
    }


def _render_xml_documento(payload: dict) -> bytes:
    root = ET.Element("BoletaElectronicaSAAM", version="1.0")

    meta = ET.SubElement(root, "Meta")
    for key, value in payload["meta"].items():
        node = ET.SubElement(meta, key)
        node.text = "" if value is None else str(value)

    emisor = ET.SubElement(root, "Emisor")
    for key, value in payload["emisor"].items():
        node = ET.SubElement(emisor, key)
        node.text = "" if value is None else str(value)

    receptor = ET.SubElement(root, "Receptor")
    for key, value in payload["receptor"].items():
        node = ET.SubElement(receptor, key)
        node.text = "" if value is None else str(value)

    totales = ET.SubElement(root, "Totales")
    for key, value in payload["totales"].items():
        node = ET.SubElement(totales, key)
        node.text = str(value)

    detalle = ET.SubElement(root, "Detalle")
    for row in payload["detalle"]:
        item = ET.SubElement(detalle, "Item")
        for key, value in row.items():
            node = ET.SubElement(item, key)
            node.text = str(value)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def generar_boleta_desde_venta(venta: Venta, usuario=None) -> BoletaElectronica:
    detalle = _detalle_desde_venta(venta)
    config = _configuracion_boleta_activa()
    errores = _errores_configuracion(config)
    errores.extend(_errores_venta_boleta(venta, detalle, config))
    payload = _payload_boleta(venta, config, detalle)

    boleta, _ = BoletaElectronica.objects.get_or_create(
        venta=venta,
        defaults={"idempotency_key": payload["meta"]["idempotency_key"]},
    )

    boleta.configuracion = config
    boleta.tipo_dte = 39
    boleta.ambiente = config.ambiente if config else ""
    boleta.idempotency_key = payload["meta"]["idempotency_key"]
    boleta.payload = payload
    boleta.errores_validacion = errores
    boleta.preparada_por = usuario
    boleta.preparada_en = timezone.now()

    if errores:
        boleta.estado = BoletaElectronica.ESTADO_DATOS_INCOMPLETOS
        if boleta.xml_borrador:
            boleta.xml_borrador.delete(save=False)
            boleta.xml_borrador = None
    else:
        boleta.estado = BoletaElectronica.ESTADO_XML_PREPARADO
        xml_bytes = _render_xml_documento(payload)
        fecha = timezone.localdate().isoformat()
        filename = f"boleta_electronica_venta_{venta.id}_{fecha}.xml"
        if boleta.xml_borrador:
            boleta.xml_borrador.delete(save=False)
        boleta.xml_borrador.save(filename, ContentFile(xml_bytes), save=False)

    boleta.save()
    return boleta


def preparar_boleta_desde_venta(venta: Venta, usuario=None) -> BoletaElectronica:
    return generar_boleta_desde_venta(venta, usuario=usuario)


def nombre_archivo_xml(boleta: BoletaElectronica) -> str:
    if not boleta.xml_borrador:
        return ""
    return Path(boleta.xml_borrador.name).name
