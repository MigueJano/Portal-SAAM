"""Cliente de solo lectura para Movimientos y Saldos de Banco de Chile."""

from __future__ import annotations

import hashlib
import json
import ssl
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import jwt
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

from Apps.integraciones.models import MovimientoBancario, SaldoBancario


class BancoChileError(RuntimeError):
    pass


_token_cache = {"clave": None, "access_token": "", "vence_en": 0.0}
_token_lock = threading.Lock()


def _contexto_tls():
    contexto = ssl.create_default_context()
    contexto.minimum_version = ssl.TLSVersion.TLSv1_2
    return contexto


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
    url = getattr(settings, "BANCO_CHILE_MOVIMIENTOS_URL", "").strip()
    ambiente_configurado = getattr(settings, "BANCO_CHILE_AMBIENTE", "").strip().lower()
    ambiente = ambiente_configurado or ("sandbox" if "sandbox" in url.lower() else "production")
    valores = {
        "url": url,
        "ambiente": ambiente,
        "client_id": getattr(settings, "BANCO_CHILE_CLIENT_ID", ""),
        "client_secret": getattr(settings, "BANCO_CHILE_CLIENT_SECRET", ""),
        "bearer": getattr(settings, "BANCO_CHILE_BEARER_TOKEN", ""),
        "token_url": getattr(settings, "BANCO_CHILE_TOKEN_URL", ""),
        "private_key_path": getattr(settings, "BANCO_CHILE_PRIVATE_KEY_PATH", ""),
        "private_key_id": getattr(settings, "BANCO_CHILE_PRIVATE_KEY_ID", ""),
        "assertion_audience": getattr(settings, "BANCO_CHILE_AUTH0_ASSERTION_AUDIENCE", ""),
        "api_audience": getattr(settings, "BANCO_CHILE_API_AUDIENCE", "https://openbanking/"),
        "timeout": getattr(settings, "BANCO_CHILE_TIMEOUT", 35),
        "rut_origen": getattr(settings, "BANCO_CHILE_RUT_ORIGEN", ""),
        "producto_cuenta": getattr(settings, "BANCO_CHILE_PRODUCTO_CUENTA", ""),
        "cuenta": getattr(settings, "BANCO_CHILE_CUENTA", ""),
        "rut_apoderado": getattr(settings, "BANCO_CHILE_RUT_APODERADO", ""),
    }
    if ambiente not in {"sandbox", "production"}:
        raise ImproperlyConfigured("BANCO_CHILE_AMBIENTE debe ser sandbox o production.")
    requeridos = ("url", "client_id", "rut_origen", "producto_cuenta", "cuenta", "rut_apoderado")
    faltantes = [nombre for nombre in requeridos if not valores[nombre]]
    if ambiente == "sandbox" and not valores["client_secret"]:
        faltantes.append("client_secret")
    if ambiente == "production":
        faltantes.extend(
            nombre
            for nombre in ("token_url", "private_key_path", "assertion_audience", "api_audience")
            if not valores[nombre]
        )
    if faltantes:
        raise ImproperlyConfigured("Configuración Banco de Chile incompleta: " + ", ".join(faltantes))
    if not valores["url"].lower().startswith("https://"):
        raise ImproperlyConfigured("BANCO_CHILE_MOVIMIENTOS_URL debe usar HTTPS.")
    if ambiente == "production":
        if not valores["token_url"].lower().startswith("https://"):
            raise ImproperlyConfigured("BANCO_CHILE_TOKEN_URL debe usar HTTPS.")
        if not Path(valores["private_key_path"]).is_file():
            raise ImproperlyConfigured("BANCO_CHILE_PRIVATE_KEY_PATH no apunta a una llave PEM existente.")
    try:
        valores["timeout"] = int(valores["timeout"])
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured("BANCO_CHILE_TIMEOUT debe ser un número entero.") from exc
    return valores


def _crear_client_assertion(config: dict) -> str:
    ahora = datetime.now(timezone.utc)
    claims = {
        "iss": config["client_id"],
        "sub": config["client_id"],
        "aud": config["assertion_audience"],
        "iat": ahora,
        "exp": ahora + timedelta(minutes=1),
        "jti": str(uuid.uuid4()),
    }
    headers = {"alg": "RS256"}
    if config["private_key_id"]:
        headers["kid"] = config["private_key_id"]
    try:
        llave_privada = Path(config["private_key_path"]).read_text(encoding="utf-8")
        return jwt.encode(claims, llave_privada, algorithm="RS256", headers=headers)
    except (OSError, ValueError, jwt.PyJWTError) as exc:
        raise BancoChileError("No fue posible firmar el JWT de Banco de Chile.") from exc


