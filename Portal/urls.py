from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView


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
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

