from django import forms
from django.utils.html import strip_tags

from .html import sanitize_rich_text
from .models import ActaReunion


class ActaReunionForm(forms.ModelForm):
    class Meta:
        model = ActaReunion
        fields = ["fecha", "acta"]
        widgets = {
            "fecha": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "acta": forms.HiddenInput(),
        }

    def clean_acta(self):
        contenido = sanitize_rich_text(self.cleaned_data.get("acta"))
        if not strip_tags(contenido).strip():
            raise forms.ValidationError("Escribe el contenido del acta.")
        return contenido
