(function ($) {
  "use strict";

  if (!$ || !$.fn || !$.fn.DataTable) {
    return;
  }

  const idioma = {
    decimal: ",",
    thousands: ".",
    processing: "Procesando...",
    search: "Buscar:",
    lengthMenu: "Mostrar _MENU_ registros",
    info: "Mostrando registros del _START_ al _END_ de un total de _TOTAL_ registros",
    infoEmpty: "Mostrando registros del 0 al 0 de un total de 0 registros",
    infoFiltered: "(filtrado de un total de _MAX_ registros)",
    infoPostFix: "",
    loadingRecords: "Cargando...",
    zeroRecords: "No se encontraron resultados",
    emptyTable: "Ningún dato disponible en esta tabla",
    paginate: {
      first: "Primero",
      previous: "Anterior",
      next: "Siguiente",
      last: "Último",
    },
    aria: {
      sortAscending: ": Activar para ordenar la columna de manera ascendente",
      sortDescending: ": Activar para ordenar la columna de manera descendente",
    },
  };

  function tieneEstructuraValida($tabla) {
    const columnas = $tabla.find("thead tr:first th, thead tr:first td").length;
    if (!columnas) {
      return false;
    }

    return !$tabla.find("tbody tr").filter(function () {
      const $celdas = $(this).children("th, td");
      return $celdas.length === 1 && Number($celdas.first().attr("colspan") || 1) > 1;
    }).length;
  }

  function normalizarCeldasCombinadas($tabla) {
    if (!$tabla.hasClass("js-tabla-filtros")) {
      return;
    }

    const columnas = $tabla.find("thead tr:first th, thead tr:first td").length;
    $tabla.find("tbody tr").each(function () {
      const $celdas = $(this).children("th, td");
      if ($celdas.length !== 1) {
        return;
      }

      const $celda = $celdas.first();
      const colspan = Number($celda.attr("colspan") || 1);
      if (colspan <= 1) {
        return;
      }

      $celda.removeAttr("colspan");
      for (let indice = 1; indice < columnas; indice += 1) {
        $("<td>", { "aria-hidden": "true" }).appendTo(this);
      }
    });
  }

  function opcionesPara($tabla) {
    const esInforme = $tabla.hasClass("js-sortable-report-table");
    const noOrdenables = $tabla.find("thead th.no-sort").map(function () {
      return $(this).index();
    }).get();
    const opciones = {
      language: idioma,
      autoWidth: false,
      scrollX: !esInforme,
      order: [],
    };

    if (esInforme) {
      Object.assign(opciones, {
        paging: false,
        searching: false,
        info: false,
        lengthChange: false,
        dom: "t",
      });
    }

    if (noOrdenables.length) {
      opciones.columnDefs = [{ targets: noOrdenables, orderable: false }];
    }

    return opciones;
  }

  function inicializarTablas(contenedor) {
    $(contenedor).find("table").addBack("table").each(function () {
      const $tabla = $(this);

      normalizarCeldasCombinadas($tabla);

      if ($tabla.attr("data-tabla-filtros") === "false" ||
          $.fn.dataTable.isDataTable(this) ||
          !tieneEstructuraValida($tabla)) {
        return;
      }

      $tabla.DataTable(opcionesPara($tabla));
    });
  }

  $(function () {
    inicializarTablas(document);
  });

  window.inicializarTablasConFiltros = inicializarTablas;
})(window.jQuery || (window.django && window.django.jQuery));
