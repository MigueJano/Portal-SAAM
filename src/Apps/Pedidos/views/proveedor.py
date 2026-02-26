"""
Proveedor - Vistas para la gestión de proveedores del sistema SAAM.

Incluye:
- Listado general.
- Creación y edición de proveedores.
- Eliminación con bitácora.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from Apps.Pedidos.models import Proveedor
from Apps.Pedidos.forms import CrearProveedorForm
from Apps.Pedidos.utils import lista_generica, eliminar_generica


def lista_proveedores(request):
    """
    Muestra una lista de todos los proveedores registrados en el sistema.

    Utiliza la función genérica `lista_generica` para renderizar la vista con los proveedores.

    Template:
        ./views/proveedor/lista_proveedores.html
    """
    return lista_generica(
        request,
        Proveedor,
        './views/proveedor/lista_proveedores.html',
        'proveedores'
    )

def crear_proveedor(request):
    """
    Permite crear un nuevo proveedor.

    Muestra un formulario con validación, y si es válido, guarda el proveedor y redirige.
    En caso de error, muestra mensajes de error.

    Template:
        ./views/proveedor/crear_proveedor.html
    """
    form = CrearProveedorForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, "Proveedor creado correctamente.")
            return redirect('lista_proveedores')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    return render(request, './views/proveedor/crear_proveedor.html', {'form': form})

def editar_proveedor(request, id):
    """
    Permite editar un proveedor existente.

    Carga los datos actuales del proveedor mediante su ID, y muestra el formulario.
    Si el formulario es válido, guarda los cambios y redirige.

    Args:
        id (int): ID del proveedor a editar.

    Template:
        ./views/proveedor/editar_proveedor.html
    """
    proveedor = get_object_or_404(Proveedor, pk=id)
    form = CrearProveedorForm(request.POST or None, instance=proveedor)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, "Proveedor actualizado correctamente.")
            return redirect('lista_proveedores')
        else:
            for error in form.errors.values():
                messages.error(request, error)
    return render(request, './views/proveedor/editar_proveedor.html', {'form': form, 'proveedor': proveedor})

def eliminar_proveedor(request, id):
    """
    Elimina un proveedor utilizando la función genérica con bitácora de eliminación.

    Args:
        id (int): ID del proveedor a eliminar.

    Redirige a:
        'lista_proveedores' al finalizar.
    """
    return eliminar_generica(request, Proveedor, id, 'lista_proveedores')
