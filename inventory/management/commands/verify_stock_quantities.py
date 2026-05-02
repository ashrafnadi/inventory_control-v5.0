# inventory/management/commands/verify_stock_quantities.py
"""
Verify FacultyItemStock.cached_quantity matches transaction history.
Finds and reports mismatches.

Usage:
    uv run manage.py verify_stock_quantities --faculty=14
    uv run manage.py verify_stock_quantities --item=123 --faculty=14
    uv run manage.py verify_stock_quantities --fix --faculty=14
"""

import logging

from django.core.management.base import BaseCommand
from django.db.models import Q, Sum, Value
from django.db.models.functions import Coalesce

from inventory.models import FacultyItemStock, ItemTransactionDetails, ItemTransactions

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Verify FacultyItemStock quantities match transaction history"

    def add_arguments(self, parser):
        parser.add_argument("--faculty", type=int, help="Filter by faculty ID")
        parser.add_argument("--item", type=int, help="Check specific item ID")
        parser.add_argument(
            "--fix", action="store_true", help="Auto-fix mismatched quantities"
        )
        parser.add_argument(
            "--limit", type=int, default=50, help="Max items to check (default: 50)"
        )

    def handle(self, *args, **options):
        faculty_id = options.get("faculty")
        item_id = options.get("item")
        fix = options["fix"]
        limit = options["limit"]

        self.stdout.write("🔍 Verifying FacultyItemStock quantities...")
        if faculty_id:
            self.stdout.write(f"   Faculty filter: {faculty_id}")
        if item_id:
            self.stdout.write(f"   Item filter: {item_id}")
        if fix:
            self.stdout.write(
                self.style.WARNING("   ⚠️  FIX MODE: Will update mismatched records")
            )

        # Build queryset
        stocks = FacultyItemStock.objects.select_related(
            "item", "item__category", "sub_warehouse", "faculty"
        )
        if faculty_id:
            stocks = stocks.filter(faculty_id=faculty_id)
        if item_id:
            stocks = stocks.filter(item_id=item_id)

        stocks = stocks[:limit]
        total_checked = stocks.count()

        mismatches = []
        fixed_count = 0

        for stock in stocks:
            item = stock.item
            target_sw = item.category.sub_warehouse if item.category else None

            if not target_sw:
                continue  # Skip items without valid category→sub_warehouse

            # Calculate expected quantity from transactions
            expected_qty, tx_info = self._calculate_expected_quantity(
                item=item,
                faculty=stock.faculty,
                sub_warehouse=stock.sub_warehouse,
                return_debug=True,
            )

            stored_qty = stock.cached_quantity

            if stored_qty != expected_qty:
                mismatches.append(
                    {
                        "stock_id": stock.id,
                        "item_id": item.id,
                        "item_name": item.name,
                        "faculty": stock.faculty.name,
                        "sub_warehouse": stock.sub_warehouse.name,
                        "stored_qty": stored_qty,
                        "expected_qty": expected_qty,
                        "difference": expected_qty - stored_qty,
                        "tx_info": tx_info,
                    }
                )

                if fix:
                    stock.cached_quantity = expected_qty
                    stock.save(update_fields=["cached_quantity"])
                    fixed_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  ✓ Fixed: {item.name} | Stored: {stored_qty} → Expected: {expected_qty}"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(
                            f"  ✗ Mismatch: {item.name} | Stored: {stored_qty} ≠ Expected: {expected_qty}"
                        )
                    )
                    self.stdout.write(f"     {tx_info}")

        # Summary
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("📋 VERIFICATION SUMMARY")
        self.stdout.write("=" * 70)
        self.stdout.write(f"• Records checked: {total_checked}")
        self.stdout.write(f"• Mismatches found: {len(mismatches)}")
        if fix:
            self.stdout.write(f"• Records fixed: {fixed_count}")

        if mismatches and not fix:
            self.stdout.write("\n⚠️  Top 10 mismatches:")
            for m in mismatches[:10]:
                self.stdout.write(
                    f"  • {m['item_name']} ({m['item_id']}) | "
                    f"{m['faculty']} / {m['sub_warehouse']} | "
                    f"Stored: {m['stored_qty']} ≠ Expected: {m['expected_qty']} | "
                    f"Diff: {m['difference']}"
                )
                self.stdout.write(f"     {m['tx_info']}")
            if len(mismatches) > 10:
                self.stdout.write(f"  • ... and {len(mismatches) - 10} more")

            self.stdout.write(
                self.style.WARNING(
                    "\n💡 Run with --fix to auto-correct mismatched quantities"
                )
            )

    def _calculate_expected_quantity(
        self, item, faculty, sub_warehouse, return_debug=False
    ):
        """Calculate expected quantity with optional debug info."""
        details = ItemTransactionDetails.objects.filter(
            item=item,
            transaction__faculty=faculty,
            transaction__approval_status=ItemTransactions.APPROVAL_STATUS.APPROVED,
            transaction__deleted=False,
            transaction__is_reversed=False,
        )

        # IN transactions
        in_q = (
            Q(
                transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Addition,
                transaction__to_sub_warehouse=sub_warehouse,
            )
            | Q(
                transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Return,
                transaction__to_sub_warehouse=sub_warehouse,
            )
            | Q(
                transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Transfer,
                transaction__castody_type=ItemTransactions.CASTODY_TYPES.Warehouse,
                transaction__to_sub_warehouse=sub_warehouse,
            )
        )
        incoming = (
            details.filter(in_q).aggregate(
                total=Coalesce(Sum("approved_quantity"), Value(0))
            )["total"]
            or 0
        )
        in_count = details.filter(in_q).count()

        # OUT transactions
        out_q = Q(
            transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Disbursement,
            transaction__from_sub_warehouse=sub_warehouse,
        ) | Q(
            transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Transfer,
            transaction__castody_type=ItemTransactions.CASTODY_TYPES.Warehouse,
            transaction__from_sub_warehouse=sub_warehouse,
        )
        outgoing = (
            details.filter(out_q).aggregate(
                total=Coalesce(Sum("approved_quantity"), Value(0))
            )["total"]
            or 0
        )
        out_count = details.filter(out_q).count()

        expected = max(0, incoming - outgoing)
        total_details = details.count()

        if return_debug:
            debug = (
                f"Total approved details: {total_details} | "
                f"IN: {in_count} txs → +{incoming} | "
                f"OUT: {out_count} txs → -{outgoing} | "
                f"Net: {incoming} - {outgoing} = {expected}"
            )
            return expected, debug

        return expected, None
