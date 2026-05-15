from .models import VersionRegistro

def obtener_version_actual():
    """
    Devuelve (X, Y, Z) de la última versión registrada.
    Si no hay registros, parte en 0.0.0.
    """
    ultimo = VersionRegistro.objects.order_by('-creado_en', '-id').first()
    if not ultimo:
        return (0, 0, 0)
    return (ultimo.version_mayor, ultimo.version_menor, ultimo.version_patch)

def calcular_siguiente_version(impacto: str):
    """
    Aplica SemVer:
      - SIN_CAMBIO => X.Y.Z
      - PATCH => X.Y.(Z+1)
      - MENOR => X.(Y+1).0
      - MAYOR => (X+1).0.0
    Si no hay versión previa, se parte desde:
      - SIN_CAMBIO => 0.0.0
      - PATCH => 0.0.1
      - MENOR => 0.1.0
      - MAYOR => 1.0.0
    """
    x, y, z = obtener_version_actual()

    if impacto == 'SIN_CAMBIO':
        return (x, y, z)

    if (x, y, z) == (0, 0, 0):
        if impacto == 'PATCH':
            return (0, 0, 1)
        elif impacto == 'MENOR':
            return (0, 1, 0)
        else:
            return (1, 0, 0)

    if impacto == 'PATCH':
        return (x, y, z + 1)
    elif impacto == 'MENOR':
        return (x, y + 1, 0)
    else:  # MAYOR
        return (x + 1, 0, 0)
