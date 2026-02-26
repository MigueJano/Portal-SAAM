#!/usr/bin/env python
"""
manage.py

Herramienta de línea de comandos para ejecutar tareas administrativas de Django,
como correr el servidor de desarrollo, migraciones, manejo de usuarios, etc.

Este archivo debe ejecutarse desde la raíz del proyecto.
"""

import os
import sys


def main():
    """
    Ejecuta tareas administrativas de Django.

    Configura la variable de entorno para los ajustes del proyecto Django y
    delega la ejecución al manejador de comandos de Django.

    Lanza una excepción con un mensaje detallado si Django no está disponible
    en el entorno actual (por ejemplo, si no está activado el entorno virtual).

    Returns:
        None
    """
    # Define el módulo de configuración predeterminado del proyecto
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Portal.settings')

    try:
        # Importa el manejador de comandos de Django
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        # Si Django no está instalado o hay error en la importación, muestra advertencia clara
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    # Ejecuta el comando pasado por línea de comandos (ej: runserver, migrate, etc.)
    execute_from_command_line(sys.argv)


# Punto de entrada del script
if __name__ == '__main__':
    main()
