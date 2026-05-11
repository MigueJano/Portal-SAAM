"""
Modelos del sistema SAAM - App Pedidos.

Define las entidades principales: proveedores, productos, clientes, cotizaciones,
pedidos, ventas, y todos los elementos necesarios para la gestión de stock,
recepciones y precios.
"""

from django.conf import settings
from django.db import models
from decimal import Decimal, ROUND_HALF_UP
from django.core.validators import MinValueValidator
from django.db.models.functions import Lower
from django.utils import timezone


IVA_TASA = Decimal('0.19')   # 19% Chile
DOS_DEC = Decimal('0.01')

class CategoriaEmpaque(models.Model):
    """
    Categoriza los tipos de empaque en tres niveles: primario, secundario y terciario.
    Ejemplo: 'Caja' (SECUNDARIO), 'Unidad' (PRIMARIO).
    """
    NIVELES = (
        ('PRIMARIO', 'Primario'),
        ('SECUNDARIO', 'Secundario'),
        ('TERCIARIO', 'Terciario'),
    )

    nombre = models.CharField(max_length=100)
    nivel = models.CharField(max_length=15, choices=NIVELES)

    class Meta:
        constraints = [
            # Unicidad por par (nombre, nivel)
            models.UniqueConstraint(
                fields=['nombre', 'nivel'],
                name='uniq_categoria_empaque_nombre_nivel'
            )
        ]
        ordering = ('id',)

    def __str__(self):
        return f"{self.nombre} ({self.nivel})"

class Proveedor(models.Model):
    """
    Almacena la información de proveedores de productos.
    Incluye datos de cuenta bancaria para pagos.
    """
    CUENTA_CHOICES = [
        ('Corriente', 'Corriente'),
        ('Vista', 'Vista'),
        ('Prepago', 'Prepago'),
        ('Ahorro', 'Ahorro'),
        ('RUT', 'RUT'),
    ]

    nombre_proveedor = models.CharField(max_length=30)
    rut_proveedor = models.CharField(max_length=20, unique=True)
    direccion_proveedor = models.CharField(max_length=100)
    direccion_bodega_proveedor = models.CharField(max_length=100)
    empresa_activa = models.BooleanField(default=True)
    banco_proveedor = models.CharField(max_length=20)
    cta_proveedor = models.CharField(max_length=10, choices=CUENTA_CHOICES)
    num_cuenta_proveedor = models.CharField(max_length=20)

    def __str__(self):
        return f"{self.nombre_proveedor} ({self.rut_proveedor})"

class Contacto(models.Model):
    """
    Representa un contacto asociado a un proveedor.
    """
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE)
    nombre_contacto = models.CharField(max_length=30)
    apellido_contacto = models.CharField(max_length=30)
    cargo_contacto = models.CharField(max_length=30)
    telefono_contacto = models.CharField(max_length=30)
    correo_contacto = models.CharField(max_length=50)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['proveedor', 'nombre_contacto', 'apellido_contacto', 'cargo_contacto'],
                name='uniq_contacto_por_proveedor_nombre_apellido_cargo'
            )
        ]

    def __str__(self):
        return f"{self.nombre_contacto} {self.apellido_contacto} - {self.cargo_contacto} en {self.proveedor}"

