"""
Este módulo contiene los formularios personalizados (ModelForm y Form) utilizados 
en la aplicación de gestión de productos, recepciones, clientes, ventas y cotizaciones
del sistema SAAM.

Incluye validaciones específicas por modelo, restricciones de campos únicos,
formateo de precios, validación de RUT chileno y lógica adicional para operaciones
de negocio como IVA o empaques.
"""

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from Apps.Pedidos.utils import validar_rut
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# Modelos importados
from .models import (
    Producto, Proveedor, Contacto, Recepcion, RecepcionLinea, Stock, Cliente, ListaPrecios,
    Subcategoria, Pedido, Cotizacion, CategoriaEmpaque, Venta, ConfiguracionBoletaSii
)

#Constantes
DOS_DECIMALES = Decimal('0.01')
IVA = Decimal('0.19')
FACTOR_NETO = Decimal('1.00') + IVA  # Decimal('1.19')

# --------------------------
# FORMULARIOS PERSONALIZADOS
# --------------------------
class CrearProveedorForm(forms.ModelForm):
    """
    Formulario personalizado para crear o editar un proveedor en el sistema.

    Campos:
        - Todos los del modelo Proveedor.
        - 'empresa_activa' se inicializa como True por defecto.

    Validaciones:
        - Hereda la validación automática del ModelForm.
    """

    empresa_activa = forms.BooleanField(required=False, initial=True)

    class Meta:
        model = Proveedor
        fields = '__all__'

class CrearProductoForm(forms.ModelForm):
    """
    Formulario para crear productos con validaciones de códigos únicos
    y selección de empaques según su nivel (primario, secundario, terciario).
    """
    barcodes = forms.CharField(label='Códigos de Barra', required=False)

    class Meta:
        model = Producto
        fields = [
            'categoria_producto',
            'subcategoria_producto',
            # 'codigo_producto_proveedor',  # ❌ NO se usa más: los códigos externos van en CodigoProveedor
            'codigo_producto_interno',
            'nombre_producto',
            'qty_terciario',
            'qty_secundario',
            'qty_primario',
            'qty_unidad',
            'medida',
            'qty_minima',
            'empaque_primario',
            'empaque_secundario',
            'empaque_terciario',
        ]
        labels = {
            'categoria_producto': 'Categoría',
            'subcategoria_producto': 'Subcategoría',
            'codigo_producto_interno': 'Código interno',
            'nombre_producto': 'Nombre del producto',
            'qty_terciario': 'Cantidad por Empaque Terciario',
            'qty_secundario': 'Cantidad por Empaque Secundario',
            'qty_primario': 'Cantidad por Empaque Primario',
            'qty_unidad': 'Cantidad por Unidad',
            'medida': 'Unidad de Medida',
            'qty_minima': 'Cantidad mínima',
            'empaque_primario': 'Empaque Primario',
            'empaque_secundario': 'Empaque Secundario',
            'empaque_terciario': 'Empaque Terciario',
        }

    def __init__(self, *args, **kwargs):
        """
        Inicializa el formulario filtrando los empaques según su nivel.
        """
        super().__init__(*args, **kwargs)
        self.fields['empaque_primario'].queryset = CategoriaEmpaque.objects.filter(nivel='PRIMARIO')
        self.fields['empaque_secundario'].queryset = CategoriaEmpaque.objects.filter(nivel='SECUNDARIO')
        self.fields['empaque_terciario'].queryset = CategoriaEmpaque.objects.filter(nivel='TERCIARIO')

    def clean(self):
        """
        Valida que el código interno no se repita al crear.
        (Los códigos de proveedor se gestionan en la tabla CodigoProveedor desde el template).
        """
        cleaned_data = super().clean()
        cod_interno = cleaned_data.get('codigo_producto_interno')

        if not self.instance.pk:
            if Producto.objects.filter(codigo_producto_interno=cod_interno).exists():
                self.add_error('codigo_producto_interno', "Ya existe un producto con este código interno.")
        return cleaned_data


