from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.contrib.staticfiles.views import serve as static_serve
from django.views.generic import RedirectView
from django.urls import re_path


urlpatterns = [
    path("", RedirectView.as_view(pattern_name="home", permanent=False)),
    path("admin/", admin.site.urls),
    path("auth/", include("Apps.usuarios.urls")),
    path("pedidos/", include("Apps.Pedidos.urls")),
    path("ajax/", include("Apps.Pedidos.urls_ajax")),
    path("indicadores/", include("Apps.indicadores.urls")),
    path("observaciones/", include("Apps.observaciones.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += staticfiles_urlpatterns()
else:
    urlpatterns += [
        re_path(r"^static/(?P<path>.*)$", static_serve, {"insecure": True}),
    ]
