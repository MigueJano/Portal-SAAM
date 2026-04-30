"""
Filtros personalizados para uso en templates del sistema SAAM.

Incluye utilidades para:
- Multiplicación de valores.
- Formateo de números.
- Acceso a nombres de empaques.
- Cálculos porcentuales.
- Estilización de formularios.

Fecha de documentación: 2025-08-08
"""

from decimal import Decimal, ROUND_HALF_UP

from django import template

# Registro del sistema de filtros personalizados de Django
register = template.Library()

@register.filter
def multiply(value, arg):
    """
    Multiplica dos valores enteros.
    
    Args:
        value (int): primer valor entero.
        arg (int): segundo valor entero.
    
    Returns:
        int: resultado de la multiplicación o 0 si falla.
    """
    try:
        return int(value) * int(arg)
    except Exception:
        return 0


@register.filter
def mul(value, arg):
    """
    Multiplica dos valores decimales (floats).
    
    Args:
        value (float): primer valor.
        arg (float): segundo valor.
    
    Returns:
        float: producto decimal, o cadena vacía si ocurre error.
    """
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return ''


@register.filter
def formatear_miles(value):
    """
    Formatea un número separando los miles con punto.
    Ejemplo: 10000 -> "10.000"
    
    Args:
        value (int or float): valor numérico a formatear.
    
    Returns:
        str: número formateado con puntos como separador de miles.
    """
    try:
        valor_redondeado = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"{int(valor_redondeado):,}".replace(",", ".")
    except (ArithmeticError, ValueError, TypeError):
        return value


@register.filter
def get_empaque_nombre(categorias_empaque, nivel):
    """
    Retorna el nombre visible del empaque para un nivel dado.

    Args:
        categorias_empaque (QuerySet): lista de objetos CategoriaEmpaque.
        nivel (str): nivel del empaque ('PRIMARIO', 'SECUNDARIO', etc.).

    Returns:
        str or None: nombre del empaque si se encuentra, None si no.
    """
    for cat in categorias_empaque:
        if cat.nivel == nivel:
            return cat.nombre
    return None


@register.filter
def dividir(valor, divisor):
    """
    Divide dos valores flotantes y redondea el resultado a 2 decimales.

    Args:
        valor (float): dividendo.
        divisor (float): divisor.

    Returns:
        float: resultado de la división redondeado o 0 si error.
    """
    try:
        return round(float(valor) / float(divisor), 2) if divisor else 0
    except Exception:
        return 0


@register.filter
def dividir_porcentaje(valor, total):
    """
    Calcula el porcentaje de `valor` respecto a `total`.

    Redondea el resultado al entero más cercano.

    Args:
        valor (float): valor parcial.
        total (float): valor total.

    Returns:
        int: porcentaje como número entero.
    """
    try:
        porcentaje = (valor / total) * 100
        return round(porcentaje)
    except (ZeroDivisionError, TypeError):
        return 0


@register.filter(name='add_class')
def add_class(field, css):
    """
    Agrega una clase CSS personalizada a un campo de formulario.

    Args:
        field (BoundField): campo del formulario.
        css (str): clase CSS a agregar.

    Returns:
        Widget: campo renderizado con la clase agregada.
    """
    return field.as_widget(attrs={'class': css})

@register.filter
def get_item(d, key):
    """
    Devuelve d[key] para usar en plantillas: {{ dict|get_item:llave }}.
    Soporta dicts normales y defaultdicts. Si falla, retorna None.
    """
    try:
        return d.get(key)
    except Exception:
        try:
            return d[key]
        except Exception:
            return None
        
@register.filter
def restar(a, b):
    """
    Resta dos valores sin redondeo, pensado para luego formatear con formatear_miles.
    Ej: {{ total|restar:neto }}
    """
    try:
        return float(a) - float(b)
    except Exception:
        return 0