class CrearPackForm(forms.ModelForm):
    """
    Formulario simplificado para crear packs comerciales.
    """

    class Meta:
        model = Producto
        fields = [
            'codigo_producto_interno',
            'nombre_producto',
        ]
        labels = {
            'codigo_producto_interno': 'Código interno del pack',
            'nombre_producto': 'Nombre del pack',
        }

    def clean_codigo_producto_interno(self):
        codigo = (self.cleaned_data.get('codigo_producto_interno') or '').strip()
        qs = Producto.objects.filter(codigo_producto_interno=codigo)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Ya existe un producto con este código interno.")
        return codigo

class CambiarEstadoProductoForm(forms.Form):
    estado_operativo = forms.ChoiceField(
        choices=Producto.ESTADO_OPERATIVO_CHOICES,
        label='Estado operativo',
    )
    motivo_estado = forms.CharField(
        label='Motivo',
        required=False,
        max_length=255,
        widget=forms.Textarea(attrs={'rows': 3}),
    )

    def __init__(self, *args, **kwargs):
        self.producto = kwargs.pop('producto')
        super().__init__(*args, **kwargs)
        self.fields['estado_operativo'].initial = self.producto.estado_operativo
        self.fields['motivo_estado'].initial = self.producto.motivo_estado
        self.fields['estado_operativo'].widget.attrs.update({'class': 'form-select'})
        self.fields['motivo_estado'].widget.attrs.update({'class': 'form-control'})

    def clean(self):
        cleaned_data = super().clean()
        nuevo_estado = cleaned_data.get('estado_operativo')
        motivo = (cleaned_data.get('motivo_estado') or '').strip()

        if not nuevo_estado:
            self.add_error('estado_operativo', "Debes seleccionar un estado.")
            return cleaned_data

        if nuevo_estado != Producto.ESTADO_ACTIVO and not motivo:
            self.add_error('motivo_estado', "Debes indicar un motivo para suspender o descontinuar el producto.")

        return cleaned_data

    def save(self, usuario=None):
        self.producto.actualizar_estado_operativo(
            self.cleaned_data['estado_operativo'],
            motivo=self.cleaned_data.get('motivo_estado', ''),
            usuario=usuario,
        )
        return self.producto


class CrearContactoForm(forms.ModelForm):
    class Meta:
        model = Contacto
        fields = ['proveedor', 'nombre_contacto', 'apellido_contacto',
                  'cargo_contacto', 'telefono_contacto', 'correo_contacto']

    def clean(self):
        cleaned = super().clean()
        nombre   = cleaned.get('nombre_contacto')
        apellido = cleaned.get('apellido_contacto')
        cargo    = cleaned.get('cargo_contacto')
        proveedor = cleaned.get('proveedor')  # en este form sí viene

        qs = Contacto.objects.filter(
            nombre_contacto=nombre,
            apellido_contacto=apellido,
            cargo_contacto=cargo,
        )
        if proveedor:
            qs = qs.filter(proveedor=proveedor)

        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise forms.ValidationError(
                "Ya existe un contacto con ese nombre, apellido y cargo para este proveedor."
            )
        return cleaned

class AsociarContactoForm(forms.ModelForm):
    """
    Formulario para asociar un contacto existente a un proveedor.
    Similar a CrearContactoForm, pero pensado para reutilizar contactos.

    Realiza validaciones:
        - Todos los campos deben estar completos.
        - No debe existir otro contacto exactamente igual ya registrado.
    """

    class Meta:
        model = Contacto
        fields = '__all__'

    def clean(self):
        """
        Validación del formulario:
        - Requiere que todos los campos estén presentes.
        - Valida duplicados exactos en los datos del contacto.
        """
        cleaned_data = super().clean()

        proveedor = cleaned_data.get('proveedor')
        nombre = cleaned_data.get('nombre_contacto')
        apellido = cleaned_data.get('apellido_contacto')
        cargo = cleaned_data.get('cargo_contacto')
        telefono = cleaned_data.get('telefono_contacto')
        correo = cleaned_data.get('correo_contacto')

        # Verifica presencia de todos los campos
        if not all([proveedor, nombre, apellido, cargo, telefono, correo]):
            raise ValidationError("Todos los campos son obligatorios.")

        # Verificación de duplicado exacto solo si es una nueva instancia
        if not self.instance.pk:
            existe = Contacto.objects.filter(
                proveedor=proveedor,
                nombre_contacto=nombre,
                apellido_contacto=apellido,
                cargo=cargo,
                telefono_contacto=telefono,
                correo_contacto=correo
            ).exists()
            if existe:
                raise ValidationError("Este contacto ya existe para el proveedor seleccionado.")

        return cleaned_data

