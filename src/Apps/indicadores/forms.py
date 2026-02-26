# Apps/indicadores/forms.py
from django import forms
from datetime import date

from Apps.Pedidos.models import Cliente, Categoria, Proveedor

class FiltroFinancieroForm(forms.Form):
    fecha_desde = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    fecha_hasta = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )

    def clean(self):
        data = super().clean()
        hoy = date.today()

        # Defaults: primer día del mes actual → hoy
        if not data.get('fecha_desde'):
            data['fecha_desde'] = hoy.replace(day=1)
        if not data.get('fecha_hasta'):
            data['fecha_hasta'] = hoy

        # Normaliza por si vienen invertidas
        if data['fecha_desde'] > data['fecha_hasta']:
            data['fecha_desde'], data['fecha_hasta'] = data['fecha_hasta'], data['fecha_desde']

        return data

class FiltroVentasForm(forms.Form):
    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.all().order_by('nombre_cliente'),
        required=False,
        label="Cliente"
    )
    categoria = forms.ModelChoiceField(
        queryset=Categoria.objects.all().order_by('categoria'),
        required=False,
        label="Categoría"
    )
    proveedor = forms.ModelChoiceField(                     # 👈 NUEVO
        queryset=Proveedor.objects.all().order_by('nombre_proveedor'),
        required=False,
        label="Proveedor"
    )
    MESES_CHOICES = (
        (3,  "Últimos 3"),
        (6,  "Últimos 6"),
        (9,  "Últimos 9"),
        (12, "Últimos 12"),
    )
    meses = forms.ChoiceField(
        choices=MESES_CHOICES,
        initial=3,
        required=False,
        label="Meses"
    )

    def clean_meses(self) -> int:
        valor = self.cleaned_data.get('meses')
        try:
            return int(valor) if valor not in (None, "") else 3
        except (TypeError, ValueError):
            return 3

    def rango_fechas_o_meses(self):
        hoy = date.today()
        n = self.cleaned_data.get('meses') or 3
        try:
            n = int(n)
        except (TypeError, ValueError):
            n = 3

        # primer día del mes de (n-1) meses atrás
        y, m = hoy.year, hoy.month - (n - 1)
        while m <= 0:
            m += 12
            y -= 1
        inicio = date(y, m, 1)
        fin = hoy
        return inicio, fin
