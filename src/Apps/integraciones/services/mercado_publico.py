import json
import socket
import unicodedata
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction
from django.utils.dateparse import parse_datetime

from Apps.integraciones.models import CompraAgil, FiltroCompraAgil


class MercadoPublicoError(RuntimeError):
    pass


def _texto_comparable(valor):
    normalizado = unicodedata.normalize("NFKD", str(valor or ""))
    return "".join(letra for letra in normalizado if not unicodedata.combining(letra)).casefold()


def _decimal(valor):
    if valor in (None, ""):
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _fecha(valor):
    if not valor:
        return None
    return parse_datetime(str(valor))


def _mensaje_error(datos, predeterminado):
    errores = datos.get("errors") if isinstance(datos, dict) else None
    if errores:
        mensajes = [str(error.get("mensaje") or error.get("detalle") or "") for error in errores]
        return "; ".join(mensaje for mensaje in mensajes if mensaje) or predeterminado
    return predeterminado


class ClienteMercadoPublico:
    def __init__(self, *, base_url=None, ticket=None, timeout=None):
        self.base_url = (base_url or settings.MERCADO_PUBLICO_API_URL).rstrip("/")
        self.ticket = ticket if ticket is not None else settings.MERCADO_PUBLICO_TICKET
        self.timeout = timeout or settings.MERCADO_PUBLICO_TIMEOUT
        if not self.ticket:
            raise MercadoPublicoError(
                "Falta configurar MERCADO_PUBLICO_TICKET en las variables privadas del entorno."
            )

    def _get(self, ruta, parametros=None):
        url = f"{self.base_url}/{ruta.lstrip('/')}"
        if parametros:
            url = f"{url}?{urlencode(parametros)}"
        request = Request(
            url,
            headers={"ticket": self.ticket, "Accept": "application/json", "User-Agent": "Portal-SAAM/1.0"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout) as respuesta:
                datos = json.loads(respuesta.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                datos_error = json.loads(exc.read().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                datos_error = {}
            if exc.code == 429:
                espera = exc.headers.get("Retry-After")
                detalle = f" Reintente en {espera} segundos." if espera else " Reintente más tarde."
                raise MercadoPublicoError("Mercado Público informó que se agotó la cuota diaria." + detalle) from exc
            raise MercadoPublicoError(
                _mensaje_error(datos_error, f"Mercado Público respondió HTTP {exc.code}.")
            ) from exc
        except (URLError, socket.timeout, TimeoutError) as exc:
            raise MercadoPublicoError(f"No fue posible conectar con Mercado Público: {exc}") from exc
        except (ValueError, UnicodeDecodeError) as exc:
            raise MercadoPublicoError("Mercado Público entregó una respuesta que no es JSON válido.") from exc

        if datos.get("success") != "OK" or datos.get("payload") is None:
            raise MercadoPublicoError(_mensaje_error(datos, "La API rechazó la consulta."))
        return datos["payload"]

    def listar(self, parametros):
        return self._get("v2/compra-agil", parametros)

    def detalle(self, codigo):
        return self._get(f"v2/compra-agil/{quote(codigo, safe='')}")


def _parametros_filtro(filtro, palabra, pagina):
    parametros = {
        "tamano_pagina": 50,
        "numero_pagina": pagina,
        "ordenar_por": "FechaUltimaModificacion",
        "estado": ",".join(filtro.estados or ["publicada"]),
    }
    if filtro.regiones:
        parametros["region"] = ",".join(str(region) for region in filtro.regiones)
    if palabra:
        parametros["q"] = palabra
    return parametros


def _obtener_items(cliente, filtro):
    encontrados = {}
    palabras = filtro.lista_palabras_clave or [None]
    for palabra in palabras:
        pagina = 1
        while True:
            payload = cliente.listar(_parametros_filtro(filtro, palabra, pagina))
            for item in payload.get("items") or []:
                if item.get("codigo"):
                    encontrados[item["codigo"]] = item
            paginacion = payload.get("paginacion") or {}
            total_paginas = int(paginacion.get("total_paginas") or 1)
            if pagina >= total_paginas:
                break
            pagina += 1
    return encontrados


def _detalle_necesario(compra, item):
    if compra is None:
        return True
    ultimo_cambio = _fecha((item.get("fechas") or {}).get("fecha_ultimo_cambio"))
    return not ultimo_cambio or compra.fecha_ultimo_cambio != ultimo_cambio


def _valores_compra(item, detalle):
    fechas = detalle.get("fechas") or item.get("fechas") or {}
    convocatoria = detalle.get("convocatoria") or item.get("convocatoria") or {}
    institucion = detalle.get("institucion") or item.get("institucion") or {}
    presupuesto = detalle.get("presupuesto") or {}
    montos = item.get("montos") or {}
    entrega = detalle.get("entrega") or {}
    estado = detalle.get("estado") or item.get("estado") or {}
    monto = presupuesto.get("monto_disponible_clp")
    if monto is None:
        monto = presupuesto.get("presupuesto_estimado")
    if monto is None:
        monto = montos.get("monto_disponible_clp", montos.get("monto_disponible"))
    return {
        "nombre": detalle.get("nombre") or item.get("nombre") or "",
        "descripcion": detalle.get("descripcion") or "",
        "estado_api": estado.get("codigo") or "",
        "estado_api_glosa": estado.get("glosa") or "",
        "estado_convocatoria": convocatoria.get("estado_convocatoria"),
        "fecha_publicacion": _fecha(fechas.get("fecha_publicacion")),
        "fecha_cierre": _fecha(fechas.get("fecha_cierre")),
        "fecha_cierre_primer_llamado": _fecha(convocatoria.get("fecha_cierre_primer_llamado")),
        "fecha_ultimo_cambio": _fecha(fechas.get("fecha_ultimo_cambio")),
        "monto": _decimal(monto),
        "moneda": presupuesto.get("moneda") or montos.get("moneda") or "CLP",
        "organismo_comprador": institucion.get("organismo_comprador") or "",
        "rut_organismo": institucion.get("rut") or "",
        "unidad_compra": institucion.get("unidad_compra") or "",
        "region": institucion.get("region"),
        "nombre_region": institucion.get("nombre_region") or "",
        "direccion_entrega": entrega.get("direccion_entrega") or "",
        "enlace_publico": (
            "https://buscador.mercadopublico.cl/ficha?code="
            + quote(str(item.get("codigo") or detalle.get("codigo") or ""), safe="")
        ),
        "datos_origen": {"listado": item, "detalle": detalle},
    }


def _coincide_filtro(compra, filtro):
    if filtro.regiones and compra.region not in filtro.regiones:
        return False
    if filtro.monto_minimo is not None and (compra.monto is None or compra.monto < filtro.monto_minimo):
        return False
    if filtro.monto_maximo is not None and (compra.monto is None or compra.monto > filtro.monto_maximo):
        return False
    if filtro.lugar:
        lugar = _texto_comparable(filtro.lugar)
        ubicacion = _texto_comparable(
            " ".join((compra.direccion_entrega, compra.unidad_compra, compra.nombre_region))
        )
        if lugar not in ubicacion:
            return False
    palabras = [_texto_comparable(valor) for valor in filtro.lista_palabras_clave]
    if palabras:
        texto = _texto_comparable(f"{compra.nombre} {compra.descripcion}")
        if not any(palabra in texto for palabra in palabras):
            return False
    return True


def sincronizar_compras_agiles(cliente=None):
    filtros = list(FiltroCompraAgil.objects.filter(activo=True))
    if not filtros:
        raise MercadoPublicoError("No existen filtros activos de Compra Ágil.")
    cliente = cliente or ClienteMercadoPublico()
    coincidencias = {filtro.pk: set() for filtro in filtros}
    creadas = actualizadas = 0

    for filtro in filtros:
        for codigo, item in _obtener_items(cliente, filtro).items():
            compra = CompraAgil.objects.filter(codigo=codigo).first()
            if _detalle_necesario(compra, item):
                detalle = cliente.detalle(codigo)
                valores = _valores_compra(item, detalle)
                compra, creada = CompraAgil.objects.update_or_create(codigo=codigo, defaults=valores)
                creadas += int(creada)
                actualizadas += int(not creada)
            if compra and _coincide_filtro(compra, filtro):
                coincidencias[filtro.pk].add(compra.pk)

    ids_coincidentes = set().union(*coincidencias.values()) if coincidencias else set()
    with transaction.atomic():
        CompraAgil.objects.update(coincide_filtros=False)
        CompraAgil.objects.filter(pk__in=ids_coincidentes).update(coincide_filtros=True)
        CompraAgil.filtros.through.objects.all().delete()
        for filtro in filtros:
            filtro.compras.set(coincidencias[filtro.pk])
    return {
        "creadas": creadas,
        "actualizadas": actualizadas,
        "coincidentes": len(ids_coincidentes),
        "filtros": len(filtros),
    }