class CrearRecepcionForm(forms.ModelForm):
    """
    Formulario para crear una recepción de productos, incluyendo 
    validación de monto neto, chequeo de duplicidad por proveedor y documento, 
    y un control para incluir o no el IVA en los precios ingresados.
    """
    incluir_iva = forms.BooleanField(required=False)

    class Meta:
        model = Recepcion
        fields = [
            'fecha_recepcion',
            'estado_recepcion',
            'documento_recepcion',
            'num_documento_recepcion',
            'total_neto_recepcion',
            'moneda_recepcion',
            'incluir_iva',
            'proveedor',
            'comentario_recepcion',
        ]
        widgets = {
            'fecha_recepcion': forms.DateInput(
                format='%Y-%m-%d',
                attrs={'type': 'date', 'class': 'form-control'}
            ),
            'estado_recepcion': forms.Select(attrs={'class': 'form-control'}),
            'documento_recepcion': forms.Select(attrs={'class': 'form-control'}),
            'moneda_recepcion': forms.Select(attrs={'class': 'form-control'}),
            'num_documento_recepcion': forms.TextInput(attrs={'class': 'form-control'}),
            'total_neto_recepcion': forms.TextInput(attrs={'class': 'form-control'}),
            'proveedor': forms.Select(attrs={'class': 'form-control'}),
            'comentario_recepcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'maxlength': 500}),
        }

    def __init__(self, *args, **kwargs):
        """
        Inicializa el formulario con valor inicial de incluir_iva
        según el estado actual de la instancia, si existe.
        """
        super().__init__(*args, **kwargs)
        if self.instance and hasattr(self.instance, 'incluir_iva'):
            self.fields['incluir_iva'].initial = self.instance.incluir_iva
        else:
            self.fields['incluir_iva'].initial = False

    def clean_total_neto_recepcion(self):
        """
        Limpia y convierte el monto ingresado a Decimal, eliminando caracteres especiales.
        Asegura que el valor sea no negativo y válido según norma del SII.
        """
        monto_raw = (self.data.get('total_neto_recepcion', '') or '').strip()
        if not monto_raw:
            return Decimal('0.00')

        monto_raw = monto_raw.replace("$", "").replace(" ", "")
        # Soporta "1.234,56" y "1234.56"
        if "," in monto_raw and "." in monto_raw:
            monto_raw = monto_raw.replace(".", "").replace(",", ".")
        elif "," in monto_raw:
            monto_raw = monto_raw.replace(",", ".")

        try:
            monto_clean = Decimal(monto_raw)
        except (InvalidOperation, ValueError):
            raise ValidationError("Formato de monto inválido.")
        if monto_clean < 0:
            raise ValidationError("El monto neto no puede ser negativo.")
        return monto_clean.quantize(DOS_DECIMALES, rounding=ROUND_HALF_UP)

    def clean_comentario_recepcion(self):
        comentario = (self.cleaned_data.get('comentario_recepcion') or '').strip()
        return comentario

    def clean(self):
        """
        Valida que no exista otra recepción con el mismo número de documento
        para el proveedor actual (solo al crear una nueva).
        """
        cleaned_data = super().clean()
        proveedor = cleaned_data.get('proveedor')
        num_doc = cleaned_data.get('num_documento_recepcion')

        if proveedor and num_doc and not self.instance.pk:
            if Recepcion.objects.filter(proveedor=proveedor, num_documento_recepcion=num_doc).exists():
                raise ValidationError("Ya existe una recepción con este número de documento para el proveedor.")

        return cleaned_data