class Recepcion(models.Model):
    """
    Documento de ingreso de productos al sistema. Asociado a un proveedor.
    """

    ESTADO_PEDIDO_CHOICES = [
        ('Pendiente', 'Pendiente'),
        ('Recibido', 'Recibido'),
        ('Parcial', 'Parcial'),
        ('Rechazado', 'Rechazado'),
        ('Finalizado', 'Finalizado'),
    ]

    DOCUMENTO_PEDIDO_CHOICES = [
        ('Factura', 'Factura'),
        ('Guia de Despacho', 'Guía de Despacho'),
        ('Boleta', 'Boleta'),
        ('Credito', 'Crédito'),
    ]

    MONEDA_CHOICES = [
        ('CLP', 'CLP'),
        ('EUR', 'EUR'),
        ('US', 'US'),
        ('UF', 'UF'),
        ('UTM', 'UTM'),
    ]

    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE)
    fecha_recepcion = models.DateField()
    estado_recepcion = models.CharField(
        max_length=20,
        choices=ESTADO_PEDIDO_CHOICES,
        default='Pendiente'
    )
    documento_recepcion = models.CharField(max_length=20, choices=DOCUMENTO_PEDIDO_CHOICES)
    num_documento_recepcion = models.IntegerField()

    total_neto_recepcion = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )
    iva_recepcion = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )
    total_recepcion = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )

    incluir_iva = models.BooleanField(default=True)
    moneda_recepcion = models.CharField(max_length=4, choices=MONEDA_CHOICES)
    comentario_recepcion = models.TextField(blank=True, null=True)

    def actualizar_totales(self):
        """
        Recalcula IVA y Total a partir de total_neto_recepcion.
        NO vuelve a calcular el neto desde Stock.

        El flag incluir_iva solo indica si el valor ingresado originalmente
        ya incluia IVA y por lo tanto debio ser normalizado a neto antes.
        Una vez persistido el neto, el IVA del documento siempre se calcula
        sobre ese valor.
        """
        neto = (self.total_neto_recepcion or Decimal('0.00')).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
        iva = (neto * IVA_TASA).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
        total = (neto + iva).quantize(DOS_DEC, rounding=ROUND_HALF_UP)

        self.iva_recepcion = iva
        self.total_recepcion = total
        self.save(update_fields=['iva_recepcion', 'total_recepcion'])

    def __str__(self):
        return f"Recepción {self.num_documento_recepcion} - {self.proveedor} ({self.fecha_recepcion})"

class Categoria(models.Model):
    """
    Clasificación general del producto (ej. Bebidas, Alimentos).
    """
    categoria = models.CharField(max_length=30)

    def __str__(self):
        return self.categoria

class Subcategoria(models.Model):
    """
    Clasificación específica dentro de una categoría (ej. Gaseosas dentro de Bebidas).
    """
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE)
    subcategoria = models.CharField(max_length=30)

    def __str__(self):
        return f"{self.subcategoria} - {self.categoria}"

class Producto(models.Model):
    """
    Representa un producto del inventario.
    Incluye codificación, medidas, empaques y categorías.
    """
    UNIDAD_CHOICES = [
        ('cms', 'cms'),
        ('mts', 'mts'),
        ('cc', 'cc'),
        ('ml', 'ml'),
        ('lts', 'lts'),
        ('und', 'und'),
        ('kg', 'kg'),
        ('grs', 'grs'),
    ]

    categoria_producto = models.ForeignKey(Categoria, on_delete=models.CASCADE, blank=True, null=True)
    subcategoria_producto = models.ForeignKey(Subcategoria, on_delete=models.CASCADE, blank=True, null=True)
    codigo_producto_interno = models.CharField(max_length=10)
    nombre_producto = models.CharField(max_length=40)
    qty_terciario = models.IntegerField()
    qty_secundario = models.IntegerField()
    qty_primario = models.IntegerField()
    qty_unidad = models.IntegerField()
    medida = models.CharField(max_length=5, choices=UNIDAD_CHOICES)
    qty_minima = models.IntegerField()
    empaque_primario = models.ForeignKey('CategoriaEmpaque', on_delete=models.SET_NULL, null=True, blank=True, related_name='productos_primarios')
    empaque_secundario = models.ForeignKey('CategoriaEmpaque', on_delete=models.SET_NULL, null=True, blank=True, related_name='productos_secundarios')
    empaque_terciario = models.ForeignKey('CategoriaEmpaque', on_delete=models.SET_NULL, null=True, blank=True, related_name='productos_terciarios')

    def __str__(self):
        return f"{self.codigo_producto_interno} - {self.nombre_producto} ({self.qty_unidad} {self.medida})"

