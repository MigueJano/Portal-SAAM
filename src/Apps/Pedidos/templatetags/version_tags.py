# Apps/observaciones/templatetags/version_tags.py
from django import template
from Apps.observaciones.models import VersionRegistro
from django.core.cache import cache

register = template.Library()

@register.simple_tag
def version_actual():
    """
    Retorna la versión como string 'X.Y.Z', cacheada 60s.
    """
    key = "observaciones:version_str"
    ver_str = cache.get(key)
    if ver_str is None:
        v = (VersionRegistro.objects
             .only("version_mayor", "version_menor", "version_patch")
             .order_by("-creado_en", "-id")
             .first())
        ver_str = f"{v.version_mayor}.{v.version_menor}.{v.version_patch}" if v else "0.0.0"
        cache.set(key, ver_str, 60)
    return ver_str