class CrearRecepcionProductoForm(forms.ModelForm):
    """
    Formulario para registrar productos dentro de una recepción específica.
    Incluye validaciones de cantidad, precio unitario y lógica para aplicar IVA 
    automáticamente si la recepción lo requiere. 
    También asocia el producto al documento de recepción correspondiente.
    """

    class Meta:
        model = RecepcionLinea
        fields = ['producto', 'qty', 'empaque', 'precio_unitario']
        widgets = {
            'producto': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'qty': forms.NumberInput(
                attrs={
                    'class': 'form-control form-control-sm',
                    'min': 1,
                    'step': 1,
                    'inputmode': 'numeric',
                }
            ),
            'empaque': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'precio_unitario': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'step': '0.01', 'min': 0}),
        }
        labels = {
            'producto': 'Producto',
            'qty': 'Cantidad',
            'empaque': 'Empaque',
            'precio_unitario': 'Precio unitario',
        }

    def __init__(self, *args, **kwargs):
        """
        Inicializa el formulario con la recepción asociada (self.documento),
        y configura el queryset del campo producto y las opciones de empaque.
        """
        self.documento = kwargs.pop('documento', None)
        super().__init__(*args, **kwargs)
        self.fields['producto'].queryset = Producto.objects.filter(
            tipo_producto='SIMPLE',
            estado_operativo__in=Producto.estados_compra_habilitados(),
        ).order_by('nombre_producto')
        self.fields['empaque'].widget.choices = Stock.UNIDAD_EMPAQUE

    def clean_qty(self):
        """
        Valida que la cantidad ingresada sea un número positivo mayor a cero.

        Returns:
            int: Cantidad validada.
        """
        qty = self.cleaned_data.get('qty')
        if qty is None or qty <= 0:
            raise ValidationError("La cantidad debe ser un número entero positivo.")
        return qty

    def clean_precio_unitario(self):
        """
        Valida que el precio unitario ingresado sea un valor decimal positivo.

        Returns:
            Decimal: Precio validado.
        """
        precio = self.cleaned_data.get('precio_unitario')
        if precio is None or precio <= 0:
            raise ValidationError("El precio unitario debe ser un número positivo.")
        return precio.quantize(DOS_DECIMALES, rounding=ROUND_HALF_UP)

    def clean(self):
        cleaned_data = super().clean()
        producto = cleaned_data.get('producto')
        if producto and not producto.compra_habilitada:
            self.add_error('producto', "El producto no estÃ¡ habilitado para nuevas recepciones.")
        return cleaned_data

    def save(self, commit=True):
        """
        Guarda la instancia del producto asociado a la recepción.
        Si la recepción incluye IVA, ajusta automáticamente el precio neto.

        Args:
            commit (bool): Si True, guarda la instancia en la base de datos.

        Returns:
            RecepcionLinea: Instancia guardada del detalle de recepción.
        """
        instancia = super().save(commit=False)
        instancia.recepcion = self.documento

        if instancia.precio_unitario and self.documento and getattr(self.documento, 'incluir_iva', False):
            precio_neto = (instancia.precio_unitario / FACTOR_NETO).quantize(DOS_DECIMALES, rounding=ROUND_HALF_UP)
            instancia.precio_unitario = precio_neto
        else:
            instancia.precio_unitario = instancia.precio_unitario.quantize(DOS_DECIMALES, rounding=ROUND_HALF_UP)

        if commit:
            instancia.full_clean()
            instancia.save()
        return instancia

class ClienteForm(forms.ModelForm):
    """
    Formulario para registrar y editar clientes.
    Incluye validación del RUT chileno utilizando la función `validar_rut` del módulo utils.
    """

    class Meta:
        model = Cliente
        fields = [
            'nombre_cliente',
            'rut_cliente',
            'razon_social',
            'giro_cliente',
            'direccion_cliente',
            'direccion_bodega_cliente',
            'comuna_cliente',
            'ciudad_cliente',
            'cliente_activo',
            'telefono_cliente',
            'correo_cliente',
            'categoria',
        ]
        labels = {
            'nombre_cliente': 'Nombre del Cliente',
            'rut_cliente': 'RUT',
            'direccion_cliente': 'Dirección Comercial',
            'direccion_bodega_cliente': 'Dirección Bodega',
            'cliente_activo': '¿Activo?',
            'telefono_cliente': 'Teléfono',
            'correo_cliente': 'Correo electrónico',
            'categoria': 'Categoría del Cliente',
        }

    def clean_rut_cliente(self):
        """
        Valida que el RUT ingresado tenga formato válido y no esté duplicado.

        Raises:
            ValidationError: Si el RUT no es válido o ya existe en otro cliente.

        Returns:
            str: RUT validado y limpio.
        """
        rut = self.cleaned_data.get('rut_cliente')

        # Validación de formato usando función externa
        if not validar_rut(rut):
            raise ValidationError("RUT inválido.")

        # Validación de duplicado solo si es nuevo cliente
        if not self.instance.pk and Cliente.objects.filter(rut_cliente=rut).exists():
            raise ValidationError("Ya existe un cliente con este RUT.")

        return rut

    def clean_razon_social(self):
        razon_social = (self.cleaned_data.get('razon_social') or '').strip()
        if razon_social:
            return razon_social
        return (self.cleaned_data.get('nombre_cliente') or '').strip()

    def clean_giro_cliente(self):
        return (self.cleaned_data.get('giro_cliente') or '').strip()

    def clean_comuna_cliente(self):
        return (self.cleaned_data.get('comuna_cliente') or '').strip()

    def clean_ciudad_cliente(self):
        return (self.cleaned_data.get('ciudad_cliente') or '').strip()

