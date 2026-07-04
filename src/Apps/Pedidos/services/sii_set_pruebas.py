from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from xml.etree import ElementTree as ET

from Apps.Pedidos.models import ConfiguracionBoletaSii


PESO = Decimal("1")
IVA_RATE = Decimal("0.19")
FACTOR_IVA = Decimal("1.19")
RUT_CONSUMIDOR_FINAL = "66666666-6"
NOMBRE_CONSUMIDOR_FINAL = "Consumidor Final"
RUT_RECEPTOR_SII = "60803000-K"
SII_NS = "http://www.sii.cl/SiiDte"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

CASE_RE = re.compile(r"(?m)^CASO-(?P<num>\d+)\s*$")
ITEM_RE = re.compile(r"^(?P<nombre>.+?)\s+(?P<cantidad>\d+(?:[,.]\d+)?)\s+(?P<precio>[\d.]+)\s*$")


@dataclass(frozen=True)
class BoletaSetItem:
    nombre: str
    cantidad: Decimal
    precio_unitario_con_iva: Decimal
    exento: bool = False
    unidad_medida: str = ""

    @property
    def monto_item(self) -> Decimal:
        return _q0(self.cantidad * self.precio_unitario_con_iva)


@dataclass(frozen=True)
class BoletaSetCase:
    codigo: str
    items: tuple[BoletaSetItem, ...]
    observacion: str = ""


