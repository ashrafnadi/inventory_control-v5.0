# inventory/management/commands/fix_transaction_document_numbers.py

"""
Management command to regenerate transaction document numbers starting from 1 (0001)
and incrementing sequentially per faculty & transaction-type scope.

Scope: (faculty_id, transaction_type, sub_warehouse_code, year)
Order: Chronological (created_at) to preserve historical sequence
Starts: 0001, 0002, 0003... per scope
"""

# uv run manage.py fix_transaction_document_numbers --force

from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import IntegrityError
from django.db import transaction as db_transaction

from inventory.models import ItemTransactions


class Command(BaseCommand):
    help = (
        "Regenerate document numbers starting from 0001 and incrementing sequentially "
        "per faculty & transaction-type scope, preserving chronological order."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without saving (default behavior)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Actually apply the changes to the database",
        )
        parser.add_argument(
            "--faculty",
            type=int,
            help="Limit to a specific faculty ID (optional)",
        )
        parser.add_argument(
            "--transaction-type",
            type=str,
            choices=["A", "D", "R", "T"],
            help="Limit to a specific transaction type (A=Addition, D=Disbursement, R=Return, T=Transfer)",
        )

    def _get_prefix(self, tx_type: str) -> str:
        type_prefixes = {
            ItemTransactions.TRANSACTION_TYPES.Addition: "ADD",
            ItemTransactions.TRANSACTION_TYPES.Disbursement: "DIS",
            ItemTransactions.TRANSACTION_TYPES.Transfer: "TRF",
            ItemTransactions.TRANSACTION_TYPES.Return: "RET",
        }
        return type_prefixes.get(tx_type, "DOC")

    def _get_faculty_segment(self, faculty_id: int) -> str:
        return f"B{faculty_id}" if faculty_id else "B0"

    def _get_sub_wh_code(self, sub_wh) -> str:
        if not sub_wh:
            return "GEN"
        if sub_wh.code:
            return sub_wh.code
        name_part = "".join(c for c in sub_wh.name[:3].upper() if c.isalnum())
        return f"{name_part}{sub_wh.id:03d}"

    def handle(self, *args, **options):
        dry_run = options["dry_run"] or not options["force"]
        filter_faculty = options.get("faculty")
        filter_tx_type = options.get("transaction_type")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("🔍 DRY RUN MODE - No changes will be saved")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("⚠️  LIVE MODE - Changes WILL be applied")
            )

        # Base queryset
        txs_qs = (
            ItemTransactions.objects.filter(document_number__isnull=False)
            .exclude(document_number="")
            .select_related("from_sub_warehouse", "to_sub_warehouse", "faculty")
        )

        if filter_faculty:
            txs_qs = txs_qs.filter(faculty_id=filter_faculty)
        if filter_tx_type:
            txs_qs = txs_qs.filter(transaction_type=filter_tx_type)

        # Group transactions by scope key: (faculty_id, tx_type, sub_wh_code, year)
        scope_groups = {}
        skipped_no_faculty = 0
        current_year = str(datetime.now().year)

        for tx in txs_qs.iterator(chunk_size=200):
            # Resolve faculty ID strictly
            tx_faculty_id = tx.faculty_id
            if (
                not tx_faculty_id
                and tx.created_by
                and hasattr(tx.created_by, "profile")
            ):
                tx_faculty_id = tx.created_by.profile.faculty_id

            if not tx_faculty_id:
                skipped_no_faculty += 1
                continue

            scope_wh = tx._get_scope_sub_warehouse()
            sub_wh_code = self._get_sub_wh_code(scope_wh)
            prefix = self._get_prefix(tx.transaction_type)
            faculty_seg = self._get_faculty_segment(tx_faculty_id)

            scope_key = (tx_faculty_id, tx.transaction_type, sub_wh_code, current_year)
            if scope_key not in scope_groups:
                scope_groups[scope_key] = []
            scope_groups[scope_key].append(tx)

        total_scanned = len(txs_qs)
        updated = errors = 0

        for scope_key, txs_in_scope in scope_groups.items():
            faculty_id, tx_type, sub_wh_code, year = scope_key
            prefix = self._get_prefix(tx_type)
            faculty_seg = self._get_faculty_segment(faculty_id)

            # ✅ Sort chronologically to preserve historical sequence
            txs_in_scope.sort(key=lambda t: t.created_at)

            # ✅ Base pattern for this scope
            base_pattern = f"{prefix}-{faculty_seg}-{sub_wh_code}-{year}-"

            # ✅ START FROM 1 AND INCREMENT
            next_seq = 1

            for tx in txs_in_scope:
                new_doc = f"{base_pattern}{next_seq:04d}"

                if new_doc != tx.document_number:
                    if dry_run:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"✅ Would update TX #{tx.id} (Faculty {faculty_id}): "
                                f"'{tx.document_number}' → '{new_doc}'"
                            )
                        )
                        updated += 1
                    else:
                        try:
                            with db_transaction.atomic():
                                tx.document_number = new_doc
                                tx.save(
                                    update_fields=["document_number", "modified_at"]
                                )
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"✅ Updated TX #{tx.id} (Faculty {faculty_id}): '{new_doc}'"
                                )
                            )
                            updated += 1
                        except IntegrityError:
                            # Rare conflict: skip and continue incrementing
                            errors += 1
                            self.stdout.write(
                                self.style.WARNING(
                                    f"⚠️  Conflict on '{new_doc}' for TX #{tx.id}, skipping..."
                                )
                            )
                        except Exception as e:
                            errors += 1
                            self.stdout.write(
                                self.style.ERROR(
                                    f"❌ Failed to update TX #{tx.id}: {e}"
                                )
                            )

                next_seq += 1

        # Summary
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("SUMMARY"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Total transactions scanned: {total_scanned}")
        self.stdout.write(f"Skipped (no faculty): {skipped_no_faculty}")
        self.stdout.write(f"Updated (started from 0001): {updated}")
        self.stdout.write(f"Errors/Conflicts: {errors}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\n🔍 This was a DRY RUN. Use --force to apply changes."
                )
            )
        elif updated > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✅ Successfully updated {updated} transactions starting from 0001"
                )
            )
        else:
            self.stdout.write(self.style.WARNING("\n⚠️  No transactions were updated."))