class ListaPreciosForm(forms.ModelForm):
    """
    Formulario para asignar precios de productos a clientes específicos.

    Permite registrar un precio de venta por producto y empaque, calcular el IVA
    y el precio total. También valida que no exista duplicidad de asignación de precios.
    """

    def __init__(self, *args, **kwargs):
        """
        Constructor personalizado que espera recibir el cliente como argumento
        para ser usado en validaciones posteriores.
        """
        self.cliente = kwargs.pop('cliente', None)
        super().__init__(*args, **kwargs)

    class Meta:
        model = ListaPrecios
        fields = ['nombre_producto', 'empaque', 'precio_venta', 'vigencia']
        labels = {
            'nombre_producto': 'Producto',
            'empaque': 'Empaque',
            'precio_venta': 'Precio Neto',
            'vigencia': 'Desde',
        }
        widgets = {
            'vigencia': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def clean(self):
        """
        Validación general del formulario. Verifica:
        - Que el cliente esté definido.
        - Que todos los campos requeridos estén presentes.
        - Que el producto con el mismo empaque no esté ya registrado para el cliente.
        """
        cleaned_data = super().clean()

        # Validación: Cliente requerido
        if not self.cliente:
            raise forms.ValidationError("El cliente debe estar definido.")

        # Validación: Campos individuales
        producto = cleaned_data.get('nombre_producto')
        empaque = cleaned_data.get('empaque')
        precio_venta = cleaned_data.get('precio_venta')
        vigencia = cleaned_data.get('vigencia')

        if not producto:
            self.add_error('nombre_producto', "Debe seleccionar un producto.")
        elif not producto.precio_habilitado:
            self.add_error('nombre_producto', "El producto no estÃ¡ habilitado para nuevos precios.")

        if not empaque:
            self.add_error('empaque', "Debe seleccionar un empaque.")

        if precio_venta is None:
            self.add_error('precio_venta', "Debe ingresar un precio de venta.")
        elif precio_venta < 0:
            self.add_error('precio_venta', "El precio de venta no puede ser negativo.")

        if not vigencia:
            self.add_error('vigencia', "Debe ingresar una fecha desde.")

        # Validación: evitar duplicados (si es nuevo)
        if producto and empaque:
            qs = ListaPrecios.objects.filter(
                nombre_cliente=self.cliente,
                nombre_producto=producto,
                empaque=empaque
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError("Este producto con ese empaque ya tiene un precio asignado para el cliente.")

        return cleaned_data

    def save(self, commit=True):
        """
        Guarda la instancia del precio asignado, calculando automáticamente el IVA
        y el precio total si se proporciona el precio de venta.

        Args:
            commit (bool): Si se debe guardar en base de datos inmediatamente.

        Returns:
            ListaPrecios: Instancia creada o modificada.
        """
        instancia = super().save(commit=False)
        instancia.nombre_cliente = self.cliente

        # Cálculo automático del IVA (19%) y precio total
        if instancia.precio_venta is not None:
            precio_iva = (instancia.precio_venta * IVA).quantize(DOS_DECIMALES, rounding=ROUND_HALF_UP)
            precio_total = (instancia.precio_venta + precio_iva).quantize(DOS_DECIMALES, rounding=ROUND_HALF_UP)
            instancia.precio_iva = precio_iva
            instancia.precio_total = precio_total

        if commit:
            instancia.save()
        return instancia

class SubCategoriaForm(forms.ModelForm):
    """
    Formulario para crear o editar una subcategoría de productos,
    vinculada a una categoría principal.
    """

    class Meta:
        model = Subcategoria
        fields = ['subcategoria', 'categoria']
        labels = {
            'subcategoria': 'Nombre de la Subcategoría',
            'categoria': 'Categoría',
        }
        widgets = {
            'subcategoria': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ingrese nombre de subcategoría'
            }),
            'categoria': forms.Select(attrs={
                'class': 'form-select'
            }),
        }

