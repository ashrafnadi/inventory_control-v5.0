# inventory/management/commands/sync_faculty_stocks.py
"""
Sync FacultyItemStock.cached_quantity with transaction history.
✅ Handles reversed transactions with sign inversion.
✅ Matches exact logic from item_history_view.
"""
# uv run manage.py sync_faculty_stocks --faculty 1
import logging

from django.core.management.base import BaseCommand
from django.db.models import Case, F, IntegerField, Sum, Value, When
from django.db.models.functions import Coalesce, Greatest

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
        calculated_nets = {}  # Cache results per item to avoid duplicate DB queries

        for stock in stocks.iterator():
            item_id = stock.item_id

            # Reuse calculation if already computed for this item in this run
            if item_id in calculated_nets:
                net = calculated_nets[item_id]
            else:
                # ✅ Calculate net quantity with correct sign handling for reversed transactions
                net = (
                    ItemTransactionDetails.objects.filter(
                        item_id=item_id,
                        transaction__faculty=faculty,
                        transaction__approval_status=ItemTransactions.APPROVAL_STATUS.APPROVED,
                        transaction__deleted=False,
                        transaction__transaction_type__in=["A", "D", "R"],
                    ).aggregate(
                        net=Greatest(
                            Value(0),
                            Coalesce(
                                Sum(
                                    Case(
                                        # Addition (A): + normally, - if reversed
                                        When(
                                            transaction__transaction_type="A",
                                            transaction__is_reversed=False,
                                            then=F("approved_quantity"),
                                        ),
                                        When(
                                            transaction__transaction_type="A",
                                            transaction__is_reversed=True,
                                            then=-F("approved_quantity"),
                                        ),
                                        # Disbursement (D): - normally, + if reversed
                                        When(
                                            transaction__transaction_type="D",
                                            transaction__is_reversed=False,
                                            then=-F("approved_quantity"),
                                        ),
                                        When(
                                            transaction__transaction_type="D",
                                            transaction__is_reversed=True,
                                            then=F("approved_quantity"),
                                        ),
                                        # Return (R): + normally, - if reversed
                                        When(
                                            transaction__transaction_type="R",
                                            transaction__is_reversed=False,
                                            then=F("approved_quantity"),
                                        ),
                                        When(
                                            transaction__transaction_type="R",
                                            transaction__is_reversed=True,
                                            then=-F("approved_quantity"),
                                        ),
                                        default=Value(0),
                                        output_field=IntegerField(),
                                    )
                                ),
                                Value(0),
                            ),
                        )
                    )["net"]
                    or 0
                )
                calculated_nets[item_id] = net

            # Debug line (remove or comment out in production)
            if item_id == 2552:
                self.stdout.write(
                    f"Debug Item {item_id}: Stored={stock.cached_quantity}, Calculated={net}"
                )

            if stock.cached_quantity != net:
                if not dry_run:
                    stock.cached_quantity = net
                    stock.save(
                        update_fields=["cached_quantity", "last_quantity_update"]
                    )
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"[DONE] Updated {updated} records"))
