# Portal/Apps/Pedidos/management/commands/recalcular_recepciones.py
from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal, ROUND_HALF_UP
from django.utils.dateparse import parse_date

from Apps.Pedidos.models import Recepcion

# 💡 Porcentaje de IVA configurable aquí
IVA_TASA = Decimal("0.19")
DOS_DEC  = Decimal("0.01")

class Command(BaseCommand):
    help = "Recalcula iva_recepcion y total_recepcion a partir de total_neto_recepcion, ignorando incluir_iva."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="No guarda cambios.")
        parser.add_argument("--only-pendientes", action="store_true", help="Excluye Finalizado.")
        parser.add_argument("--since", type=str, help=">= YYYY-MM-DD")
        parser.add_argument("--until", type=str, help="<= YYYY-MM-DD")
        parser.add_argument("--id", type=int, help="Solo una recepción por ID")

    def handle(self, *args, **opts):
        qs = Recepcion.objects.all()
        if opts.get("id"):
            qs = qs.filter(id=opts["id"])
        if opts.get("only_pendientes") or opts.get("only-pendientes"):
            qs = qs.exclude(estado_recepcion="Finalizado")

        s = opts.get("since"); u = opts.get("until")
        if s:
            d = parse_date(s)
            if not d:
                self.stderr.write("Formato inválido --since (use YYYY-MM-DD).")
                return
            qs = qs.filter(fecha_recepcion__gte=d)
        if u:
            d = parse_date(u)
            if not d:
                self.stderr.write("Formato inválido --until (use YYYY-MM-DD).")
                return
            qs = qs.filter(fecha_recepcion__lte=d)

        total = qs.count()
        if not total:
            self.stdout.write("No hay recepciones a procesar.")
            return

        dry = opts.get("dry_run", False)
        self.stdout.write(f"Procesando {total} recepciones {'(dry-run)' if dry else ''}...")

        procesadas = 0
        with transaction.atomic():
            for r in qs.iterator():
                # Neto base (siempre tomado del campo persistido)
                neto = (r.total_neto_recepcion or Decimal("0.00")).quantize(DOS_DEC, rounding=ROUND_HALF_UP)

                # ⚠️ Ignora incluir_iva: siempre calcula IVA y Total
                iva = (neto * IVA_TASA).quantize(DOS_DEC, rounding=ROUND_HALF_UP)
                total_doc = (neto + iva).quantize(DOS_DEC, rounding=ROUND_HALF_UP)

                before_neto  = r.total_neto_recepcion or Decimal("0.00")
                before_iva   = r.iva_recepcion or Decimal("0.00")
                before_total = r.total_recepcion or Decimal("0.00")

                r.iva_recepcion = iva
                r.total_recepcion = total_doc
                r.save(update_fields=["iva_recepcion", "total_recepcion"])

                self.stdout.write(
                    f"[{r.id}] Neto {before_neto} | IVA {before_iva} -> {iva} | Total {before_total} -> {total_doc}"
                )
                procesadas += 1

            if dry:
                transaction.set_rollback(True)

        self.stdout.write(f"Listo. Procesadas: {procesadas}. {'Sin guardar (dry-run).' if dry else 'Cambios guardados.'}")