class PedidoForm(forms.ModelForm):
    """
    Formulario para registrar un nuevo pedido de un cliente.

    Permite ingresar la fecha, estado actual y comentarios adicionales del pedido.
    """

    num_cotizacion = forms.CharField(
        required=False,
        label='Cotización (opcional)',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Número de cotización (opcional)'})
    )

    class Meta:
        model = Pedido
        fields = ['nombre_cliente', 'fecha_pedido', 'estado_pedido', 'comentario_pedido']
        labels = {
            'nombre_cliente': 'Cliente',
            'fecha_pedido': 'Fecha del Pedido',
            'estado_pedido': 'Estado',
            'comentario_pedido': 'Comentario',
        }
        widgets = {
            'nombre_cliente': forms.TextInput(attrs={'class': 'form-control'}),
            'fecha_pedido': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'estado_pedido': forms.Select(attrs={'class': 'form-control'}),
            'comentario_pedido': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cotizacion_obj = None

        # Mostrar número de cotización actual al editar.
        if self.instance and self.instance.pk and self.instance.num_cotizacion:
            self.fields['num_cotizacion'].initial = self.instance.num_cotizacion.num_cotizacion

    def clean_num_cotizacion(self):
        numero = (self.cleaned_data.get('num_cotizacion') or '').strip()
        if not numero:
            self._cotizacion_obj = None
            return ''

        cotizacion = Cotizacion.objects.filter(num_cotizacion=numero).select_related('nombre_cliente').first()
        if not cotizacion:
            raise ValidationError("No existe una cotización con ese número.")
        self._cotizacion_obj = cotizacion
        return numero

    def clean(self):
        cleaned_data = super().clean()
        cliente = cleaned_data.get('nombre_cliente')
        cot = getattr(self, '_cotizacion_obj', None)

        if cot and cliente and cot.nombre_cliente_id != cliente.id:
            self.add_error(
                'num_cotizacion',
                "La cotización no corresponde al cliente seleccionado."
            )
        return cleaned_data

    def save(self, commit=True):
        instancia = super().save(commit=False)
        instancia.num_cotizacion = getattr(self, '_cotizacion_obj', None)

        if commit:
            instancia.save()
            self.save_m2m()
        return instancia

class SeleccionarClienteForm(forms.Form):
    """
    Formulario para seleccionar un cliente activo del sistema.

    Usado como paso previo para mostrar los productos disponibles
    para ese cliente (en cotizaciones, listas de precios, etc.).
    """

    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.filter(cliente_activo=True),
        label="Cliente"
    )

class ProductoReservaForm(forms.Form):
    """
    Formulario simple para seleccionar un producto, su cantidad y su empaque 
    al momento de crear un pedido o reserva de productos.

    Este formulario no está vinculado a un modelo directamente.
    """

    producto_id = forms.IntegerField(widget=forms.HiddenInput)
    producto_nombre = forms.CharField(disabled=True, required=False)
    empaque = forms.CharField(widget=forms.HiddenInput)
    precio_unitario = forms.DecimalField(widget=forms.HiddenInput, decimal_places=2, max_digits=12)
    cantidad = forms.IntegerField(
        min_value=0,
        required=False,
        initial=0,
        label="Cantidad"
    )

class ProductosCotizacionForm(forms.Form):
    """
    Formulario dinámico para generar una cotización a partir de productos disponibles 
    en una Lista de Precios personalizada para un cliente.

    Los campos se generan dinámicamente en base a un queryset de objetos `ListaPrecios`.
    """

    def __init__(self, *args, **kwargs):
        precios = kwargs.pop('precios')  # queryset de ListaPrecios
        super().__init__(*args, **kwargs)

        # Crear campos dinámicamente según los productos del cliente
        for i, lp in enumerate(precios):
            self.fields[f'producto_{i}'] = forms.BooleanField(
                label=f"{lp.nombre_producto.nombre_producto} ({lp.empaque}) - ${lp.precio_total:,}",
                required=False
            )
            self.fields[f'cantidad_{i}'] = forms.IntegerField(
                min_value=1,
                initial=1,
                required=False,
                label="Cantidad"
            )
            self.fields[f'precio_{i}'] = forms.DecimalField(
                widget=forms.HiddenInput(),
                initial=lp.precio_total,
                decimal_places=2,
                max_digits=12
            )
            self.fields[f'id_{i}'] = forms.IntegerField(
                widget=forms.HiddenInput(),
                initial=lp.id
            )

class CategoriaEmpaqueForm(forms.ModelForm):
    """
    Formulario para crear o editar una categoría de empaque, permitiendo asignar 
    un nombre personalizado y su nivel jerárquico (PRIMARIO, SECUNDARIO, TERCIARIO).
    """

    class Meta:
        model = CategoriaEmpaque
        fields = ['nombre', 'nivel']
        labels = {
            'nombre': 'Nombre visible de empaque',
            'nivel': 'Nivel de empaque (PRIMARIO, SECUNDARIO, TERCIARIO)'
        }
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'nivel': forms.Select(attrs={'class': 'form-select'}),
        }

class FinalizarVentaForm(forms.ModelForm):
    """
    Formulario para registrar la información final de una venta asociada a un pedido.

    Permite ingresar la fecha de venta, el tipo de documento y su número.
    Incluye validación para evitar duplicados por pedido.
    """

    class Meta:
        model = Venta
        fields = ['fecha_venta', 'documento_pedido', 'num_documento']
        widgets = {
            'fecha_venta': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'}
            ),
            'documento_pedido': forms.Select(attrs={'class': 'form-select'}),
            'num_documento': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
        }

    def __init__(self, *args, **kwargs):
        """
        Permite recibir el pedido asociado al formulario para su validación.
        """
        self.pedido = kwargs.pop('pedido', None)  # <-- Recibe el objeto Pedido desde la vista
        super().__init__(*args, **kwargs)
        self.fields['num_documento'].required = False
        self.fields['fecha_venta'].initial = self.fields['fecha_venta'].initial or timezone.localdate()
        self.fields['documento_pedido'].initial = self.fields['documento_pedido'].initial or 'Boleta'

    def clean(self):
        """
        Validación del formulario para evitar ventas duplicadas por pedido.
        """
        cleaned_data = super().clean()
        documento = cleaned_data.get('documento_pedido')
        num_documento = cleaned_data.get('num_documento')

        # Validar que no exista ya una venta para este pedido
        if self.pedido and Venta.objects.filter(pedidoid=self.pedido).exists():
            raise forms.ValidationError("Ya existe una venta registrada para este pedido.")

        if documento != 'Boleta' and not num_documento:
            self.add_error('num_documento', "Debes ingresar el numero del documento.")

        if num_documento is not None and num_documento <= 0:
            self.add_error('num_documento', "El numero del documento debe ser mayor a cero.")

        if documento == 'Boleta':
            cleaned_data['num_documento'] = None

        return cleaned_data


