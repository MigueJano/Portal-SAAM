"""
Vistas de la app usuarios.

Incluye funciones para login, logout y descarga de base de datos (respaldo manual).
"""

from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login, logout
from django.db.utils import OperationalError, ProgrammingError
from django.http import FileResponse
from django.shortcuts import redirect, render, resolve_url

from .models import ClonacionBaseDatos
from .services import (
    clone_sqlite_database,
    database_environment_paths,
    env_override_active,
    identify_database_environment,
    read_runtime_database_selection,
    runtime_selection_file,
    sqlite_db_file_info,
    switch_current_process_database,
    write_runtime_database_selection,
)


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


@staff_member_required
def clonar_base_datos(request):
    db_config = settings.DATABASES.get("default", {})
    engine = db_config.get("ENGINE", "")
    db_name = db_config.get("NAME")

    if not db_name:
        messages.error(request, "No hay base de datos configurada.")
        return redirect("home")

    base_activa_path = Path(db_name).expanduser().resolve()
    base_pruebas_path = (Path(settings.BASE_DIR) / "Database" / "pruebas" / "SAAM.db").resolve()
    clones_dir = (Path(settings.BASE_DIR) / "Database" / "clones").resolve()
    env_paths = database_environment_paths(settings.BASE_DIR)
    current_environment = identify_database_environment(base_activa_path, settings.BASE_DIR)
    runtime_selection = read_runtime_database_selection(settings.BASE_DIR)
    selection_file = runtime_selection_file(settings.BASE_DIR)
    db_override = env_override_active()

    if request.method == "POST":
        action = request.POST.get("action", "clone")

        if action == "switch_environment":
            if engine != "django.db.backends.sqlite3":
                messages.error(request, "El cambio de entorno web está disponible solo para bases SQLite.")
                return redirect("clonar_base_datos")
            if db_override:
                messages.warning(
                    request,
                    "Existe una variable DJANGO_DB_NAME activa. El cambio web no puede sobreescribir ese entorno.",
                )
                return redirect("clonar_base_datos")

            environment = request.POST.get("environment", "").strip().lower()
            if environment not in env_paths:
                messages.error(request, "Selecciona un entorno válido.")
                return redirect("clonar_base_datos")

            target_path = env_paths[environment]
            if not target_path.exists():
                messages.error(
                    request,
                    f"No existe la base para el entorno seleccionado: {target_path}. Clona primero la base de pruebas.",
                )
                return redirect("clonar_base_datos")

            write_runtime_database_selection(environment, settings.BASE_DIR)
            switch_current_process_database(target_path)

            backend = request.session.get("_auth_user_backend") or "django.contrib.auth.backends.ModelBackend"
            login(request, request.user, backend=backend)

            messages.success(
                request,
                f"Entorno activo cambiado a {environment}. La aplicación ahora usa {target_path}.",
            )
            return redirect("clonar_base_datos")

        if engine != "django.db.backends.sqlite3":
            messages.error(request, "La clonación web está disponible solo para bases SQLite.")
            return redirect("clonar_base_datos")
        if not base_activa_path.exists():
            messages.error(request, "No se encontró la base de datos activa para clonar.")
            return redirect("clonar_base_datos")

        resultado = clone_sqlite_database(
            source=base_activa_path,
            target=base_pruebas_path,
            archive_dir=clones_dir,
        )
        source_info = resultado["source"]
        target_info = resultado["target"]
        snapshot_info = resultado["snapshot"] or {}

        try:
            ClonacionBaseDatos.objects.create(
                usuario=request.user,
                motor_base=engine,
                origen_path=source_info["path"],
                destino_path=target_info["path"],
                snapshot_path=snapshot_info.get("path", ""),
                base_activa_actualizada_at=source_info["updated_at"],
                base_activa_size_bytes=source_info["size_bytes"],
                destino_size_bytes=target_info["size_bytes"],
            )
            messages.success(
                request,
                f"Clonación completada. Base de pruebas actualizada en {target_info['path']}.",
            )
        except (OperationalError, ProgrammingError):
            messages.warning(
                request,
                "La clonación se realizó, pero no fue posible guardar el historial. Ejecuta las migraciones pendientes.",
            )
        return redirect("clonar_base_datos")

    historial = []
    historial_disponible = True
    historial_error = ""
    try:
        historial = list(ClonacionBaseDatos.objects.select_related("usuario").all()[:30])
    except (OperationalError, ProgrammingError):
        historial_disponible = False
        historial_error = "La tabla de historial aún no existe. Ejecuta `python manage.py migrate` en esta base."

    return render(
        request,
        "usuarios/clonar_base_datos.html",
        {
            "engine": engine,
            "base_activa": sqlite_db_file_info(base_activa_path) if engine == "django.db.backends.sqlite3" else None,
            "base_pruebas": sqlite_db_file_info(base_pruebas_path),
            "clones_dir": str(clones_dir),
            "db_pruebas_relpath": "Database/pruebas/SAAM.db",
            "env_paths": {key: str(path) for key, path in env_paths.items()},
            "current_environment": current_environment,
            "runtime_selection": runtime_selection,
            "selection_file": str(selection_file),
            "db_override_active": db_override,
            "historial": historial,
            "historial_disponible": historial_disponible,
            "historial_error": historial_error,
            "clonacion_habilitada": engine == "django.db.backends.sqlite3",
        },
    )
