# inventory/management/commands/fix_cached_quantities.py
import logging

from django.core.management.base import BaseCommand
from django.db.models import Case, F, IntegerField, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from administration.models import Faculty
from inventory.models import (
    FacultyItemStock,
    Item,
    ItemTransactionDetails,
    ItemTransactions,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "تصحيح FacultyItemStock.cached_quantity ليطابق تماماً item_history_view"

    def add_arguments(self, parser):
        parser.add_argument(
            "--faculty", type=int, help="معرف الكلية المراد معالجتها (اختياري)"
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="معاينة التغييرات فقط بدون حفظ"
        )

    def handle(self, *args, **options):
        faculty_id = options.get("faculty")
        dry_run = options.get("dry_run", False)

        self.stdout.write(self.style.SUCCESS("🚀 بدء مزامنة الكميات..."))
        if dry_run:
            self.stdout.write(
                self.style.WARNING("⚠️  وضع المعاينة - لن يتم حفظ أي تغيير")
            )

        # جلب التراكيب الفريدة من كلية/صنف
        stocks_qs = FacultyItemStock.objects.select_related("faculty", "item")
        if faculty_id:
            stocks_qs = stocks_qs.filter(faculty_id=faculty_id)

        faculty_item_pairs = stocks_qs.values("faculty_id", "item_id").distinct()
        total_pairs = faculty_item_pairs.count()
        self.stdout.write(f"📊 جاري معالجة {total_pairs} تركيبة (كلية/صنف)...")

        updated_count = 0
        for idx, pair in enumerate(faculty_item_pairs, 1):
            faculty = Faculty.objects.get(id=pair["faculty_id"])
            item = Item.objects.get(id=pair["item_id"])

            # 🔑 نفس الـ Query المستخدم في item_history_view بالضبط
            net = (
                ItemTransactionDetails.objects.filter(
                    item=item,
                    transaction__faculty=faculty,
                    transaction__approval_status=ItemTransactions.APPROVAL_STATUS.APPROVED,
                    transaction__deleted=False,
                    transaction__transaction_type__in=["A", "D", "R"],
                )
                .exclude(transaction__document_number__startswith="REV-")
                .aggregate(
                    net=Coalesce(
                        Sum(
                            Case(
                                When(
                                    Q(transaction__transaction_type__in=["A", "R"])
                                    & Q(transaction__is_reversed=False),
                                    then=F("approved_quantity"),
                                ),
                                When(
                                    Q(transaction__transaction_type__in=["A", "R"])
                                    & Q(transaction__is_reversed=True),
                                    then=-F("approved_quantity"),
                                ),
                                When(
                                    Q(transaction__transaction_type="D")
                                    & Q(transaction__is_reversed=False),
                                    then=-F("approved_quantity"),
                                ),
                                When(
                                    Q(transaction__transaction_type="D")
                                    & Q(transaction__is_reversed=True),
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
            net = max(0, net)
            if not dry_run:
                FacultyItemStock.objects.filter(faculty=faculty, item=item).update(
                    cached_quantity=net,
                    limit_quantity=item.limit_quantity,
                    last_quantity_update=timezone.now(),
                )
                updated_count += 1
                if updated_count % 20 == 0 or idx == total_pairs:
                    self.stdout.write(
                        f"✅ [{idx}/{total_pairs}] تم تحديث: {item.name[:30]} → {net}"
                    )

        self.stdout.write(
            self.style.SUCCESS(f"\n🎉 اكتملت العملية! تم تحديث {updated_count} سجل.")
        )