class CodigoProveedor(models.Model):
    """
    Mapea un código de producto dado por un proveedor a un Producto interno.
    Permite múltiples proveedores por producto y múltiples códigos por proveedor.
    """
    proveedor = models.ForeignKey(
        'Proveedor',
        on_delete=models.CASCADE,
        related_name='codigos_proveedor'
    )
    producto = models.ForeignKey(
        'Producto',
        on_delete=models.CASCADE,
        related_name='codigos_proveedor'
    )
    codigo_proveedor = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Código que el proveedor utiliza para este producto"
    )

    class Meta:
        constraints = [
            # Un código no puede repetirse para el mismo proveedor (case-insensitive)
            models.UniqueConstraint(
                Lower('codigo_proveedor'), 'proveedor',
                name='uniq_codigo_por_proveedor_ci'
            ),
        ]
        verbose_name = "Código de Proveedor"
        verbose_name_plural = "Códigos de Proveedor"

    def __str__(self):
        return f"{self.codigo_proveedor} - {self.proveedor} → {self.producto}"

class Stock(models.Model):
    """
    Movimientos de inventario: ingreso, reserva, salida.
    """
    UNIDAD_EMPAQUE = [
        ('PRIMARIO', 'Primario'),
        ('SECUNDARIO', 'Secundario'),
        ('TERCIARIO', 'Terciario'),
    ]

    MOVIMIENTO_CHOICES = [
        ('RECEPCION', 'Recepción'),
        ('DISPONIBLE', 'Disponible'),
        ('RESERVA', 'Reserva'),
        ('DESPACHO', 'Despacho'),
    ]

    tipo_movimiento = models.CharField(max_length=10, choices=MOVIMIENTO_CHOICES)
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    qty = models.IntegerField()
    empaque = models.CharField(max_length=10)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    fecha_movimiento = models.DateTimeField(auto_now_add=True)
    recepcion = models.ForeignKey('Recepcion', null=True, blank=True, on_delete=models.SET_NULL)
    pedido = models.ForeignKey('Pedido', null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        referencia = None
        if self.pedido_id:
            referencia = f"Pedido #{self.pedido_id}"
        elif self.recepcion_id:
            referencia = f"Recepcion #{self.recepcion_id}"

        detalle = f"{self.tipo_movimiento} - {self.producto} - {self.qty} ({self.empaque})"
        return f"{detalle} - {referencia}" if referencia else detalle


class MovimientoStockHistorico(models.Model):
    """
    Conserva el flujo operativo del stock por fila.

    Se usa para no perder trazabilidad cuando un registro de stock cambia
    de estado, por ejemplo desde RESERVA a DESPACHO.
    """

    stock = models.ForeignKey(
        "Stock",
        on_delete=models.CASCADE,
        related_name="historial_movimientos",
    )
    tipo_movimiento = models.CharField(max_length=10, choices=Stock.MOVIMIENTO_CHOICES)
    qty = models.IntegerField()
    empaque = models.CharField(max_length=10)
    precio_unitario = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    fecha_movimiento = models.DateTimeField(default=timezone.now, db_index=True)
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimientos_stock_historicos",
    )

    class Meta:
        ordering = ("fecha_movimiento", "id")
        indexes = [
            models.Index(fields=["fecha_movimiento"]),
            models.Index(fields=["tipo_movimiento", "fecha_movimiento"]),
        ]

    def __str__(self):
        referencia = None
        if self.stock and self.stock.pedido_id:
            referencia = f"Pedido #{self.stock.pedido_id}"
        elif self.stock and self.stock.recepcion_id:
            referencia = f"Recepcion #{self.stock.recepcion_id}"

        detalle = f"{self.tipo_movimiento} - Stock #{self.stock_id} - {self.qty} ({self.empaque})"
        return f"{detalle} - {referencia}" if referencia else detalle

