# inventory/management/commands/sync_faculty_stocks_new.py
"""
Sync FacultyItemStock.cached_quantity with transaction history.
✅ Matches EXACT logic from item_history_view & calculate_authoritative_net_quantity.
✅ Uses document_number prefix (REV-) for accurate reversal handling.
✅ Optimized with .update() instead of .save() in loop.
"""

# uv run manage.py sync_faculty_stocks_new --faculty 1

import logging

from django.core.management.base import BaseCommand
from django.db.models import Case, F, IntegerField, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from administration.models import Faculty
from inventory.models import FacultyItemStock, ItemTransactionDetails, ItemTransactions

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync all FacultyItemStock.cached_quantity with transaction history"

    def add_arguments(self, parser):
        parser.add_argument("--faculty", type=int, required=True, help="Faculty ID")
        parser.add_argument("--dry-run", action="store_true", help="Preview only")
        parser.add_argument("--item", type=int, help="Limit to specific item ID")

    def handle(self, *args, **options):
        faculty = Faculty.objects.get(id=options["faculty"])
        dry_run = options["dry_run"]
        item_id_filter = options.get("item")

        self.stdout.write(f"[START] Syncing FacultyItemStock for {faculty.name}")
        if dry_run:
            self.stdout.write(
                self.style.WARNING("[DRY RUN] - No changes will be saved")
            )

        stocks = FacultyItemStock.objects.filter(faculty=faculty).select_related(
            "item", "sub_warehouse"
        )
        if item_id_filter:
            stocks = stocks.filter(item_id=item_id_filter)

        updated = 0
        calculated_nets = {}  # Cache per item to avoid duplicate DB queries

        for stock in stocks.iterator():
            item_id = stock.item_id
            if item_id in calculated_nets:
                net = calculated_nets[item_id]
            else:
                # ✅ EXACT MATCH with item_history_view aggregate logic
                net = (
                    ItemTransactionDetails.objects.filter(
                        item_id=item_id,
                        transaction__faculty=faculty,
                        transaction__approval_status=ItemTransactions.APPROVAL_STATUS.APPROVED,
                        transaction__deleted=False,
                        transaction__transaction_type__in=["A", "D", "R"],
                    ).aggregate(
                        net=Coalesce(
                            Sum(
                                Case(
                                    # Normal Addition/Return (+)
                                    When(
                                        Q(transaction__transaction_type__in=["A", "R"])
                                        & ~Q(
                                            transaction__document_number__startswith="REV-"
                                        ),
                                        then=F("approved_quantity"),
                                    ),
                                    # Reversal of Addition/Return (-)
                                    When(
                                        Q(transaction__transaction_type__in=["A", "R"])
                                        & Q(
                                            transaction__document_number__startswith="REV-"
                                        ),
                                        then=-F("approved_quantity"),
                                    ),
                                    # Normal Disbursement (-)
                                    When(
                                        Q(transaction__transaction_type="D")
                                        & ~Q(
                                            transaction__document_number__startswith="REV-"
                                        ),
                                        then=-F("approved_quantity"),
                                    ),
                                    # Reversal of Disbursement (+)
                                    When(
                                        Q(transaction__transaction_type="D")
                                        & Q(
                                            transaction__document_number__startswith="REV-"
                                        ),
                                        then=F("approved_quantity"),
                                    ),
                                    default=Value(0),
                                    output_field=IntegerField(),
                                )
                            ),
                            Value(0),
                        )
                    )["net"]
                    or 0
                )
                # Clamp to zero (safer than DB Greatest for cross-DB compatibility)
                net = max(0, net)
                calculated_nets[item_id] = net

            if stock.cached_quantity != net:
                if not dry_run:
                    # ✅ Use .update() for bulk performance (avoids .save() signal overhead)
                    FacultyItemStock.objects.filter(pk=stock.pk).update(
                        cached_quantity=net, last_quantity_update=timezone.now()
                    )
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"[DONE] Updated {updated} records"))
