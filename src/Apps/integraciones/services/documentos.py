from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

from django.core.files.base import ContentFile
from django.utils import timezone

from Apps.integraciones.models import DocumentoTributarioEntrante


def _texto_xml(root, nombres):
    for nodo in root.iter():
        nombre = nodo.tag.rsplit("}", 1)[-1]
        if nombre in nombres and nodo.text:
            return nodo.text.strip()
    return ""


def extraer_datos_xml(contenido: bytes) -> dict:
    try:
        root = ET.fromstring(contenido)
    except ET.ParseError:
        return {}
    monto = _texto_xml(root, {"MntTotal", "MontoTotal"})
    try:
        monto_total = Decimal(monto) if monto else None
    except InvalidOperation:
        monto_total = None
    return {
        "tipo_documento": _texto_xml(root, {"TipoDTE", "TpoDoc"})[:40],
        "folio": _texto_xml(root, {"Folio"})[:40],
        "rut_emisor": _texto_xml(root, {"RUTEmisor", "RUTEmi"})[:20],
        "monto_total": monto_total,
    }


def guardar_adjunto(*, message_id, remitente, asunto, recibido_en, nombre, contenido):
    extension = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    if extension not in {"xml", "pdf"}:
        return None, False
    digest = hashlib.sha256(contenido).hexdigest()
    datos = extraer_datos_xml(contenido) if extension == "xml" else {}
    documento = DocumentoTributarioEntrante(
        gmail_message_id=message_id[:160],
        remitente=remitente[:254],
        asunto=asunto[:500],
        recibido_en=recibido_en or timezone.now(),
        nombre_archivo=nombre[:255],
        sha256=digest,
        **datos,
    )
    existente = DocumentoTributarioEntrante.objects.filter(sha256=digest).first()
    if existente:
        return existente, False
    nombre_seguro = re.sub(r"[^A-Za-z0-9._-]", "_", nombre)
    documento.archivo.save(nombre_seguro, ContentFile(contenido), save=True)
    return documento, True


def fecha_correo_a_datetime(valor):
    if not valor:
        return timezone.now()
    if isinstance(valor, datetime):
        dt = valor
    else:
        try:
            dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        except ValueError:
            return timezone.now()
    if timezone.is_naive(dt):
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt

