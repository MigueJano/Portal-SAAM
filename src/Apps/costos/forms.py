from django import forms

from .models import AccionOperacional, CategoriaGasto, GastoRecepcion


class GastoRecepcionForm(forms.ModelForm):
    class Meta:
        model = GastoRecepcion
        fields = ("categoria", "descripcion", "monto_neto", "pedido", "refacturable")
        widgets = {
            "descripcion": forms.TextInput(attrs={"class": "form-control"}),
            "monto_neto": forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "0.01"}),
            "categoria": forms.Select(attrs={"class": "form-select"}),
            "pedido": forms.Select(attrs={"class": "form-select"}),
            "refacturable": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].queryset = CategoriaGasto.objects.filter(activa=True)
        self.fields["pedido"].required = False


class AccionOperacionalForm(forms.ModelForm):
    class Meta:
        model = AccionOperacional
        fields = ("nombre", "tipo_costo", "base_calculo", "minutos_estandar", "valor_hora", "costo_fijo_evento", "activa")
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control"}),
            "tipo_costo": forms.Select(attrs={"class": "form-select"}),
            "minutos_estandar": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "valor_hora": forms.NumberInput(attrs={"class": "form-control", "min": 0, "step": "0.01"}),
            "costo_fijo_evento": forms.NumberInput(attrs={"class": "form-control", "min": 0, "step": "0.01"}),
            "base_calculo": forms.Select(attrs={"class": "form-select"}),
            "activa": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class CategoriaGastoForm(forms.ModelForm):
    class Meta:
        model = CategoriaGasto
        fields = ("nombre", "activa")
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control"}),
            "activa": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
