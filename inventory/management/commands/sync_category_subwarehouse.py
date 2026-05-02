# inventory/management/commands/sync_category_subwarehouse.py
"""
Updates ItemCategory.sub_warehouse to match the most frequent transaction
to_sub_warehouse_id for items in that category.

Usage:
    uv run manage.py sync_category_subwarehouse --dry-run
    uv run manage.py sync_category_subwarehouse --category-id=3
    uv run manage.py sync_category_subwarehouse  # Apply to all
"""

import logging

from django.core.management.base import BaseCommand
from django.db.models import Count

from inventory.models import (
    Item,
    ItemCategory,
    ItemTransactionDetails,
    ItemTransactions,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Sync ItemCategory.sub_warehouse with the most frequent transaction "
        "to_sub_warehouse_id for items in that category."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without saving to database",
        )
        parser.add_argument(
            "--category-id",
            type=int,
            help="Limit to a specific category ID",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limit number of categories to process (0 = all)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit = options["limit"]
        cat_id = options["category_id"]

        self.stdout.write("[START] Syncing Category Sub-Warehouses...")
        if dry_run:
            self.stdout.write(
                self.style.WARNING("[DRY RUN] No database changes will be made.")
            )

        qs = ItemCategory.objects.select_related("sub_warehouse").all()
        if cat_id:
            qs = qs.filter(id=cat_id)
        if limit > 0:
            qs = qs[:limit]

        total_checked = qs.count()
        updated = 0
        skipped_match = 0
        skipped_no_tx = 0
        errors = 0

        for cat in qs:
            try:
                # 1. Get all item IDs in this category
                item_ids = list(
                    Item.objects.filter(category=cat).values_list("id", flat=True)
                )
                if not item_ids:
                    skipped_no_tx += 1
                    continue

                # 2. Find most frequent to_sub_warehouse in approved, active transactions
                most_common = (
                    ItemTransactionDetails.objects.filter(
                        item_id__in=item_ids,
                        transaction__approval_status=ItemTransactions.APPROVAL_STATUS.APPROVED,
                        transaction__deleted=False,
                        transaction__is_reversed=False,
                        transaction__to_sub_warehouse_id__isnull=False,
                    )
                    .values("transaction__to_sub_warehouse_id")
                    .annotate(count=Count("id"))
                    .order_by("-count", "-transaction__to_sub_warehouse_id")
                    .first()
                )

                if not most_common:
                    skipped_no_tx += 1
                    continue

                target_sw_id = most_common["transaction__to_sub_warehouse_id"]

                # 3. Skip if already correct
                if cat.sub_warehouse_id == target_sw_id:
                    skipped_match += 1
                    continue

                # 4. Apply or preview update
                if dry_run:
                    self.stdout.write(
                        f"  [PREVIEW] Category '{cat.name}' (ID: {cat.id}): "
                        f"Current SW={cat.sub_warehouse_id} -> Target SW={target_sw_id} "
                        f"(Txs: {most_common['count']})"
                    )
                else:
                    cat.sub_warehouse_id = target_sw_id
                    cat.save(update_fields=["sub_warehouse"])
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  [UPDATED] Category '{cat.name}' (ID: {cat.id}) -> SW={target_sw_id}"
                        )
                    )
                updated += 1

            except Exception as e:
                errors += 1
                self.stderr.write(
                    self.style.ERROR(f"  [ERROR] Category ID={cat.id}: {str(e)}")
                )
                logger.error(
                    f"Error syncing category {cat.id}: {str(e)}", exc_info=True
                )

        # Summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("[SUMMARY]")
        self.stdout.write("=" * 60)
        self.stdout.write(f"Categories checked: {total_checked}")
        self.stdout.write(f"Updated: {updated}")
        self.stdout.write(f"Skipped (already correct): {skipped_match}")
        self.stdout.write(f"Skipped (no approved txs): {skipped_no_tx}")
        self.stdout.write(f"Errors: {errors}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("\n[DRY RUN] Remove --dry-run to apply changes.")
            )
        else:
            self.stdout.write(self.style.SUCCESS("\n[COMPLETE] Sync finished."))
