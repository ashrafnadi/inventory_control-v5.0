# inventory/management/commands/sync_transactions_to_category_warehouse.py
"""
Updates ItemTransaction sub_warehouse IDs to match ItemCategory.sub_warehouse.
SAFE: Handles unique constraint violations by skipping conflicting records.
"""

import logging
from django.core.management.base import BaseCommand
from django.db import IntegrityError
from django.db.models import Q

from inventory.models import (
    Item,
    ItemCategory,
    ItemTransactionDetails,
    ItemTransactions,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Update transaction sub_warehouse IDs to match ItemCategory.sub_warehouse. "
        "Skips transactions that would violate unique constraints."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Preview changes")
        parser.add_argument(
            "--category-id", type=int, help="Limit to specific category"
        )
        parser.add_argument(
            "--approved-only",
            action="store_true",
            help="Only update approved transactions",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        cat_id = options["category_id"]
        approved_only = options["approved_only"]

        self.stdout.write("[START] Syncing transactions to category sub-warehouse...")
        if dry_run:
            self.stdout.write(
                self.style.WARNING("[DRY RUN] No database changes will be made.")
            )
        if approved_only:
            self.stdout.write(
                self.style.WARNING(
                    "[FILTER] Only approved transactions will be updated."
                )
            )

        qs = ItemCategory.objects.select_related("sub_warehouse").all()
        if cat_id:
            qs = qs.filter(id=cat_id)

        total_categories = qs.count()
        total_updated = 0
        skipped_conflict = 0
        skipped_no_match = 0
        errors = 0

        for cat in qs:
            target_sw_id = cat.sub_warehouse_id
            if not target_sw_id:
                continue

            item_ids = list(
                Item.objects.filter(category=cat).values_list("id", flat=True)
            )
            if not item_ids:
                continue

            tx_ids = list(
                ItemTransactionDetails.objects.filter(item_id__in=item_ids)
                .values_list("transaction_id", flat=True)
                .distinct()
            )
            if not tx_ids:
                continue

            tx_filter = Q(id__in=tx_ids)
            if approved_only:
                tx_filter &= Q(
                    approval_status=ItemTransactions.APPROVAL_STATUS.APPROVED
                )

            # Get all transactions that need updating
            to_update = ItemTransactions.objects.filter(tx_filter).filter(
                (
                    Q(transaction_type__in=["A", "R"])
                    & ~Q(to_sub_warehouse_id=target_sw_id)
                )
                | (Q(transaction_type="D") & ~Q(from_sub_warehouse_id=target_sw_id))
                | (
                    Q(transaction_type="T", castody_type="W")
                    & (
                        ~Q(to_sub_warehouse_id=target_sw_id)
                        | ~Q(from_sub_warehouse_id=target_sw_id)
                    )
                )
            )

            if not to_update.exists():
                skipped_no_match += 1
                continue

            if dry_run:
                self.stdout.write(
                    f"  [PREVIEW] Category '{cat.name}' (ID: {cat.id}): "
                    f"Would update {to_update.count()} transactions to SW={target_sw_id}"
                )
                total_updated += to_update.count()
                continue

            # Safe row-by-row update to catch constraint violations
            for tx in to_update.iterator():
                try:
                    update_fields = {}
                    if tx.transaction_type in ["A", "R"]:
                        update_fields["to_sub_warehouse_id"] = target_sw_id
                    elif tx.transaction_type == "D":
                        update_fields["from_sub_warehouse_id"] = target_sw_id
                    elif tx.transaction_type == "T" and tx.castody_type == "W":
                        update_fields["to_sub_warehouse_id"] = target_sw_id
                        update_fields["from_sub_warehouse_id"] = target_sw_id

                    if update_fields:
                        # Direct DB update bypasses model save() & recalculation
                        ItemTransactions.objects.filter(pk=tx.pk).update(
                            **update_fields
                        )
                        total_updated += 1
                except IntegrityError:
                    skipped_conflict += 1
                    self.stderr.write(
                        self.style.WARNING(
                            f"  [SKIP CONSTRAINT] Doc: {tx.document_number} | "
                            f"Type: {tx.get_transaction_type_display()} | "
                            f"Reason: Unique constraint violation (duplicate doc/SW combo)"
                        )
                    )
                    logger.warning(
                        f"Skipped tx {tx.id} due to constraint violation: {tx.document_number}"
                    )

        # Summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("[SUMMARY]")
        self.stdout.write("=" * 60)
        self.stdout.write(f"Categories processed: {total_categories}")
        self.stdout.write(f"Transactions updated: {total_updated}")
        self.stdout.write(f"Skipped (constraint conflict): {skipped_conflict}")
        self.stdout.write(f"Skipped (no change needed): {skipped_no_match}")
        self.stdout.write(f"Errors: {errors}")

        if skipped_conflict > 0:
            self.stdout.write(
                self.style.WARNING(
                    "\n⚠️  Some transactions were skipped due to document number conflicts. "
                    "These usually indicate duplicate document numbers across different sub-warehouses."
                )
            )

        if dry_run:
            self.stdout.write(
                self.style.WARNING("\n[DRY RUN] Remove --dry-run to apply changes.")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "\n[COMPLETE] Transactions synced. "
                    "⚠️  Run `verify_stock_quantities --fix` to recalculate quantities."
                )
            )