def _q0(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(PESO, rounding=ROUND_HALF_UP)


def _amount(value: str) -> Decimal:
    return Decimal((value or "0").strip().replace(".", "").replace(",", "."))


def _text(value: str | None) -> str:
    return (value or "").strip()


def _safe_rut(value: str | None) -> str:
    return _text(value).replace(".", "").upper()


def _node(parent: ET.Element, tag: str, value: object | None) -> ET.Element:
    node = ET.SubElement(parent, tag)
    node.text = "" if value is None else str(value)
    return node


def _timestamp() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _xml_bytes(root: ET.Element) -> bytes:
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _case_blocks(text: str) -> list[tuple[str, str]]:
    matches = list(CASE_RE.finditer(text))
    blocks = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append((f"CASO-{match.group('num')}", text[start:end]))
    return blocks


def parse_set_prueba_boleta(text: str) -> list[BoletaSetCase]:
    cases = []
    for codigo, block in _case_blocks(text):
        observaciones = []
        items = []
        for raw_line in block.splitlines():
            line = raw_line.strip()
            upper = line.upper()
            if not line or set(line) <= {"="}:
                continue
            if upper.startswith("ITEM") and "CANTIDAD" in upper:
                continue
            if upper.startswith("OBSERVACION"):
                observaciones.append(line)
                continue
            if "OBSERVACION" in upper:
                observaciones.append(line)
                continue

            match = ITEM_RE.match(line)
            if not match:
                continue

            nombre = match.group("nombre").strip()
            unidad = "Kg" if codigo == "CASO-5" else ""
            items.append(
                BoletaSetItem(
                    nombre=nombre,
                    cantidad=_amount(match.group("cantidad")),
                    precio_unitario_con_iva=_amount(match.group("precio")),
                    exento="EXENTO" in nombre.upper(),
                    unidad_medida=unidad,
                )
            )

        if items:
            cases.append(BoletaSetCase(codigo=codigo, items=tuple(items), observacion=" ".join(observaciones)))
    return cases


def parse_set_prueba_boleta_file(path: str | Path) -> list[BoletaSetCase]:
    return parse_set_prueba_boleta(Path(path).read_text(encoding="utf-8-sig"))


def totales_boleta_set_case(case: BoletaSetCase) -> dict[str, Decimal]:
    monto_afecto_bruto = sum((item.monto_item for item in case.items if not item.exento), start=Decimal("0"))
    monto_exento = sum((item.monto_item for item in case.items if item.exento), start=Decimal("0"))
    monto_neto = _q0(monto_afecto_bruto / FACTOR_IVA) if monto_afecto_bruto else Decimal("0")
    iva = monto_afecto_bruto - monto_neto
    total = monto_afecto_bruto + monto_exento
    return {
        "monto_neto": _q0(monto_neto),
        "iva": _q0(iva),
        "monto_exento": _q0(monto_exento),
        "monto_total": _q0(total),
    }


def render_boleta_set_xml(
    case: BoletaSetCase,
    *,
    config: ConfiguracionBoletaSii,
    folio: int,
    fecha_emision: date,
) -> bytes:
    totals = totales_boleta_set_case(case)
    dte = ET.Element("DTE", version="1.0")
    documento = ET.SubElement(dte, "Documento", ID=f"T39F{folio}")

    encabezado = ET.SubElement(documento, "Encabezado")
    id_doc = ET.SubElement(encabezado, "IdDoc")
    _node(id_doc, "TipoDTE", 39)
    _node(id_doc, "Folio", folio)
    _node(id_doc, "FchEmis", fecha_emision.isoformat())
    _node(id_doc, "IndServicio", 3)

    emisor = ET.SubElement(encabezado, "Emisor")
    _node(emisor, "RUTEmisor", _safe_rut(config.rut_emisor))
    _node(emisor, "RznSocEmisor", config.razon_social)
    _node(emisor, "GiroEmisor", config.giro)
    if _text(config.acteco_principal):
        _node(emisor, "Acteco", config.acteco_principal)
    _node(emisor, "DirOrigen", config.direccion_origen)
    _node(emisor, "CmnaOrigen", config.comuna_origen)
    _node(emisor, "CiudadOrigen", config.ciudad_origen)

    receptor = ET.SubElement(encabezado, "Receptor")
    _node(receptor, "RUTRecep", RUT_CONSUMIDOR_FINAL)
    _node(receptor, "RznSocRecep", NOMBRE_CONSUMIDOR_FINAL)

    totales = ET.SubElement(encabezado, "Totales")
    _node(totales, "MntNeto", int(totals["monto_neto"]))
    _node(totales, "MntExe", int(totals["monto_exento"]))
    _node(totales, "IVA", int(totals["iva"]))
    _node(totales, "MntTotal", int(totals["monto_total"]))

    for line_number, item in enumerate(case.items, start=1):
        detalle = ET.SubElement(documento, "Detalle")
        _node(detalle, "NroLinDet", line_number)
        if item.exento:
            _node(detalle, "IndExe", 1)
        _node(detalle, "NmbItem", item.nombre)
        _node(detalle, "QtyItem", _format_decimal(item.cantidad))
        if item.unidad_medida:
            _node(detalle, "UnmdItem", item.unidad_medida)
        _node(detalle, "PrcItem", int(item.precio_unitario_con_iva))
        _node(detalle, "MontoItem", int(item.monto_item))

    referencia = ET.SubElement(documento, "Referencia")
    _node(referencia, "NroLinRef", 1)
    _node(referencia, "CodRef", "SET")
    _node(referencia, "RazonRef", case.codigo)

    return _xml_bytes(dte)


def render_sobre_set_boleta_xml(
    cases: list[BoletaSetCase],
    *,
    config: ConfiguracionBoletaSii,
    folio_inicial: int,
    fecha_emision: date,
    rut_envia: str,
    rut_receptor: str = RUT_RECEPTOR_SII,
) -> bytes:
    ET.register_namespace("", SII_NS)
    ET.register_namespace("xsi", XSI_NS)

    root = ET.Element(
        "EnvioBOLETA",
        {
            "xmlns": SII_NS,
            "xmlns:xsi": XSI_NS,
            "version": "1.0",
        },
    )
    set_dte = ET.SubElement(root, "SetDTE", ID="SetDoc")
    caratula = ET.SubElement(set_dte, "Caratula", version="1.0")
    _node(caratula, "RutEmisor", _safe_rut(config.rut_emisor))
    _node(caratula, "RutEnvia", _safe_rut(rut_envia))
    _node(caratula, "RutReceptor", _safe_rut(rut_receptor))
    _node(caratula, "FchResol", config.resolucion_fecha.isoformat() if config.resolucion_fecha else "")
    _node(caratula, "NroResol", config.resolucion_numero or "")
    _node(caratula, "TmstFirmaEnv", _timestamp())

    subtotal = ET.SubElement(caratula, "SubTotDTE")
    _node(subtotal, "TpoDTE", 39)
    _node(subtotal, "NroDTE", len(cases))

    for offset, case in enumerate(cases):
        dte_xml = render_boleta_set_xml(
            case,
            config=config,
            folio=folio_inicial + offset,
            fecha_emision=fecha_emision,
        )
        set_dte.append(ET.fromstring(dte_xml))

    return _xml_bytes(root)


def totales_set_boleta(cases: list[BoletaSetCase]) -> dict[str, Decimal | int]:
    acumulado = {
        "monto_neto": Decimal("0"),
        "iva": Decimal("0"),
        "monto_exento": Decimal("0"),
        "monto_total": Decimal("0"),
        "folios_emitidos": len(cases),
        "folios_utilizados": len(cases),
        "folios_anulados": 0,
    }
    for case in cases:
        totals = totales_boleta_set_case(case)
        acumulado["monto_neto"] += totals["monto_neto"]
        acumulado["iva"] += totals["iva"]
        acumulado["monto_exento"] += totals["monto_exento"]
        acumulado["monto_total"] += totals["monto_total"]
    return acumulado


def render_rcof_set_boleta_xml(
    cases: list[BoletaSetCase],
    *,
    config: ConfiguracionBoletaSii,
    fecha_emision: date,
    rut_envia: str,
) -> bytes:
    totals = totales_set_boleta(cases)
    ET.register_namespace("", SII_NS)
    ET.register_namespace("xsi", XSI_NS)

    root = ET.Element(
        "ConsumoFolios",
        {
            "xmlns": SII_NS,
            "xmlns:xsi": XSI_NS,
            "version": "1.0",
        },
    )
    documento = ET.SubElement(root, "DocumentoConsumoFolios", ID="RCOFSetBoleta")
    caratula = ET.SubElement(documento, "Caratula", version="1.0")
    _node(caratula, "RutEmisor", _safe_rut(config.rut_emisor))
    _node(caratula, "RutEnvia", _safe_rut(rut_envia))
    _node(caratula, "FchResol", config.resolucion_fecha.isoformat() if config.resolucion_fecha else "")
    _node(caratula, "NroResol", config.resolucion_numero or "")
    _node(caratula, "FchInicio", fecha_emision.isoformat())
    _node(caratula, "FchFinal", fecha_emision.isoformat())
    _node(caratula, "SecEnvio", 1)
    _node(caratula, "TmstFirmaEnv", _timestamp())

    resumen = ET.SubElement(documento, "Resumen")
    _node(resumen, "TipoDocumento", 39)
    _node(resumen, "MntNeto", int(totals["monto_neto"]))
    _node(resumen, "MntIva", int(totals["iva"]))
    _node(resumen, "TasaIVA", 19)
    _node(resumen, "MntExento", int(totals["monto_exento"]))
    _node(resumen, "MntTotal", int(totals["monto_total"]))
    _node(resumen, "FoliosEmitidos", totals["folios_emitidos"])
    _node(resumen, "FoliosAnulados", totals["folios_anulados"])
    _node(resumen, "FoliosUtilizados", totals["folios_utilizados"])

    return _xml_bytes(root)


def _format_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    return str(int(normalized)) if normalized == normalized.to_integral() else format(normalized, "f")


def generar_archivos_set_boleta(
    *,
    input_path: str | Path,
    output_dir: str | Path,
    config: ConfiguracionBoletaSii,
    folio_inicial: int,
    fecha_emision: date,
    rut_envia: str | None = None,
    rut_receptor: str = RUT_RECEPTOR_SII,
) -> dict:
    cases = parse_set_prueba_boleta_file(input_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    rut_envia = rut_envia or config.rut_emisor

    files = []
    for offset, case in enumerate(cases):
        folio = folio_inicial + offset
        xml_bytes = render_boleta_set_xml(
            case,
            config=config,
            folio=folio,
            fecha_emision=fecha_emision,
        )
        file_path = output / f"boleta_{case.codigo.lower()}_folio_{folio}.xml"
        file_path.write_bytes(xml_bytes)
        totals = totales_boleta_set_case(case)
        files.append(
            {
                "caso": case.codigo,
                "folio": folio,
                "archivo": str(file_path),
                "monto_neto": int(totals["monto_neto"]),
                "monto_exento": int(totals["monto_exento"]),
                "iva": int(totals["iva"]),
                "monto_total": int(totals["monto_total"]),
            }
        )

    sobre_path = output / "sobre_set_boletas.xml"
    sobre_path.write_bytes(
        render_sobre_set_boleta_xml(
            cases,
            config=config,
            folio_inicial=folio_inicial,
            fecha_emision=fecha_emision,
            rut_envia=rut_envia,
            rut_receptor=rut_receptor,
        )
    )

    rcof_path = output / "rcof_set_boletas.xml"
    rcof_path.write_bytes(
        render_rcof_set_boleta_xml(
            cases,
            config=config,
            fecha_emision=fecha_emision,
            rut_envia=rut_envia,
        )
    )
    total_set = totales_set_boleta(cases)

    summary = {
        "tipo_set": "boleta_electronica",
        "input": str(input_path),
        "output_dir": str(output),
        "rut_emisor": _safe_rut(config.rut_emisor),
        "rut_envia": _safe_rut(rut_envia),
        "sobre": str(sobre_path),
        "rcof": str(rcof_path),
        "totales_set": {
            "monto_neto": int(total_set["monto_neto"]),
            "iva": int(total_set["iva"]),
            "monto_exento": int(total_set["monto_exento"]),
            "monto_total": int(total_set["monto_total"]),
            "folios_emitidos": total_set["folios_emitidos"],
            "folios_utilizados": total_set["folios_utilizados"],
            "folios_anulados": total_set["folios_anulados"],
        },
        "folios": files,
    }
    (output / "resumen_set_boleta.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary
