# inventory/management/commands/recalculate_faculty_item_stock.py
"""
Recalculate FacultyItemStock.cached_quantity from transaction history.
Respects faculty isolation - each faculty sees only their own transactions.

Usage:
    uv run manage.py recalculate_faculty_item_stock --dry-run
    uv run manage.py recalculate_faculty_item_stock --faculty=14
    uv run manage.py recalculate_faculty_item_stock --batch-size=1000
"""

import logging

from django.core.management.base import BaseCommand
from django.db import connection
from django.db import transaction as db_transaction

from inventory.models import FacultyItemStock

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Recalculate FacultyItemStock.cached_quantity from APPROVED transactions. "
        "Respects faculty isolation. Safe to run multiple times (idempotent)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )
        parser.add_argument(
            "--faculty",
            type=int,
            help="Limit to specific faculty ID (optional)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of records to update per batch (default: 1000)",
        )
        parser.add_argument(
            "--only-zero",
            action="store_true",
            help="Only recalculate records where cached_quantity = 0",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        faculty_id = options["faculty"]
        batch_size = options["batch_size"]
        only_zero = options["only_zero"]

        self.stdout.write("🔄 Starting FacultyItemStock quantity recalculation...")
        self.stdout.write(f"   • Dry run: {dry_run}")
        self.stdout.write(
            f"   • Faculty filter: {faculty_id if faculty_id else 'All faculties'}"
        )
        self.stdout.write(f"   • Batch size: {batch_size}")
        self.stdout.write(f"   • Zero-only mode: {only_zero}")

        # Calculate net quantities per (faculty, item, sub_warehouse)
        # Uses set-based SQL for maximum performance
        fac_filter = f"AND up.faculty_id = {faculty_id}" if faculty_id else ""
        zero_filter = "AND fis.cached_quantity = 0" if only_zero else ""

        calc_sql = f"""
            WITH NetMovements AS (
                SELECT
                    up.faculty_id,
                    itd.item_id,
                    ic.sub_warehouse_id AS sub_warehouse_id,
                    SUM(
                        CASE
                            -- Exclude non-warehouse transfers
                            WHEN it.castody_type != 'W' AND it.transaction_type = 'T' THEN 0
                            
                            -- IN transactions (Addition, Return, Transfer TO)
                            WHEN it.transaction_type IN ('A', 'R') 
                                 AND it.to_sub_warehouse_id = ic.sub_warehouse_id 
                            THEN itd.approved_quantity
                            
                            WHEN it.transaction_type = 'T' 
                                 AND it.castody_type = 'W'
                                 AND it.to_sub_warehouse_id = ic.sub_warehouse_id 
                            THEN itd.approved_quantity
                            
                            -- OUT transactions (Disbursement, Transfer FROM)
                            WHEN it.transaction_type = 'D' 
                                 AND it.from_sub_warehouse_id = ic.sub_warehouse_id 
                            THEN -itd.approved_quantity
                            
                            WHEN it.transaction_type = 'T' 
                                 AND it.castody_type = 'W'
                                 AND it.from_sub_warehouse_id = ic.sub_warehouse_id 
                            THEN -itd.approved_quantity
                            
                            ELSE 0
                        END
                    ) AS net_qty
                FROM inventory_itemtransactiondetails itd
                JOIN inventory_itemtransactions it ON itd.transaction_id = it.id
                JOIN inventory_item i ON itd.item_id = i.id
                JOIN inventory_itemcategory ic ON i.category_id = ic.id
                JOIN administration_userprofile up ON it.created_by_id = up.user_id
                WHERE it.approval_status = 'A'
                  AND it.deleted = FALSE
                  AND it.is_reversed = FALSE
                  AND up.faculty_id IS NOT NULL
                  AND ic.sub_warehouse_id IS NOT NULL
                  {fac_filter}
                GROUP BY up.faculty_id, itd.item_id, ic.sub_warehouse_id
            )
            SELECT 
                nm.faculty_id,
                nm.item_id,
                nm.sub_warehouse_id,
                GREATEST(0, nm.net_qty) AS calculated_qty
            FROM NetMovements nm
            WHERE nm.net_qty != 0
        """

        with connection.cursor() as cursor:
            cursor.execute(calc_sql)
            calculated = cursor.fetchall()

        if not calculated:
            self.stdout.write(self.style.SUCCESS("✅ No quantity changes needed."))
            return

        self.stdout.write(
            f"📊 Found {len(calculated)} records with calculated quantities..."
        )

        # Get existing FacultyItemStock records to update
        existing_map = {}
        for fis in FacultyItemStock.objects.all().only(
            "id", "faculty_id", "item_id", "sub_warehouse_id", "cached_quantity"
        ):
            key = (fis.faculty_id, fis.item_id, fis.sub_warehouse_id)
            existing_map[key] = fis

        # Identify records to update (only where quantity differs)
        to_update = []
        skipped_same = 0
        created_new = 0

        for fac_id, item_id, sw_id, calc_qty in calculated:
            key = (fac_id, item_id, sw_id)
            existing = existing_map.get(key)

            if existing:
                if existing.cached_quantity != calc_qty:
                    existing.cached_quantity = calc_qty
                    to_update.append(existing)
                else:
                    skipped_same += 1
            else:
                # Record doesn't exist - mark for creation (handled by populate script)
                created_new += 1

        if not to_update:
            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ All {skipped_same} existing records already have correct quantities."
                )
            )
            if created_new > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f"⚠️  {created_new} records need creation. Run `populate_faculty_item_stock` first."
                    )
                )
            return

        # Bulk update in batches
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\n🛑 DRY RUN: Would update {len(to_update)} FacultyItemStock records."
                )
            )
            # Show sample of changes
            for fis in to_update[:5]:
                self.stdout.write(
                    f"  • Faculty={fis.faculty_id}, Item={fis.item_id}, "
                    f"SW={fis.sub_warehouse_id}, Old={fis.cached_quantity}, New=calculated"
                )
        else:
            with db_transaction.atomic():
                updated_count = 0
                for i in range(0, len(to_update), batch_size):
                    chunk = to_update[i : i + batch_size]
                    FacultyItemStock.objects.bulk_update(
                        chunk, fields=["cached_quantity"], batch_size=batch_size
                    )
                    updated_count += len(chunk)
                    self.stdout.write(
                        f"  📦 Updated batch {i // batch_size + 1} ({len(chunk)} records)"
                    )

            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✅ Successfully updated {updated_count} FacultyItemStock records."
                )
            )
            if created_new > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f"⚠️  {created_new} records need creation. Run `populate_faculty_item_stock`."
                    )
                )

        # Summary
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("📋 RECALCULATION SUMMARY"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"• Total calculated records: {len(calculated)}")
        self.stdout.write(f"• Records updated: {len(to_update) if not dry_run else 0}")
        self.stdout.write(f"• Records skipped (no change): {skipped_same}")
        self.stdout.write(f"• Records missing (need creation): {created_new}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("\n⚠️  DRY RUN MODE - Database unchanged.")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("\n✅ FacultyItemStock recalculation complete.")
            )
