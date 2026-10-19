from django import forms
from django.utils import timezone
from datetime import timedelta

from Apps.Pedidos.models import Cliente, Contacto, Pedido
from Apps.integraciones.models import ConciliacionPago


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

