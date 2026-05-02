# inventory/management/commands/fix_category_subwarehouse_mismatch.py
import logging

from django.core.management.base import BaseCommand
from django.db.models import Count

from inventory.models import (
    Item,
    ItemTransactionDetails,
    ItemTransactions,
    SubWarehouse,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Find & fix items where transaction sub_warehouse != category.sub_warehouse"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Preview only")
        parser.add_argument("--faculty", type=int, help="Limit to faculty")
        parser.add_argument(
            "--auto-fix-category",
            action="store_true",
            help="Auto-assign category to most frequent SW",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        faculty_id = options.get("faculty")
        auto_fix = options["auto_fix_category"]

        self.stdout.write("🔍 جاري فحص تناقض المخازن...")
        if dry_run:
            self.stdout.write(self.style.WARNING("🛑 وضع المعاينة فقط"))

        # جلب الأصناف التي لها معاملات
        items = Item.objects.select_related("category__sub_warehouse").distinct()
        if faculty_id:
            items = items.filter(
                itemtransactiondetails__transaction__faculty_id=faculty_id
            )

        fixed = 0
        skipped = 0

        for item in items:
            # أكثر مخزن فرعي تكراراً في المعاملات المعتمدة
            most_common_sw = (
                ItemTransactionDetails.objects.filter(
                    item=item,
                    transaction__approval_status=ItemTransactions.APPROVAL_STATUS.APPROVED,
                    transaction__deleted=False,
                    transaction__is_reversed=False,
                )
                .values("transaction__to_sub_warehouse")
                .annotate(cnt=Count("id"))
                .order_by("-cnt")
                .first()
            )

            if (
                not most_common_sw
                or not most_common_sw["transaction__to_sub_warehouse"]
            ):
                continue

            target_sw_id = most_common_sw["transaction__to_sub_warehouse"]
            target_sw = SubWarehouse.objects.get(id=target_sw_id)

            if item.category.sub_warehouse_id == target_sw_id:
                continue  # متطابق، تخطى

            skipped += 1
            if dry_run:
                self.stdout.write(
                    f"  ⚠️  {item.name} | Category SW: {item.category.sub_warehouse.name} | Tx SW: {target_sw.name}"
                )
                continue

            if auto_fix:
                # تحديث الفئة لتشير للمخزن الفعلي
                item.category.sub_warehouse = target_sw
                item.category.save(update_fields=["sub_warehouse"])
                self.stdout.write(
                    self.style.SUCCESS(f"  ✓ Fixed category SW for: {item.name}")
                )
                fixed += 1

        self.stdout.write("\n📋 SUMMARY")
        self.stdout.write(f"• Items checked: {items.count()}")
        self.stdout.write(f"• Mismatches found: {skipped}")
        self.stdout.write(f"• Fixed: {fixed}")
        if not dry_run and auto_fix and fixed > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    "\n✅ تم التصحيح. شغّل populate_faculty_item_stock الآن لتحديث الكميات."
                )
            )
