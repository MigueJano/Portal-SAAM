from calendar import monthrange
from datetime import date

from django import forms

from Apps.Pedidos.models import Categoria, Cliente, Producto, Proveedor


def ultimo_mes_natural(hoy: date | None = None) -> tuple[date, date]:
    """Retorna el primer y ultimo dia del mes calendario anterior."""
    hoy = hoy or date.today()
    if hoy.month == 1:
        year, month = hoy.year - 1, 12
    else:
        year, month = hoy.year, hoy.month - 1
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def inicio_tres_meses_naturales(hoy: date | None = None) -> date:
    """Primer dia del mes actual menos dos meses calendario."""
    hoy = hoy or date.today()
    year = hoy.year
    month = hoy.month - 2
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


class FiltroFinancieroForm(forms.Form):
    fecha_desde = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    fecha_hasta = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )

    def clean(self):
        data = super().clean()
        desde_default, hasta_default = ultimo_mes_natural()
        if not data.get("fecha_desde"):
            data["fecha_desde"] = desde_default
        if not data.get("fecha_hasta"):
            data["fecha_hasta"] = hasta_default
        if data["fecha_desde"] > data["fecha_hasta"]:
            data["fecha_desde"], data["fecha_hasta"] = (
                data["fecha_hasta"],
                data["fecha_desde"],
            )
        return data


class FiltroVentasForm(forms.Form):
    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.all().order_by("nombre_cliente"),
        required=False,
        label="Cliente",
    )
    categoria = forms.ModelChoiceField(
        queryset=Categoria.objects.all().order_by("categoria"),
        required=False,
        label="Categoría",
    )
    proveedor = forms.ModelChoiceField(
        queryset=Proveedor.objects.all().order_by("nombre_proveedor"),
        required=False,
        label="Proveedor",
    )
    MESES_CHOICES = (
        (3, "Últimos 3"),
        (6, "Últimos 6"),
        (9, "Últimos 9"),
        (12, "Últimos 12"),
    )
    meses = forms.ChoiceField(
        choices=MESES_CHOICES,
        initial=3,
        required=False,
        label="Meses",
    )

    def clean_meses(self) -> int:
        valor = self.cleaned_data.get("meses")
        try:
            return int(valor) if valor not in (None, "") else 3
        except (TypeError, ValueError):
            return 3

    def rango_fechas_o_meses(self):
        hoy = date.today()
        n = self.cleaned_data.get("meses") or 3
        try:
            n = int(n)
        except (TypeError, ValueError):
            n = 3
        y, m = hoy.year, hoy.month - (n - 1)
        while m <= 0:
            m += 12
            y -= 1
        inicio = date(y, m, 1)
        fin = hoy
        return inicio, fin


class FiltroProductosForm(forms.Form):
    UNIDAD_CHOICES = (
        ("PRIMARIO", "Primaria"),
        ("SECUNDARIO", "Secundaria"),
    )

    fecha_desde = forms.DateField(
        required=False,
        label="Desde",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    fecha_hasta = forms.DateField(
        required=False,
        label="Hasta",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    producto = forms.ModelChoiceField(
        queryset=Producto.objects.all().order_by("nombre_producto", "codigo_producto_interno"),
        required=False,
        label="Producto",
    )
    unidad = forms.ChoiceField(
        choices=UNIDAD_CHOICES,
        initial="PRIMARIO",
        required=False,
        label="Cantidad en",
    )

    def clean(self):
        data = super().clean()
        hoy = date.today()
        data["fecha_desde"] = data.get("fecha_desde") or inicio_tres_meses_naturales(hoy)
        data["fecha_hasta"] = data.get("fecha_hasta") or hoy
        if data["fecha_desde"] > data["fecha_hasta"]:
            data["fecha_desde"], data["fecha_hasta"] = (
                data["fecha_hasta"],
                data["fecha_desde"],
            )
        data["unidad"] = data.get("unidad") or "PRIMARIO"
        return data