class Cliente(models.Model):
    """
    Información de clientes del sistema (persona o empresa).
    """
    CATEGORIA = [
        ('PERSONA NATURAL', 'PERSONA NATURAL'),
        ('EMPRESA PRIVADA', 'EMPRESA PRIVADA'),
        ('EMPRESA PÚBLICA', 'EMPRESA PÚBLICA'),
        ('PYME', 'PYME'),
    ]

    nombre_cliente = models.CharField(max_length=50)
    rut_cliente = models.CharField(max_length=20, unique=True)
    direccion_cliente = models.CharField(max_length=100)
    direccion_bodega_cliente = models.CharField(max_length=100)
    cliente_activo = models.BooleanField(default=True)
    telefono_cliente = models.CharField(max_length=30)
    correo_cliente = models.CharField(max_length=50)
    categoria = models.CharField(max_length=20, choices=CATEGORIA)

    def __str__(self):
        return f"{self.nombre_cliente} ({self.rut_cliente})"

class ListaPrecios(models.Model):
    """
    Asociación entre cliente y precios por producto, por tipo de empaque.
    """
    UNIDAD_EMPAQUE = Stock.UNIDAD_EMPAQUE

    nombre_cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    nombre_producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    empaque = models.CharField(max_length=10)
    precio_venta = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    precio_iva = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    precio_total = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    vigencia = models.DateField()

    def __str__(self):
        return f"{self.nombre_cliente} - {self.nombre_producto} - {self.empaque} - {self.vigencia}"

class Cotizacion(models.Model):
    """
    Representa una cotización enviada a un cliente.
    Puede estar asociada a un pedido.
    """
    fecha_cotizacion = models.DateField()
    num_cotizacion = models.CharField(max_length=20, unique=True, blank=True)
    nombre_cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    archivo_pdf = models.FileField(upload_to='cotizaciones_pdfs/', blank=True, null=True)

    def save(self, *args, **kwargs):
        """
        Autogenera número de cotización si no está definido.
        Formato: YYYYMM-N°
        """
        if not self.num_cotizacion and self.fecha_cotizacion:
            año = self.fecha_cotizacion.year
            mes = self.fecha_cotizacion.strftime('%m')
            correlativo = Cotizacion.objects.filter(fecha_cotizacion__year=año).count() + 1
            self.num_cotizacion = f"{año}{mes}-{correlativo}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Cotizacion {self.num_cotizacion} - {self.nombre_cliente} - {self.fecha_cotizacion}"

class Pedido(models.Model):
    """
    Pedido realizado por un cliente, con opción de asociar a cotización.
    """
    ESTADO_PEDIDO_CHOICES = [
        ('Pendiente', 'Pendiente'),
        ('Entregado', 'Entregado'),
        ('Pagado', 'Pagado'),
        ('Finalizado', 'Finalizado'),
    ]

    nombre_cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    num_cotizacion = models.ForeignKey(Cotizacion, on_delete=models.CASCADE, null=True, blank=True)
    fecha_pedido = models.DateField()
    estado_pedido = models.CharField(max_length=10, choices=ESTADO_PEDIDO_CHOICES)
    comentario_pedido = models.TextField(blank=True, null=True)

    def referencia_pedido(self):
        return f"Pedido #{self.pk}" if self.pk else "Pedido sin ID"

    def __str__(self):
        partes = [self.referencia_pedido()]
        if self.nombre_cliente_id:
            partes.append(str(self.nombre_cliente))
        if self.fecha_pedido:
            partes.append(str(self.fecha_pedido))
        if self.num_cotizacion_id:
            partes.append(f"Cot. {self.num_cotizacion.num_cotizacion}")
        return " - ".join(partes)

class Venta(models.Model):
    """
    Representa la venta final de un pedido: incluye datos del documento de respaldo.
    """
    DOCUMENTO_PEDIDO_CHOICES = [
        ('Factura', 'Factura'),
        ('Guia de Despacho', 'Guía de Despacho'),
        ('Boleta', 'Boleta'),
        ('Credito', 'Crédito'),
    ]

    pedidoid = models.ForeignKey(Pedido, on_delete=models.CASCADE)
    fecha_venta = models.DateField()
    documento_pedido = models.CharField(max_length=20, choices=DOCUMENTO_PEDIDO_CHOICES)
    num_documento = models.IntegerField()
    venta_neto_pedido = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    venta_iva_pedido = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    venta_total_pedido = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    ganancia_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    ganancia_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])


    def __str__(self):
        partes = [f"Venta #{self.pk}" if self.pk else "Venta"]
        if self.pedidoid_id:
            partes.append(self.pedidoid.referencia_pedido())
            if self.pedidoid.nombre_cliente_id:
                partes.append(str(self.pedidoid.nombre_cliente))
        partes.append(f"{self.documento_pedido} #{self.num_documento}")
        return " - ".join(partes)

