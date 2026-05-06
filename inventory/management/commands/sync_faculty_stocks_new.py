# inventory/management/commands/sync_faculty_stocks.py
"""
Sync FacultyItemStock.cached_quantity with transaction history for ALL faculties.
✅ Matches EXACT logic from item_history_view & calculate_authoritative_net_quantity.
✅ Uses document_number prefix (REV-) for accurate reversal handling.
✅ Features tqdm progress bar with real-time updates.

Sync ALL faculties with live progress bar

uv run manage.py sync_faculty_stocks_new

Dry-run to preview changes + see progress

uv run manage.py sync_faculty_stocks_new --dry-run

Sync specific faculty

uv run manage.py sync_faculty_stocks_new --faculty 3

Sync specific item across all faculties

uv run manage.py sync_faculty_stocks_new --item 2552
"""

import logging

from django.core.management.base import BaseCommand
from django.db.models import Case, F, IntegerField, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from tqdm import tqdm

from administration.models import Faculty
from inventory.models import FacultyItemStock, ItemTransactionDetails, ItemTransactions

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync all FacultyItemStock.cached_quantity with transaction history"

    def add_arguments(self, parser):
        parser.add_argument(
            "--faculty",
            type=int,
            required=False,
            help="Faculty ID (optional). If omitted, syncs ALL faculties.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Preview only")
        parser.add_argument("--item", type=int, help="Limit to specific item ID")

    def handle(self, *args, **options):
        faculty_id = options.get("faculty")
        dry_run = options["dry_run"]
        item_id_filter = options.get("item")

        # Determine faculties to sync
        if faculty_id:
            faculties = list(Faculty.objects.filter(id=faculty_id).order_by("name"))
        else:
            faculties = list(Faculty.objects.all().order_by("name"))

        if not faculties:
            self.stdout.write(self.style.ERROR("❌ No faculties found to sync."))
            return

        # Prepare queryset for progress bar total count
        base_stocks_qs = FacultyItemStock.objects.filter(faculty__in=faculties)
        if item_id_filter:
            base_stocks_qs = base_stocks_qs.filter(item_id=item_id_filter)

        total_count = base_stocks_qs.count()
        self.stdout.write(
            f"[START] Syncing {total_count} stock records across {len(faculties)} faculties"
        )
        if dry_run:
            self.stdout.write(
                self.style.WARNING("⚠️  [DRY RUN] - No database changes will be made")
            )

        total_updated = 0

        # ✅ tqdm progress bar
        with tqdm(
            total=total_count,
            desc="📦 Syncing stock records",
            unit="record",
            bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
        ) as pbar:
            for faculty in faculties:
                # Reset cache per faculty (quantities are faculty-scoped)
                calculated_nets = {}

                stocks = FacultyItemStock.objects.filter(
                    faculty=faculty
                ).select_related("item", "sub_warehouse")
                if item_id_filter:
                    stocks = stocks.filter(item_id=item_id_filter)

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
                                                Q(
                                                    transaction__transaction_type__in=[
                                                        "A",
                                                        "R",
                                                    ]
                                                )
                                                & ~Q(
                                                    transaction__document_number__startswith="REV-"
                                                ),
                                                then=F("approved_quantity"),
                                            ),
                                            # Reversal of Addition/Return (-)
                                            When(
                                                Q(
                                                    transaction__transaction_type__in=[
                                                        "A",
                                                        "R",
                                                    ]
                                                )
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
                        net = max(0, net)  # Clamp to zero
                        calculated_nets[item_id] = net

                    if stock.cached_quantity != net:
                        if not dry_run:
                            FacultyItemStock.objects.filter(pk=stock.pk).update(
                                cached_quantity=net, last_quantity_update=timezone.now()
                            )
                        total_updated += 1

                    # ✅ Update tqdm progress
                    pbar.update(1)

        # Final summary
        self.stdout.write(
            self.style.SUCCESS(
                f"\n🎉 [DONE] Sync complete. Updated {total_updated}/{total_count} records."
            )
        )
        if total_updated > 0 and dry_run:
            self.stdout.write(
                self.style.WARNING("💡 Run without --dry-run to apply changes.")
            )
