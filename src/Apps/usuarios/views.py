"""
Vistas de la app usuarios.

Incluye funciones para login, logout y descarga de base de datos (respaldo manual).
"""

from django.shortcuts import render, redirect, resolve_url
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.conf import settings
from django.http import FileResponse
from pathlib import Path


def login_view(request):
    """
    Vista de inicio de sesión.

    Si el método es POST, intenta autenticar al usuario con las credenciales proporcionadas.
    Si son correctas, inicia sesión y redirige a la URL definida en LOGIN_REDIRECT_URL.

    Args:
        request (HttpRequest): La solicitud HTTP entrante.

    Returns:
        HttpResponse: Página de login o redirección si el login fue exitoso.
    """
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        # Autenticación del usuario
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect(resolve_url(settings.LOGIN_REDIRECT_URL))
        else:
            messages.error(request, 'Usuario o contraseña incorrectos.')

    # Si no es POST o autenticación falló, se muestra el formulario
    return render(request, 'usuarios/login.html')


def logout_view(request):
    """
    Cierra la sesión actual del usuario y redirige al login.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        HttpResponseRedirect: Redirección a la vista de login.
    """
    logout(request)
    return redirect('login')


@staff_member_required
def base_datos(request):
    """
    Descarga manual del archivo SQLite configurado como base de datos.
    """
    db_name = settings.DATABASES.get('default', {}).get('NAME')
    if not db_name:
        messages.error(request, "No hay base de datos configurada para descarga.")
        return redirect('home')

    db_path = Path(db_name)
    if not db_path.exists():
        messages.error(request, "No se encontró el archivo de base de datos.")
        return redirect('home')

    return FileResponse(
        db_path.open('rb'),
        as_attachment=True,
        filename=db_path.name,
        content_type='application/octet-stream'
    )
