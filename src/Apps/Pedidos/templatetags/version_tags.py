# Apps/observaciones/templatetags/version_tags.py
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django import template
from django.contrib.staticfiles import finders
from django.core.cache import cache
from django.templatetags.static import static

from Apps.observaciones.models import VersionRegistro

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


@register.simple_tag
def static_version(path):
    """
    Agrega un querystring basado en la fecha de modificaciOn del archivo
    para evitar cachE del navegador durante pruebas y despliegues simples.
    """
    url = static(path)
    asset_path = finders.find(path)
    if not asset_path:
        return url

    try:
        version = str(int(Path(asset_path).stat().st_mtime))
    except OSError:
        return url

    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.append(("v", version))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
