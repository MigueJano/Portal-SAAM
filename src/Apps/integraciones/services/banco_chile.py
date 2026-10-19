"""Cliente de solo lectura para Movimientos y Saldos de Banco de Chile."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

from Apps.integraciones.models import MovimientoBancario, SaldoBancario


class BancoChileError(RuntimeError):
    pass


def _primer_valor(fila: dict, *nombres, default=""):
    for nombre in nombres:
        valor = fila.get(nombre)
        if valor not in (None, ""):
            return valor
    return default


def _fecha(valor) -> date:
    texto = str(valor or "").strip()
    try:
        if len(texto) >= 8 and texto[:8].isdigit():
            return datetime.strptime(texto[:8], "%Y%m%d").date()
        return date.fromisoformat(texto[:10])
    except ValueError as exc:
        raise BancoChileError(f"Fecha bancaria inválida: {valor!r}") from exc


def _decimal(valor, *, absoluto=False) -> Decimal:
    texto = str(valor or "0").strip()
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        numero = Decimal(texto)
    except Exception as exc:
        raise BancoChileError(f"Monto bancario inválido: {valor!r}") from exc
    return abs(numero) if absoluto else numero


def _datos_adicionales(fila: dict) -> dict[str, str]:
    resultado = {}
    for grupo in fila.get("adicionales") or []:
        campos = grupo.get("campos") or []
        if len(campos) < 2:
            continue
        etiqueta = str(campos[0].get("dato", "")).strip().rstrip(":").lower()
        valor = str(campos[1].get("dato", "")).strip()
        if etiqueta and valor:
            resultado[etiqueta] = valor
    return resultado


def _enmascarar_cuenta(valor) -> str:
    cuenta = str(valor or "").strip()
    if len(cuenta) <= 4:
        return cuenta
    return ("*" * min(len(cuenta) - 4, 12)) + cuenta[-4:]


def normalizar_movimiento(fila: dict, *, cuenta="", moneda="CLP") -> dict:
    monto_raw = _primer_valor(fila, "monto", "amount", "montoMovimiento", default=0)
    indicador = str(_primer_valor(
        fila, "indicadorCreditoDebito", "tipo", "tipoMovimiento", "creditDebitIndicator"
    )).upper()
    es_cargo = indicador in {"CARGO", "DEBIT", "D", "EGRESO"} or str(monto_raw).strip().startswith("-")
    identificador = str(_primer_valor(
        fila, "secuencial", "idInternoTransaccion", "id", "identificador", "numeroOperacion", "reference"
    ))
    if not identificador:
        estable = json.dumps(fila, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        identificador = hashlib.sha256(estable.encode("utf-8")).hexdigest()

    adicionales = _datos_adicionales(fila)
    es_abono = not es_cargo
    rut = adicionales.get("rut origen") if es_abono else adicionales.get("rut destinatario")
    nombre = adicionales.get("nombre origen") if es_abono else adicionales.get("nombre destinatario")
    rut = rut or (str(fila.get("campoComplementario4", "")) if es_abono else "")
    nombre = nombre or (str(fila.get("campoComplementario6", "")) if es_abono else "")

    return {
        "identificador_externo": identificador[:160],
        "cuenta_enmascarada": _enmascarar_cuenta(
            cuenta or _primer_valor(fila, "cuenta", "account", "numeroCuenta")
        ),
        "fecha": _fecha(_primer_valor(
            fila, "fechaContable", "fechaTransaccion", "fecha", "date", "fechaMovimiento"
        )),
        "descripcion": str(_primer_valor(
            fila, "descripcionLarga", "descripcionTransaccionCore", "descripcionCorta",
            "descripcion", "description", "glosa"
        ))[:500],
        "referencia": str(_primer_valor(
            fila, "campoComplementario7", "numeroDocumento", "idInternoTransaccion",
            "referencia", "reference", "numeroOperacion"
        ))[:160],
        "rut_contraparte": str(rut or _primer_valor(fila, "rut", "rutContraparte"))[:20],
        "nombre_contraparte": str(nombre or _primer_valor(fila, "nombre", "nombreContraparte"))[:160],
        "tipo": MovimientoBancario.TIPO_CARGO if es_cargo else MovimientoBancario.TIPO_ABONO,
        "monto": _decimal(monto_raw, absoluto=True),
        "moneda": str(moneda or _primer_valor(fila, "moneda", "currency", default="CLP"))[:4],
        "datos_origen": fila,
    }


def importar_filas(filas: list[dict], *, cuenta="", moneda="CLP") -> tuple[int, int]:
    creados = existentes = 0
    with transaction.atomic():
        for fila in filas:
            datos = normalizar_movimiento(fila, cuenta=cuenta, moneda=moneda)
            _, creado = MovimientoBancario.objects.get_or_create(
                proveedor_api="BANCO_CHILE",
                identificador_externo=datos.pop("identificador_externo"),
                defaults=datos,
            )
            creados += int(creado)
            existentes += int(not creado)
    return creados, existentes


def _configuracion():
    valores = {
        "url": getattr(settings, "BANCO_CHILE_MOVIMIENTOS_URL", ""),
        "client_id": getattr(settings, "BANCO_CHILE_CLIENT_ID", ""),
        "client_secret": getattr(settings, "BANCO_CHILE_CLIENT_SECRET", ""),
        "bearer": getattr(settings, "BANCO_CHILE_BEARER_TOKEN", ""),
        "rut_origen": getattr(settings, "BANCO_CHILE_RUT_ORIGEN", ""),
        "producto_cuenta": getattr(settings, "BANCO_CHILE_PRODUCTO_CUENTA", ""),
        "cuenta": getattr(settings, "BANCO_CHILE_CUENTA", ""),
        "rut_apoderado": getattr(settings, "BANCO_CHILE_RUT_APODERADO", ""),
    }
    requeridos = ("url", "client_id", "bearer", "rut_origen", "producto_cuenta", "cuenta", "rut_apoderado")
    faltantes = [nombre for nombre in requeridos if not valores[nombre]]
    if "sandbox" in valores["url"] and not valores["client_secret"]:
        faltantes.append("client_secret")
    if faltantes:
        raise ImproperlyConfigured("Configuración Banco de Chile incompleta: " + ", ".join(faltantes))
    return valores


def _url_periodo(url: str) -> str:
    limpia = url.rstrip("/")
    return limpia if limpia.endswith("/obtener-periodo") else limpia + "/obtener-periodo"


def _solicitar_pagina(config: dict, desde: date, hasta: date, paginacion_desde: int) -> dict:
    payload = {
        "rutOrigen": config["rut_origen"],
        "productoCuenta": config["producto_cuenta"],
        "cuenta": config["cuenta"],
        "rutApoderado": [{"value": config["rut_apoderado"]}],
        "fechaDesde": desde.isoformat(),
        "fechaHasta": hasta.isoformat(),
        "paginacionDesde": paginacion_desde,
    }
    bearer = config["bearer"]
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "client-id": config["client_id"],
        "Authorization": bearer if bearer.lower().startswith("bearer ") else f"Bearer {bearer}",
    }
    if config["client_secret"]:
        headers["client-secret"] = config["client_secret"]
    request = Request(
        _url_periodo(config["url"]),
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    try:
        with urlopen(request, timeout=30) as response:
            respuesta = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detalle = exc.read().decode("utf-8", errors="replace")[:500]
        raise BancoChileError(f"Banco de Chile respondió HTTP {exc.code}: {detalle}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise BancoChileError(f"No fue posible consultar Banco de Chile: {exc}") from exc
    if not isinstance(respuesta, dict):
        raise BancoChileError("La respuesta bancaria no es un objeto JSON.")
    if respuesta.get("codigoRetorno") not in (None, "", "0", 0):
        raise BancoChileError(
            f"Banco de Chile rechazó la consulta: {respuesta.get('glosaRespuesta') or respuesta.get('codigoRetorno')}"
        )
    if not isinstance(respuesta.get("movimientos", []), list):
        raise BancoChileError("La respuesta bancaria no contiene una lista de movimientos.")
    return respuesta


def consultar_movimientos(desde: date, hasta: date) -> dict:
    if desde > hasta:
        raise BancoChileError("La fecha inicial no puede ser posterior a la fecha final.")
    config = _configuracion()
    movimientos = []
    pagina = 0
    cursores_usados = set()
    respuesta_final = {}
    for _ in range(100):
        if pagina in cursores_usados:
            raise BancoChileError("La API repitió el cursor de paginación.")
        cursores_usados.add(pagina)
        respuesta = _solicitar_pagina(config, desde, hasta, pagina)
        movimientos.extend(respuesta.get("movimientos", []))
        respuesta_final = respuesta
        if str(respuesta.get("indicadorMasPaginas", "N")).upper() != "Y":
            break
        try:
            pagina = int(respuesta.get("indiceTerminoRespuesta"))
        except (TypeError, ValueError) as exc:
            raise BancoChileError("La API indicó más páginas sin entregar un cursor válido.") from exc
    else:
        raise BancoChileError("La consulta superó el máximo de 100 páginas permitido por seguridad.")
    respuesta_final = dict(respuesta_final)
    respuesta_final["movimientos"] = movimientos
    return respuesta_final


def guardar_resultado(respuesta: dict, *, desde: date, hasta: date) -> tuple[int, int, SaldoBancario, bool]:
    movimientos = respuesta.get("movimientos", [])
    cuenta = str(respuesta.get("numeroCuenta") or getattr(settings, "BANCO_CHILE_CUENTA", ""))
    moneda = str(respuesta.get("moneda") or "CLP")
    creados, existentes = importar_filas(movimientos, cuenta=cuenta, moneda=moneda)
    datos_origen = {k: v for k, v in respuesta.items() if k != "movimientos"}
    estable = json.dumps(
        {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "respuesta": datos_origen},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    respuesta_hash = hashlib.sha256(estable.encode("utf-8")).hexdigest()
    saldo, saldo_creado = SaldoBancario.objects.get_or_create(
        respuesta_hash=respuesta_hash,
        defaults={
            "cuenta_enmascarada": _enmascarar_cuenta(cuenta),
            "moneda": moneda[:4],
            "nombre_titular": str(respuesta.get("nombreTitular") or "")[:160],
            "saldo_disponible": _decimal(respuesta.get("saldoDisponible")),
            "saldo_contable": _decimal(respuesta.get("saldoContable")),
            "total_cargos": _decimal(respuesta.get("totalCargo")),
            "total_abonos": _decimal(respuesta.get("totalAbono")),
            "saldo_inicio": _decimal(respuesta.get("saldoInicio")),
            "saldo_final": _decimal(respuesta.get("saldoFinal")),
            "periodo_desde": desde,
            "periodo_hasta": hasta,
            "datos_origen": datos_origen,
        },
    )
    return creados, existentes, saldo, saldo_creado
