
from django import forms
from .models import Observacion, VersionRegistro

class ObservacionForm(forms.ModelForm):
    class Meta:
        model  = Observacion
        fields = ['url', 'tipo', 'observacion']
        widgets = {
            'url': forms.HiddenInput(),
            'tipo': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'observacion': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Cuéntanos tu observación…'}),
        }
        labels = {
            'tipo': 'Tipo',
            'observacion': 'Observación',
        }

class ResolverObservacionForm(forms.Form):
    """
    Form para resolver una observacion:
    - impacto (SIN_CAMBIO/PATCH/MENOR/MAYOR)
    - resumen (corto)
    - detalle (descripcion de la solucion)
    - Muestra la proxima version calculada (solo lectura)
    """
    impacto = forms.ChoiceField(
        choices=VersionRegistro.IMPACTO,
        widget=forms.RadioSelect,
        label="Tipo de cambio / impacto"
    )
    resumen = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Resumen corto (aparece en HS de versiones)'}),
        label="Resumen"
    )
    detalle = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 6, 'placeholder': 'Describe la solución aplicada, archivos, vistas, modelos, migraciones, etc.'}),
        label="Detalle de la solución"
    )
    proxima_version = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
        label="Próxima versión (auto)"
    )
