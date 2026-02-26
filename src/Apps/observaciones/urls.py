from django.urls import path
from . import views

urlpatterns = [
    path('nuevo/', views.crear_observacion, name='crear_observacion'),
    path('lista/', views.lista_observaciones, name='lista_observaciones'),
    path('<int:pk>/resolver/', views.resolver_observacion, name='resolver_observacion'),
    path('<int:pk>/marcar-lista/', views.marcar_lista_observacion, name='marcar_lista_observacion'),
]
