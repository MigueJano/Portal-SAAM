from django import forms
from django.utils import timezone
from datetime import timedelta

from Apps.Pedidos.models import Cliente, Contacto, Pedido
from Apps.integraciones.models import ConciliacionPago, FiltroCompraAgil


class CorreoForm(forms.Form):
    destinatario = forms.EmailField(label="Destinatario")
    asunto = forms.CharField(max_length=255)
    cuerpo = forms.CharField(widget=forms.Textarea(attrs={"rows": 9}))
    adjuntos = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"multiple": False}),
        help_text="Puede adjuntar un documento por envío.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class ConciliacionManualForm(forms.ModelForm):
    class Meta:
        model = ConciliacionPago
        fields = ("pedido", "monto_aplicado")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pedido"].queryset = Pedido.objects.filter(estado_pedido="Entregado").select_related("nombre_cliente")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control form-control-sm")


class ConsultaBancoForm(forms.Form):
    desde = forms.DateField(
        label="Desde",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control form-control-sm"}),
    )
    hasta = forms.DateField(
        label="Hasta",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control form-control-sm"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        hoy = timezone.localdate()
        self.fields["desde"].initial = hoy - timedelta(days=7)
        self.fields["hasta"].initial = hoy

    def clean(self):
        cleaned = super().clean()
        desde = cleaned.get("desde")
        hasta = cleaned.get("hasta")
        if desde and hasta and desde > hasta:
            raise forms.ValidationError("La fecha inicial no puede ser posterior a la fecha final.")
        if desde and hasta and (hasta - desde).days > 366:
            raise forms.ValidationError("Para esta prueba seleccione un período máximo de 366 días.")
        return cleaned


def destinatarios_disponibles():
    clientes = Cliente.objects.filter(cliente_activo=True).exclude(correo_cliente="").values_list(
        "nombre_cliente", "correo_cliente"
    )
    contactos = Contacto.objects.select_related("proveedor").exclude(correo_contacto="")
    filas = [("Cliente", nombre, correo) for nombre, correo in clientes]
    filas.extend(
        ("Proveedor", f"{c.proveedor.nombre_proveedor} - {c.nombre_contacto} {c.apellido_contacto}", c.correo_contacto)
        for c in contactos
    )
    return sorted(filas, key=lambda fila: (fila[0], fila[1].lower()))


class FiltroCompraAgilForm(forms.ModelForm):
    regiones = forms.MultipleChoiceField(
        label="Regiones",
        choices=FiltroCompraAgil.REGIONES,
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": 8}),
        help_text="Sin selección consulta todas las regiones.",
    )
    estados = forms.MultipleChoiceField(
        label="Estados de Mercado Público",
        choices=FiltroCompraAgil.ESTADOS_API,
        required=False,
        initial=["publicada"],
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = FiltroCompraAgil
        fields = (
            "nombre",
            "activo",
            "regiones",
            "lugar",
            "palabras_clave",
            "estados",
            "monto_minimo",
            "monto_maximo",
        )
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control"}),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "lugar": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Ej.: Santiago, Providencia"}
            ),
            "palabras_clave": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 5,
                    "placeholder": "garantía\nequipamiento médico\nreactivos",
                }
            ),
            "monto_minimo": forms.NumberInput(attrs={"class": "form-control", "min": 0, "step": "0.01"}),
            "monto_maximo": forms.NumberInput(attrs={"class": "form-control", "min": 0, "step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial["regiones"] = [str(valor) for valor in self.instance.regiones]
            self.initial["estados"] = self.instance.estados

    def clean_regiones(self):
        return [int(valor) for valor in self.cleaned_data["regiones"]]

    def clean_estados(self):
        return self.cleaned_data["estados"] or ["publicada"]

    def clean(self):
        cleaned = super().clean()
        minimo = cleaned.get("monto_minimo")
        maximo = cleaned.get("monto_maximo")
        if minimo is not None and maximo is not None and minimo > maximo:
            self.add_error("monto_maximo", "El monto máximo debe ser igual o mayor al mínimo.")
        return cleaned

