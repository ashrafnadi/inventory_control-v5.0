# inventory/management/commands/find_missing_items.py
"""
Find items that have approved transactions but are missing from FacultyItemStock.

Usage:
    uv run manage.py find_missing_items --faculty=14
    uv run manage.py find_missing_items --export missing_items.csv
"""

import csv
import logging
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Q, Sum, Value
from django.db.models.functions import Coalesce

from inventory.models import (
    FacultyItemStock,
    Item,
    ItemTransactionDetails,
    ItemTransactions,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Find items with approved transactions but missing from FacultyItemStock"

    def add_arguments(self, parser):
        parser.add_argument(
            "--faculty",
            type=int,
            help="Filter by faculty ID (optional)",
        )
        parser.add_argument(
            "--export",
            type=str,
            help="Export results to CSV file (optional)",
        )
        parser.add_argument(
            "--include-zero",
            action="store_true",
            help="Include items where net quantity = 0",
        )

    def handle(self, *args, **options):
        faculty_id = options.get("faculty")
        export_path = options.get("export")
        include_zero = options["include_zero"]

        self.stdout.write("🔍 Scanning for missing items...")
        if faculty_id:
            self.stdout.write(f"   Faculty filter: {faculty_id}")
        if include_zero:
            self.stdout.write("   Including items with net qty = 0")

        # Find all items that have approved transaction details
        items_with_txs = (
            Item.objects.filter(
                itemtransactiondetails__transaction__approval_status=ItemTransactions.APPROVAL_STATUS.APPROVED,
                itemtransactiondetails__transaction__deleted=False,
                itemtransactiondetails__transaction__is_reversed=False,
            )
            .select_related("category", "category__sub_warehouse")
            .distinct()
        )

        if faculty_id:
            items_with_txs = items_with_txs.filter(
                itemtransactiondetails__transaction__faculty_id=faculty_id
            )

        missing_items = []

        for item in items_with_txs:
            target_sw = item.category.sub_warehouse if item.category else None

            # Reason 1: No category or category has no sub_warehouse
            if not target_sw:
                missing_items.append(
                    {
                        "item_id": item.id,
                        "item_name": item.name,
                        "item_code": item.code or "-",
                        "category": item.category.name if item.category else None,
                        "category_id": item.category_id,
                        "target_sub_warehouse": None,
                        "reason": "No category or category has no sub_warehouse",
                        "approved_quantity": 0,
                    }
                )
                continue

            # Calculate net quantity from transactions for this faculty/item/sub_warehouse
            faculty_filter = (
                {"transaction__faculty_id": faculty_id} if faculty_id else {}
            )

            details = ItemTransactionDetails.objects.filter(
                item=item,
                transaction__approval_status=ItemTransactions.APPROVAL_STATUS.APPROVED,
                transaction__deleted=False,
                transaction__is_reversed=False,
                **faculty_filter,
            )

            incoming = (
                details.filter(
                    Q(
                        transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Addition,
                        transaction__to_sub_warehouse=target_sw,
                    )
                    | Q(
                        transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Return,
                        transaction__to_sub_warehouse=target_sw,
                    )
                    | Q(
                        transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Transfer,
                        transaction__castody_type="W",
                        transaction__to_sub_warehouse=target_sw,
                    )
                ).aggregate(total=Coalesce(Sum("approved_quantity"), Value(0)))["total"]
                or 0
            )

            outgoing = (
                details.filter(
                    Q(
                        transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Disbursement,
                        transaction__from_sub_warehouse=target_sw,
                    )
                    | Q(
                        transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Transfer,
                        transaction__castody_type="W",
                        transaction__from_sub_warehouse=target_sw,
                    )
                ).aggregate(total=Coalesce(Sum("approved_quantity"), Value(0)))["total"]
                or 0
            )

            net_qty = max(0, incoming - outgoing)

            # Skip if net_qty = 0 and --include-zero not set
            if net_qty == 0 and not include_zero:
                continue

            # Reason 2: No FacultyItemStock record exists for this combination
            has_stock = FacultyItemStock.objects.filter(
                item=item,
                sub_warehouse=target_sw,
                **({"faculty_id": faculty_id} if faculty_id else {}),
            ).exists()

            if not has_stock:
                missing_items.append(
                    {
                        "item_id": item.id,
                        "item_name": item.name,
                        "item_code": item.code or "-",
                        "category": item.category.name if item.category else None,
                        "category_id": item.category_id,
                        "target_sub_warehouse": target_sw.name,
                        "target_sub_warehouse_id": target_sw.id,
                        "reason": f"No FacultyItemStock record (net_qty={net_qty})",
                        "incoming": incoming,
                        "outgoing": outgoing,
                        "net_quantity": net_qty,
                    }
                )

        # Output results
        if not missing_items:
            self.stdout.write(self.style.SUCCESS("✅ No missing items found!"))
            return

        self.stdout.write(
            f"\n⚠️  Found {len(missing_items)} items with transactions but missing from FacultyItemStock:\n"
        )

        # Group by reason
        from collections import defaultdict

        by_reason = defaultdict(list)
        for m in missing_items:
            by_reason[m["reason"]].append(m)

        for reason, items in by_reason.items():
            self.stdout.write(f"\n📌 {reason} ({len(items)} items):")
            for item in items[:10]:  # Show first 10 per reason
                self.stdout.write(
                    f"   • ID={item['item_id']} | {item['item_name']} | Net Qty: {item.get('net_quantity', 'N/A')}"
                )
            if len(items) > 10:
                self.stdout.write(f"   • ... and {len(items) - 10} more")

        # Export to CSV if requested
        if export_path:
            path = Path(export_path)
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=missing_items[0].keys())
                writer.writeheader()
                writer.writerows(missing_items)
            self.stdout.write(self.style.SUCCESS(f"\n📄 Exported to {path}"))

        # Summary
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("📋 SUMMARY")
        self.stdout.write("=" * 70)
        for reason, items in by_reason.items():
            self.stdout.write(f"• {reason}: {len(items)} items")
        self.stdout.write(f"\nTotal missing: {len(missing_items)}")