class UtilidadProducto(models.Model):
    # Enlace directo a la venta (muy conveniente para reportes)
    venta = models.ForeignKey('Venta', on_delete=models.CASCADE, related_name='utilidades', null=True, blank=True)

    # Clave del producto y su empaque
    producto = models.ForeignKey('Producto', on_delete=models.CASCADE)
    empaque = models.CharField(max_length=20)  # PRIMARIO / SECUNDARIO / TERCIARIO

    # Agregado por línea:
    cantidad = models.PositiveIntegerField(default=0)  # unidades primarias (normalizadas)

    # Valores unitarios (por UNIDAD PRIMARIA)
    precio_compra_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    precio_venta_unitario  = models.DecimalField(max_digits=12, decimal_places=2)

    # Utilidad unitaria y porcentaje (unitario)
    utilidad             = models.DecimalField(max_digits=12, decimal_places=2)  # unitario
    utilidad_porcentaje  = models.DecimalField(max_digits=6,  decimal_places=2)  # unitario %

    # Fecha del registro (puedes usar fecha de venta)
    fecha = models.DateTimeField()

    class Meta:
        # Evita duplicados exactos en una misma venta
        unique_together = (
            ('venta', 'producto', 'empaque', 'precio_compra_unitario', 'precio_venta_unitario'),
        )
        indexes = [
            models.Index(fields=['venta']),
            models.Index(fields=['producto']),
        ]

    def __str__(self):
        detalle = f"{self.producto} x{self.cantidad} ({self.empaque})"
        if self.venta_id and self.venta and self.venta.pedidoid_id:
            referencia = f"Utilidad #{self.pk}" if self.pk else "Utilidad"
            return f"{referencia} - {self.venta.pedidoid.referencia_pedido()} - {detalle}"
        referencia = f"Utilidad #{self.pk}" if self.pk else "Utilidad"
        return f"{referencia} - {detalle}"

class EntregaPedido(models.Model):
    pedido = models.ForeignKey('Pedido', on_delete=models.CASCADE, related_name='entregas')
    nombre_receptor = models.CharField(max_length=120)
    rut_receptor = models.CharField(max_length=20)
    fecha_entrega = models.DateTimeField()
    archivo_pdf = models.FileField(upload_to='entregas_pdf/%Y/%m/', blank=True, null=True)  # único archivo
    creado = models.DateTimeField(auto_now_add=True)
    foto = models.FileField(upload_to='entregas_fotos/%Y/%m/', blank=True, null=True)

    def __str__(self):
        partes = [f"Entrega #{self.id}" if self.id else "Entrega sin ID"]
        if self.pedido_id:
            partes.append(f"Pedido #{self.pedido_id}")
            if self.pedido and self.pedido.nombre_cliente_id:
                partes.append(str(self.pedido.nombre_cliente))
        return " - ".join(partes)

# --- Listas de Precios Predeterminadas ---------------------------------------

class ListaPreciosPredeterminada(models.Model):
    """
    Cabecera de una lista de precios predeterminada (plantilla base).
    Se usa para cargar ítems de precio por producto/empaque y luego
    importarlos/asignarlos a clientes específicos.
    """
    nombre_listaprecios = models.CharField(max_length=80, unique=True)
    descripcion_listaprecios = models.CharField(max_length=200, blank=True, default="")
    activa = models.BooleanField(default=True)

    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("nombre_listaprecios",)
        verbose_name = "Lista de Precios (Predeterminada)"
        verbose_name_plural = "Listas de Precios (Predeterminadas)"

    def __str__(self):
        return f"LP #{self.pk} - {self.nombre_listaprecios}" if self.pk else self.nombre_listaprecios


