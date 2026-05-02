# inventory/management/commands/populate_faculty_item_stock.py
"""
Management command to populate FacultyItemStock from transaction history.

Logic Update:
- Items are no longer linked to sub_warehouses directly.
- The script now looks at Item -> Category -> SubWarehouse to determine the target location.
- It creates FacultyItemStock records ONLY for the sub_warehouse defined by the item's category.
"""

import logging

from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.db.models import Q, Sum, Value
from django.db.models.functions import Coalesce

from administration.models import Faculty
from inventory.models import (
    FacultyItemStock,
    Item,
    ItemTransactionDetails,
    ItemTransactions,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Populate FacultyItemStock for ALL faculty/item combinations. "
        "Uses the item's category to determine the sub_warehouse."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )
        parser.add_argument(
            "--faculty",
            type=int,
            help="Limit to specific faculty ID (optional)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        faculty_id = options["faculty"]

        self.stdout.write(
            self.style.SUCCESS(
                f"🚀 Starting FacultyItemStock population\n"
                f"   • Dry run: {dry_run}\n"
                f"   • Faculty filter: {faculty_id if faculty_id else 'All faculties'}"
            )
        )

        if faculty_id:
            faculties = list(Faculty.objects.filter(id=faculty_id))
            if not faculties:
                self.stdout.write(
                    self.style.ERROR(f"❌ Faculty with ID {faculty_id} not found.")
                )
                return
        else:
            faculties = list(Faculty.objects.all())

        if not faculties:
            self.stdout.write(self.style.ERROR("❌ No faculties found in database."))
            return

        faculty_count = len(faculties)
        self.stdout.write(f"   • Total faculties: {faculty_count}")

        # Prefetch Category and SubWarehouse to avoid N+1 queries
        items = list(
            Item.objects.select_related("category", "category__sub_warehouse").all()
        )
        total_items = len(items)
        self.stdout.write(f"   • Total items: {total_items}")

        created_count = 0
        skipped_count = 0
        skipped_no_warehouse = 0
        error_count = 0

        total_combinations = faculty_count * total_items
        processed = 0

        for faculty in faculties:
            for item in items:
                try:
                    processed += 1

                    # Determine SubWarehouse via Category
                    target_sub_warehouse = (
                        item.category.sub_warehouse if item.category else None
                    )

                    if not target_sub_warehouse:
                        skipped_no_warehouse += 1
                        if dry_run:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"  ⚠️  Skip (No Category/SubWarehouse): "
                                    f"Item={item.name} (ID: {item.id})"
                                )
                            )
                        continue

                    # Check if FacultyItemStock already exists for this combination
                    existing_stock = FacultyItemStock.objects.filter(
                        faculty=faculty,
                        item=item,
                        sub_warehouse=target_sub_warehouse,
                    ).first()

                    if existing_stock:
                        skipped_count += 1
                        if dry_run and existing_stock.cached_quantity > 0:
                            self.stdout.write(
                                f"  ⏭️  Skip (exists - qty={existing_stock.cached_quantity}): "
                                f"Faculty={faculty.name}, Item={item.name}"
                            )
                        continue

                    # Calculate quantity from transactions
                    qty = self._calculate_quantity_from_transactions(
                        item=item,
                        faculty=faculty,
                        sub_warehouse=target_sub_warehouse,
                    )

                    if dry_run:
                        action = "Would create" if qty > 0 else "Would create (qty=0)"
                        self.stdout.write(
                            f"  {action}: Faculty={faculty.name}, "
                            f"Item={item.name}, "
                            f"SubWarehouse={target_sub_warehouse.name}, "
                            f"Qty={qty}"
                        )
                        created_count += 1
                    else:
                        with db_transaction.atomic():
                            FacultyItemStock.objects.create(
                                faculty=faculty,
                                item=item,
                                sub_warehouse=target_sub_warehouse,
                                cached_quantity=qty,
                                limit_quantity=item.limit_quantity,
                            )
                            created_count += 1
                            if qty > 0:
                                self.stdout.write(
                                    self.style.SUCCESS(
                                        f"✓ Created: Faculty={faculty.name}, "
                                        f"Item={item.name}, "
                                        f"SubWarehouse={target_sub_warehouse.name}, "
                                        f"Qty={qty}"
                                    )
                                )

                except Exception as e:
                    error_count += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f"✗ Error processing Faculty={faculty.name}, Item={item.id} ({item.name}): {str(e)}"
                        )
                    )
                    logger.error(
                        f"Error in populate_faculty_item_stock: {str(e)}", exc_info=True
                    )

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("📋 SUMMARY"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"• Total faculties: {faculty_count}")
        self.stdout.write(f"• Total items: {total_items}")
        self.stdout.write(f"• FacultyItemStock records created: {created_count}")
        self.stdout.write(
            f"• FacultyItemStock records skipped (already exist): {skipped_count}"
        )
        self.stdout.write(
            f"• Items skipped (no Category/SubWarehouse defined): {skipped_no_warehouse}"
        )
        self.stdout.write(f"• Errors encountered: {error_count}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("\n⚠️  DRY RUN MODE - No changes were made.")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("\n✅ FacultyItemStock population completed.")
            )

    def _calculate_quantity_from_transactions(self, item, faculty, sub_warehouse):
        """
        Calculate quantity from APPROVED transactions for a specific faculty/sub_warehouse.
        """
        details = ItemTransactionDetails.objects.filter(
            item=item,
            transaction__faculty=faculty,
            transaction__approval_status=ItemTransactions.APPROVAL_STATUS.APPROVED,
            transaction__deleted=False,
            transaction__is_reversed=False,
        )

        # IN transactions (Addition, Return, Transfer TO)
        incoming = (
            details.filter(
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
            ).aggregate(total=Coalesce(Sum("approved_quantity"), Value(0)))["total"]
            or 0
        )

        # OUT transactions (Disbursement, Transfer FROM)
        outgoing = (
            details.filter(
                Q(
                    transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Disbursement,
                    transaction__from_sub_warehouse=sub_warehouse,
                )
                | Q(
                    transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Transfer,
                    transaction__castody_type=ItemTransactions.CASTODY_TYPES.Warehouse,
                    transaction__from_sub_warehouse=sub_warehouse,
                )
            ).aggregate(total=Coalesce(Sum("approved_quantity"), Value(0)))["total"]
            or 0
        )

        return max(0, incoming - outgoing)