class ConfiguracionBoletaSiiForm(forms.ModelForm):
    class Meta:
        model = ConfiguracionBoletaSii
        fields = [
            'nombre',
            'activa',
            'ambiente',
            'habilita_boleta',
            'habilita_factura',
            'rut_emisor',
            'razon_social',
            'giro',
            'acteco_principal',
            'direccion_origen',
            'comuna_origen',
            'ciudad_origen',
            'resolucion_numero',
            'resolucion_fecha',
            'certificado_alias',
            'correo_intercambio',
            'ruta_caf_tipo_33',
            'ruta_caf_tipo_39',
            'monto_identificacion_receptor_boleta',
            'observaciones',
        ]
        labels = {
            'nombre': 'Nombre de la configuracion',
            'activa': 'Configurar como activa',
            'ambiente': 'Ambiente',
            'habilita_boleta': 'Habilitar boleta electronica',
            'habilita_factura': 'Habilitar factura electronica',
            'rut_emisor': 'RUT emisor',
            'razon_social': 'Razon social',
            'giro': 'Giro',
            'acteco_principal': 'Acteco principal',
            'direccion_origen': 'Direccion origen',
            'comuna_origen': 'Comuna origen',
            'ciudad_origen': 'Ciudad origen',
            'resolucion_numero': 'Numero resolucion',
            'resolucion_fecha': 'Fecha resolucion',
            'certificado_alias': 'Alias certificado',
            'correo_intercambio': 'Correo intercambio DTE',
            'ruta_caf_tipo_33': 'Ruta o referencia CAF tipo 33',
            'ruta_caf_tipo_39': 'Ruta o referencia CAF tipo 39',
            'monto_identificacion_receptor_boleta': 'Monto CLP para identificar receptor boleta',
            'observaciones': 'Observaciones',
        }
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'activa': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'ambiente': forms.Select(attrs={'class': 'form-select'}),
            'habilita_boleta': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'habilita_factura': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'rut_emisor': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '11.111.111-1'}),
            'razon_social': forms.TextInput(attrs={'class': 'form-control'}),
            'giro': forms.TextInput(attrs={'class': 'form-control'}),
            'acteco_principal': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 521900'}),
            'direccion_origen': forms.TextInput(attrs={'class': 'form-control'}),
            'comuna_origen': forms.TextInput(attrs={'class': 'form-control'}),
            'ciudad_origen': forms.TextInput(attrs={'class': 'form-control'}),
            'resolucion_numero': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'resolucion_fecha': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'certificado_alias': forms.TextInput(attrs={'class': 'form-control'}),
            'correo_intercambio': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'dte@empresa.cl'}),
            'ruta_caf_tipo_33': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'caf/tipo33.xml'}),
            'ruta_caf_tipo_39': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'caf/tipo39.xml'}),
            'monto_identificacion_receptor_boleta': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'step': '1'}),
            'observaciones': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def clean_rut_emisor(self):
        rut = (self.cleaned_data.get('rut_emisor') or '').strip()
        if not validar_rut(rut):
            raise ValidationError("RUT emisor invalido.")
        return rut

    def clean_nombre(self):
        return (self.cleaned_data.get('nombre') or '').strip()

    def clean_razon_social(self):
        return (self.cleaned_data.get('razon_social') or '').strip()

    def clean_giro(self):
        return (self.cleaned_data.get('giro') or '').strip()

    def clean_acteco_principal(self):
        return (self.cleaned_data.get('acteco_principal') or '').strip()

    def clean_direccion_origen(self):
        return (self.cleaned_data.get('direccion_origen') or '').strip()

    def clean_comuna_origen(self):
        return (self.cleaned_data.get('comuna_origen') or '').strip()

    def clean_ciudad_origen(self):
        return (self.cleaned_data.get('ciudad_origen') or '').strip()

    def clean_certificado_alias(self):
        return (self.cleaned_data.get('certificado_alias') or '').strip()

    def clean_correo_intercambio(self):
        return (self.cleaned_data.get('correo_intercambio') or '').strip()

    def clean_ruta_caf_tipo_33(self):
        return (self.cleaned_data.get('ruta_caf_tipo_33') or '').strip()

    def clean_ruta_caf_tipo_39(self):
        return (self.cleaned_data.get('ruta_caf_tipo_39') or '').strip()

    def clean_monto_identificacion_receptor_boleta(self):
        monto = self.cleaned_data.get('monto_identificacion_receptor_boleta') or Decimal('0')
        if monto < 0:
            raise ValidationError("El monto no puede ser negativo.")
        return monto.quantize(DOS_DECIMALES, rounding=ROUND_HALF_UP)

    def clean_observaciones(self):
        return (self.cleaned_data.get('observaciones') or '').strip()

    def clean(self):
        cleaned_data = super().clean()
        habilita_boleta = cleaned_data.get('habilita_boleta')
        habilita_factura = cleaned_data.get('habilita_factura')
        caf_33 = cleaned_data.get('ruta_caf_tipo_33')
        caf_39 = cleaned_data.get('ruta_caf_tipo_39')

        if not habilita_boleta and not habilita_factura:
            raise ValidationError("Debes habilitar al menos boleta o factura.")

        if habilita_boleta and not caf_39:
            self.add_error('ruta_caf_tipo_39', "Debes informar el CAF tipo 39 para boleta.")

        if habilita_factura and not caf_33:
            self.add_error('ruta_caf_tipo_33', "Debes informar el CAF tipo 33 para factura.")

        return cleaned_data
