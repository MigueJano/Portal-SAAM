"""
Contacto - Vistas para gestionar contactos asociados a proveedores.

Este módulo incluye:
- Listado general de contactos.
- Creación de contacto independiente o desde un proveedor.
- Edición y eliminación de contactos.
- Asociación directa de contactos a un proveedor específico.

Fecha de documentación: 2025-08-08
Autor: Miguel Plasencia
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from Apps.Pedidos.models import Contacto, Proveedor
from Apps.Pedidos.forms import CrearContactoForm, AsociarContactoForm
from Apps.Pedidos.utils import lista_generica, eliminar_generica

# ------------------------------------------------------------------
# Lista de contactos
# ------------------------------------------------------------------

def lista_contacto(request):
    """
    Muestra todos los contactos registrados en el sistema.

    Utiliza la función genérica `lista_generica`.

    Returns:
        HttpResponse: Página con la tabla de contactos.

    Template:
        ./views/contacto/lista_contacto.html
    """
    return lista_generica(request, Contacto, './views/contacto/lista_contacto.html', 'contactos')


# ------------------------------------------------------------------
# Crear contacto (independiente o desde proveedor)
# ------------------------------------------------------------------

def crear_contacto(request):
    """
    Vista para registrar un nuevo contacto.

    Si se accede desde un proveedor (por parámetro GET), se inicializa el
    formulario con ese proveedor.

    Args:
        request (HttpRequest): Solicitud HTTP.

    Returns:
        HttpResponse: Página con el formulario de creación.

    Template:
        ./views/contacto/crear_contacto.html
    """
    proveedores = Proveedor.objects.all()
    proveedor_id = request.GET.get('proveedor')

    if request.method == 'POST':
        form = CrearContactoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Contacto guardado correctamente.")
            return redirect('lista_contacto')
        else:
            for error in form.errors.values():
                messages.error(request, error)
    else:
        form = CrearContactoForm()
        if proveedor_id:
            try:
                proveedor_obj = Proveedor.objects.get(id=proveedor_id)
                form.fields['proveedor'].initial = proveedor_obj
            except Proveedor.DoesNotExist:
                pass

    return render(request, './views/contacto/crear_contacto.html', {
        'form': form,
        'proveedores': proveedores
    })


# ------------------------------------------------------------------
# Asociar contacto directamente a proveedor
# ------------------------------------------------------------------

def asociar_contacto(request, proveedor_id):
    proveedor = get_object_or_404(Proveedor, id=proveedor_id)

    if request.method == 'POST':
        form = AsociarContactoForm(request.POST, initial={'proveedor': proveedor})
        if form.is_valid():
            contacto = form.save(commit=False)
            contacto.proveedor = proveedor
            contacto.save()
            messages.success(request, "Contacto asociado correctamente.")
            return redirect('lista_contacto')
        else:
            for error in form.errors.values():
                messages.error(request, error)
    else:
        form = AsociarContactoForm()

    return render(request, './views/contacto/asociar_contacto.html', {
        'form': form,
        'proveedor': proveedor
    })

# ------------------------------------------------------------------
# Editar contacto
# ------------------------------------------------------------------

def editar_contacto(request, id):
    """
    Modifica la información de un contacto existente.

    Args:
        id (int): ID del contacto a modificar.

    Returns:
        HttpResponse: Página con formulario de edición.

    Template:
        ./views/contacto/editar_contacto.html
    """
    proveedores = Proveedor.objects.all()
    contacto = get_object_or_404(Contacto, id=id)
    form = CrearContactoForm(request.POST or None, instance=contacto)

    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, "Contacto actualizado correctamente.")
            return redirect('lista_contacto')
        else:
            for error in form.errors.values():
                messages.error(request, error)

    return render(request, './views/contacto/editar_contacto.html', {
        'form': form,
        'contacto': contacto,
        'proveedores': proveedores
    })


# ------------------------------------------------------------------
# Eliminar contacto
# ------------------------------------------------------------------

def eliminar_contacto(request, id):
    """
    Elimina un contacto del sistema utilizando vista genérica.

    Args:
        id (int): ID del contacto a eliminar.

    Returns:
        HttpResponseRedirect: Redirige a 'lista_contacto' tras la eliminación.
    """
    return eliminar_generica(request, Contacto, id, 'lista_contacto')
