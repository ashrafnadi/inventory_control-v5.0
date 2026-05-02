# inventory/management/commands/fix_cached_quantities.py
"""
Recalculate FacultyItemStock.cached_quantity from transaction history.
Use after correcting category/sub_warehouse mappings.

Usage:
    uv run manage.py fix_cached_quantities --faculty=1
    uv run manage.py fix_cached_quantities --item=501 --faculty=1
"""

import logging

from django.core.management.base import BaseCommand
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce

from administration.models import Faculty
from inventory.models import FacultyItemStock, ItemTransactionDetails, ItemTransactions

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Recalculate cached_quantity from approved transactions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--faculty", type=int, required=True, help="Faculty ID to fix"
        )
        parser.add_argument("--item", type=int, help="Limit to specific item ID")
        parser.add_argument(
            "--dry-run", action="store_true", help="Preview without saving"
        )

    def handle(self, *args, **options):
        faculty_id = options["faculty"]
        item_id = options.get("item")
        dry_run = options["dry_run"]

        faculty = Faculty.objects.get(id=faculty_id)
        self.stdout.write(
            f"[START] Fixing quantities for {faculty.name} (ID: {faculty_id})"
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY RUN] No changes will be saved."))

        stocks = FacultyItemStock.objects.select_related(
            "item", "item__category"
        ).filter(faculty=faculty)
        if item_id:
            stocks = stocks.filter(item_id=item_id)

        fixed = 0
        for stock in stocks:
            item = stock.item

            details = ItemTransactionDetails.objects.filter(
                item=item,
                transaction__faculty=faculty,
                transaction__approval_status=ItemTransactions.APPROVAL_STATUS.APPROVED,
                transaction__deleted=False,
                transaction__is_reversed=False,
            )

            incoming = (
                details.filter(transaction__transaction_type__in=["A", "R"]).aggregate(
                    total=Coalesce(Sum("approved_quantity"), Value(0))
                )["total"]
                or 0
            )

            outgoing = (
                details.filter(transaction__transaction_type="D").aggregate(
                    total=Coalesce(Sum("approved_quantity"), Value(0))
                )["total"]
                or 0
            )

            correct_qty = max(0, incoming - outgoing)

            if stock.cached_quantity != correct_qty:
                if dry_run:
                    self.stdout.write(
                        f"  [PREVIEW] {item.name}: {stock.cached_quantity} → {correct_qty}"
                    )
                else:
                    stock.cached_quantity = correct_qty
                    stock.save(
                        update_fields=["cached_quantity", "last_quantity_update"]
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  [FIXED] {item.name}: {stock.cached_quantity} → {correct_qty}"
                        )
                    )
                fixed += 1

        self.stdout.write(f"\n[SUMMARY] Fixed: {fixed} records")
        if dry_run:
            self.stdout.write(
                self.style.WARNING("[DRY RUN] Remove --dry-run to apply changes.")
            )