def _solicitar_token_productivo(config: dict) -> tuple[str, int]:
    formulario = urlencode(
        {
            "grant_type": "client_credentials",
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": _crear_client_assertion(config),
            "audience": config["api_audience"],
        }
    ).encode("utf-8")
    request = Request(
        config["token_url"],
        data=formulario,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "CLIENTE_APISTORE",
        },
    )
    try:
        with urlopen(request, timeout=config["timeout"], context=_contexto_tls()) as response:
            respuesta = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detalle = exc.read().decode("utf-8", errors="replace")[:500]
        raise BancoChileError(f"Auth0 Banco de Chile respondió HTTP {exc.code}: {detalle}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise BancoChileError(f"No fue posible obtener el token de Banco de Chile: {exc}") from exc
    token = respuesta.get("access_token") if isinstance(respuesta, dict) else None
    if not token:
        raise BancoChileError("Auth0 Banco de Chile no entregó access_token.")
    try:
        expires_in = max(int(respuesta.get("expires_in", 300)), 1)
    except (TypeError, ValueError):
        expires_in = 300
    return str(token), expires_in


def _obtener_bearer(config: dict) -> str:
    if config["ambiente"] == "sandbox":
        bearer = str(config["bearer"] or "")
        return bearer[7:] if bearer.lower().startswith("bearer ") else bearer

    clave_cache = (
        config["client_id"],
        config["token_url"],
        config["private_key_path"],
        config["api_audience"],
    )
    ahora = time.monotonic()
    with _token_lock:
        if _token_cache["clave"] == clave_cache and _token_cache["vence_en"] > ahora + 60:
            return _token_cache["access_token"]
        token, expires_in = _solicitar_token_productivo(config)
        _token_cache.update(
            clave=clave_cache,
            access_token=token,
            vence_en=ahora + expires_in,
        )
        return token


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
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "client-id": config["client_id"],
        "User-Agent": "CLIENTE_APISTORE",
    }
    bearer = _obtener_bearer(config)
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if config["ambiente"] == "sandbox" and config["client_secret"]:
        headers["client-secret"] = config["client_secret"]
    request = Request(
        _url_periodo(config["url"]),
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    try:
        with urlopen(request, timeout=config["timeout"], context=_contexto_tls()) as response:
            respuesta = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detalle = exc.read().decode("utf-8", errors="replace")[:500]
        if 300 <= exc.code < 400:
            destino = exc.headers.get("Location", "")
            raise BancoChileError(
                f"Banco de Chile respondió HTTP {exc.code} con una redirección del gateway"
                f"{f' hacia {destino}' if destino else ''}; se esperaba JSON."
            ) from exc
        raise BancoChileError(f"Banco de Chile respondió HTTP {exc.code}: {detalle}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise BancoChileError(f"No fue posible consultar Banco de Chile: {exc}") from exc
    if not isinstance(respuesta, dict):
        raise BancoChileError("La respuesta bancaria no es un objeto JSON.")
    if respuesta.get("codigoRetorno") not in (None, "", "0", 0):
        codigo = respuesta.get("codigoRetorno")
        glosa = respuesta.get("glosaRespuesta") or "Sin glosa"
        raise BancoChileError(
            f"Banco de Chile rechazó la consulta ({codigo}): {glosa}"
        )
    if not isinstance(respuesta.get("movimientos", []), list):
        raise BancoChileError("La respuesta bancaria no contiene una lista de movimientos.")
    return respuesta


def consultar_movimientos(desde: date, hasta: date) -> dict:
    if desde > hasta:
        raise BancoChileError("La fecha inicial no puede ser posterior a la fecha final.")
    config = _configuracion()
    movimientos = []
    movimientos_vistos = set()
    pagina = 0
    cursores_usados = set()
    respuesta_final = {}
    advertencias = []
    for _ in range(100):
        if pagina in cursores_usados:
            advertencias.append(
                f"Banco de Chile repitió el cursor {pagina}; la paginación se cerró de forma segura."
            )
            break
        cursores_usados.add(pagina)
        respuesta = _solicitar_pagina(config, desde, hasta, pagina)
        for movimiento in respuesta.get("movimientos", []):
            firma = json.dumps(
                movimiento,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if firma not in movimientos_vistos:
                movimientos_vistos.add(firma)
                movimientos.append(movimiento)
        respuesta_final = respuesta
        if str(respuesta.get("indicadorMasPaginas", "N")).upper() != "Y":
            break
        try:
            pagina_siguiente = int(respuesta.get("indiceTerminoRespuesta")) + 1
        except (TypeError, ValueError) as exc:
            raise BancoChileError("La API indicó más páginas sin entregar un cursor válido.") from exc
        if pagina_siguiente in cursores_usados:
            advertencias.append(
                f"Banco de Chile repitió el cursor {pagina_siguiente}; "
                "se conservaron los movimientos recibidos y la paginación se cerró de forma segura."
            )
            break
        pagina = pagina_siguiente
    else:
        raise BancoChileError("La consulta superó el máximo de 100 páginas permitido por seguridad.")
    respuesta_final = dict(respuesta_final)
    respuesta_final["movimientos"] = movimientos
    if advertencias:
        respuesta_final["advertenciasPaginacion"] = advertencias
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