class ListaPreciosPredItem(models.Model):
    """
    Ítem de una ListaPreciosPredeterminada: define el precio por producto y empaque.
    Almacena precio neto, IVA y total (persistidos) y una fecha de vigencia.
    """
    listaprecios = models.ForeignKey(
        ListaPreciosPredeterminada,
        on_delete=models.CASCADE,
        related_name="items",
    )
    nombre_producto = models.ForeignKey(
        Producto,
        on_delete=models.CASCADE,
        related_name="precios_predeterminados",
    )

    # PRIMARIO / SECUNDARIO / TERCIARIO (normalizado a estos 3 niveles)
    empaque = models.CharField(max_length=15, choices=CategoriaEmpaque.NIVELES)

    # Precios persistidos (no se calculan al vuelo en las vistas)
    precio_venta = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))]
    )
    precio_iva = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        default=Decimal("0.00"),
    )
    precio_total = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        default=Decimal("0.00"),
    )

    vigencia = models.DateField()

    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["listaprecios", "nombre_producto", "empaque"],
                name="uniq_pred_lista_producto_empaque",
            )
        ]
        ordering = ("nombre_producto__nombre_producto", "empaque")
        verbose_name = "Ítem de Lista Predeterminada"
        verbose_name_plural = "Ítems de Lista Predeterminada"
        indexes = [
            models.Index(fields=["listaprecios"]),
            models.Index(fields=["nombre_producto"]),
            models.Index(fields=["vigencia"]),
        ]

    def __str__(self):
        referencia = f"LP Item #{self.pk}" if self.pk else "LP Item"
        return f"{referencia} - {self.listaprecios} - {self.nombre_producto} - {self.empaque} - {self.vigencia}"

    # -----------------------------
    # Helpers de negocio / display
    # -----------------------------
    def empaque_nombre(self) -> str:
        """
        Devuelve el nombre humano del empaque según la configuración del Producto.
        Si no hay categoría asignada, devuelve el nivel (PRIMARIO/SECUNDARIO/TERCIARIO).
        """
        p = self.nombre_producto
        if self.empaque == "PRIMARIO" and p.empaque_primario:
            return p.empaque_primario.nombre
        if self.empaque == "SECUNDARIO" and p.empaque_secundario:
            return p.empaque_secundario.nombre
        if self.empaque == "TERCIARIO" and p.empaque_terciario:
            return p.empaque_terciario.nombre
        return self.empaque

    # -----------------------------
    # Persistencia con IVA / Total
    # -----------------------------
    def _calcular_iva_total(self, neto: Decimal) -> tuple[Decimal, Decimal]:
        """
        Dado un neto, calcula (iva, total) con redondeo a 2 decimales (ROUND_HALF_UP).
        """
        neto = (neto or Decimal("0.00")).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
        iva = (neto * IVA_TASA).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
        total = (neto + iva).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
        return iva, total

    def save(self, *args, **kwargs):
        """
        Asegura que precio_iva y precio_total se calculen y guarden con
        redondeo consistente cada vez que cambie el precio_venta.
        Normaliza el campo empaque a PRIMARIO/SECUNDARIO/TERCIARIO.
        """
        # Normaliza el valor del empaque por seguridad
        if self.empaque:
            self.empaque = str(self.empaque).upper().strip()
            # Validación rápida contra los niveles permitidos
            niveles_validos = {n for n, _ in CategoriaEmpaque.NIVELES}
            if self.empaque not in niveles_validos:
                raise ValueError(f"Empaque inválido: {self.empaque}. Debe ser uno de {niveles_validos}")

        # Recalcula IVA y Total
        neto = (self.precio_venta or Decimal("0.00")).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
        iva, total = self._calcular_iva_total(neto)
        self.precio_iva = iva
        self.precio_total = total

        super().save(*args, **kwargs)
