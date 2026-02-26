"""
Vistas de la app usuarios.

Incluye funciones para login, logout y descarga de base de datos (respaldo manual).
"""

from django.shortcuts import render, redirect, resolve_url
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.conf import settings
from django.http import FileResponse
import os


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
