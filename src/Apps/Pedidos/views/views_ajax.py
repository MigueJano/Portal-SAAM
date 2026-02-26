# Apps/Pedidos/views_ajax.py
from decimal import Decimal
from typing import Dict, Any

from django.http import JsonResponse
from django.db.models import Min
from django.views.decorators.http import require_GET
from django.shortcuts import get_object_or_404
from django.db.models.functions import Lower

from Apps.Pedidos.models import CodigoProveedor, Producto, Recepcion, Stock


@require_GET
def resolver_codigo_proveedor(request):
    """
    GET params:
      - code (obligatorio): código externo del proveedor (string)
      - recepcion_id (opcional): si viene, se filtra por proveedor de la recepción
      - proveedor_id (opcional): alternativo a recepcion_id
    Respuesta:
      { ok: True,
        producto: { id, codigo_interno, nombre },
        empaques: [ {nivel, nombre}, ... ]
      }
    """
    code = (request.GET.get('code') or '').strip()
    if not code:
        return JsonResponse({'ok': False, 'error': 'Falta parámetro code'}, status=400)

    proveedor_id = request.GET.get('proveedor_id')
    recepcion_id = request.GET.get('recepcion_id')

    # Si viene recepcion_id, prioriza su proveedor
    if recepcion_id and recepcion_id.isdigit():
        try:
            rec = Recepcion.objects.select_related('proveedor').only('id', 'proveedor_id').get(pk=int(recepcion_id))
            proveedor_id = rec.proveedor_id
        except Recepcion.DoesNotExist:
            pass

    qs = CodigoProveedor.objects.select_related('producto')
    if proveedor_id and str(proveedor_id).isdigit():
        qs = qs.filter(proveedor_id=int(proveedor_id))

    cp = (
        qs.annotate(code_lc=Lower('codigo_proveedor'))
          .filter(code_lc=code.lower())
          .select_related('producto')
          .first()
    )

    if not cp:
        return JsonResponse({'ok': False, 'error': 'Código no encontrado'}, status=404)

    p: Producto = cp.producto

    empaques = []
    if getattr(p, 'empaque_primario_id', None):
        empaques.append({'nivel': 'PRIMARIO',  'nombre': p.empaque_primario.nombre})
    if getattr(p, 'empaque_secundario_id', None):
        empaques.append({'nivel': 'SECUNDARIO','nombre': p.empaque_secundario.nombre})
    if getattr(p, 'empaque_terciario_id', None):
        empaques.append({'nivel': 'TERCIARIO', 'nombre': p.empaque_terciario.nombre})

    return JsonResponse({
        'ok': True,
        'producto': {
            'id': p.id,
            'codigo_interno': p.codigo_producto_interno,
            'nombre': p.nombre_producto,
        },
        'empaques': empaques,
    })


@require_GET
def ajax_precio_base_compra(request, producto_id: int):
    """
    Devuelve precio base de compra (unitario) y factores de empaque.
    Respuesta:
      {
        "success": True,
        "precio_unitario": 123.45,   # Decimal -> float
        "qty_secundario": 12,
        "qty_terciario": 100
      }
    """
    try:
        # Referencia de compra: precio mínimo DISPONIBLE
        agg = (
            Stock.objects
            .filter(producto_id=producto_id, tipo_movimiento="DISPONIBLE")
            .aggregate(precio=Min("precio_unitario"))
        )
        precio_unitario = agg["precio"] if agg["precio"] is not None else Decimal("0.00")

        producto = get_object_or_404(
            Producto.objects.only('id', 'qty_secundario', 'qty_terciario'),
            id=producto_id
        )

        qty_sec = (producto.qty_secundario or 1) if (producto.qty_secundario or 0) > 0 else 1
        qty_ter = (producto.qty_terciario or 1)  if (producto.qty_terciario  or 0) > 0 else 1

        return JsonResponse({
            "success": True,
            "precio_unitario": float(precio_unitario),
            "qty_secundario": qty_sec,
            "qty_terciario": qty_ter,
        })

    except Producto.DoesNotExist:
        return JsonResponse({"success": False, "error": "Producto no encontrado"}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "error": f"Error inesperado: {e}"}, status=500)


@require_GET
def ajax_empaques_producto(request, producto_id: int):
    """
    Devuelve los empaques configurados para un producto.
    Respuesta:
      {
        "success": True,
        "empaques": [
          {"nivel": "PRIMARIO", "nombre": "Unidad"},
          {"nivel": "SECUNDARIO", "nombre": "Caja 12"},
          {"nivel": "TERCIARIO", "nombre": "Pallet"}
        ]
      }
    """
    try:
        producto = get_object_or_404(
            Producto.objects.select_related(
                'empaque_primario', 'empaque_secundario', 'empaque_terciario'
            ).only(
                'id', 'empaque_primario__nombre', 'empaque_secundario__nombre', 'empaque_terciario__nombre',
                'empaque_primario_id', 'empaque_secundario_id', 'empaque_terciario_id'
            ),
            id=producto_id
        )

        empaques: list[Dict[str, Any]] = []
        if getattr(producto, 'empaque_primario_id', None):
            empaques.append({"nivel": "PRIMARIO", "nombre": producto.empaque_primario.nombre})
        if getattr(producto, 'empaque_secundario_id', None):
            empaques.append({"nivel": "SECUNDARIO", "nombre": producto.empaque_secundario.nombre})
        if getattr(producto, 'empaque_terciario_id', None):
            empaques.append({"nivel": "TERCIARIO", "nombre": producto.empaque_terciario.nombre})

        return JsonResponse({"success": True, "empaques": empaques})

    except Producto.DoesNotExist:
        return JsonResponse({"success": False, "error": "Producto no encontrado"}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "error": f"Error inesperado: {e}"}, status=500)
