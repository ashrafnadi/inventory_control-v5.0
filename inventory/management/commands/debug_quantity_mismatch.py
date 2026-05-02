# inventory/management/commands/debug_quantity_mismatch.py
"""
تشخيص الفرق بين Item.cached_quantity و FacultyItemStock.cached_quantity

Usage:
    uv run manage.py debug_quantity_mismatch --item=501 --faculty=1
"""

import logging

from django.core.management.base import BaseCommand
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
    help = "تشخيص الفرق بين Item و FacultyItemStock quantities"

    def add_arguments(self, parser):
        parser.add_argument("--item", type=int, required=True, help="رقم الصنف للفحص")
        parser.add_argument("--faculty", type=int, required=True, help="رقم الكلية")

    def handle(self, *args, **options):
        item_id = options["item"]
        faculty_id = options["faculty"]

        item = Item.objects.select_related("category__sub_warehouse").get(id=item_id)
        faculty = Faculty.objects.get(id=faculty_id)
        target_sw = item.category.sub_warehouse if item.category else None

        self.stdout.write("=" * 70)
        self.stdout.write(f"🔍 تشخيص الصنف: {item.name} (ID: {item.id})")
        self.stdout.write(f"   الكلية: {faculty.name} (ID: {faculty_id})")
        self.stdout.write(
            f"   الفئة: {item.category.name if item.category else 'لا يوجد'}"
        )
        self.stdout.write(
            f"   المخزن الفرعي المستهدف: {target_sw.name if target_sw else 'لا يوجد'}"
        )
        self.stdout.write("=" * 70)

        # 1. عرض Item.cached_quantity
        self.stdout.write(f"\n📦 Item.cached_quantity: {item.cached_quantity}")

        # 2. عرض FacultyItemStock.cached_quantity
        try:
            fis = FacultyItemStock.objects.get(
                faculty=faculty, item=item, sub_warehouse=target_sw
            )
            self.stdout.write(
                f"📦 FacultyItemStock.cached_quantity: {fis.cached_quantity}"
            )
            self.stdout.write(f"   (ID: {fis.id})")
        except FacultyItemStock.DoesNotExist:
            self.stdout.write("❌ FacultyItemStock record DOES NOT EXIST")
            fis = None

        # 3. حساب الكمية من المعاملات (نفس منطق Item.batch_update_cached_quantities)
        self.stdout.write("\n📊 حساب الكمية من المعاملات:")

        details = ItemTransactionDetails.objects.filter(
            item=item,
            transaction__approval_status=ItemTransactions.APPROVAL_STATUS.APPROVED,
            transaction__deleted=False,
            transaction__is_reversed=False,
        )

        self.stdout.write(f"   إجمالي تفاصيل المعاملات المعتمدة: {details.count()}")

        # فلتر حسب الكلية
        details_by_faculty = details.filter(transaction__faculty=faculty)
        self.stdout.write(
            f"   بعد فلتر الكلية ({faculty.name}): {details_by_faculty.count()}"
        )

        # IN transactions
        in_q = (
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
                transaction__castody_type=ItemTransactions.CASTODY_TYPES.Warehouse,
                transaction__to_sub_warehouse=target_sw,
            )
        )

        incoming_all = (
            details.filter(in_q).aggregate(
                total=Coalesce(Sum("approved_quantity"), Value(0))
            )["total"]
            or 0
        )
        incoming_faculty = (
            details_by_faculty.filter(in_q).aggregate(
                total=Coalesce(Sum("approved_quantity"), Value(0))
            )["total"]
            or 0
        )

        self.stdout.write(f"\n   ✅ IN (كل الكليات): {incoming_all}")
        self.stdout.write(f"   ✅ IN (هذه الكلية فقط): {incoming_faculty}")

        # OUT transactions
        out_q = Q(
            transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Disbursement,
            transaction__from_sub_warehouse=target_sw,
        ) | Q(
            transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Transfer,
            transaction__castody_type=ItemTransactions.CASTODY_TYPES.Warehouse,
            transaction__from_sub_warehouse=target_sw,
        )

        outgoing_all = (
            details.filter(out_q).aggregate(
                total=Coalesce(Sum("approved_quantity"), Value(0))
            )["total"]
            or 0
        )
        outgoing_faculty = (
            details_by_faculty.filter(out_q).aggregate(
                total=Coalesce(Sum("approved_quantity"), Value(0))
            )["total"]
            or 0
        )

        self.stdout.write(f"\n   ❌ OUT (كل الكليات): {outgoing_all}")
        self.stdout.write(f"   ❌ OUT (هذه الكلية فقط): {outgoing_faculty}")

        # الكمية المتوقعة
        expected_all = max(0, incoming_all - outgoing_all)
        expected_faculty = max(0, incoming_faculty - outgoing_faculty)

        self.stdout.write("\n📈 الكمية المتوقعة:")
        self.stdout.write(f"   من كل الكليات: {expected_all}")
        self.stdout.write(f"   من هذه الكلية فقط: {expected_faculty}")

        # 4. عرض تفاصيل المعاملات
        self.stdout.write(
            f"\n📋 تفاصيل المعاملات ({details_by_faculty.count()} معاملة):"
        )
        for d in details_by_faculty.select_related(
            "transaction",
            "transaction__from_sub_warehouse",
            "transaction__to_sub_warehouse",
        ):
            tx = d.transaction
            direction = (
                "IN"
                if (
                    (
                        tx.transaction_type in ["A", "R"]
                        and tx.to_sub_warehouse_id == target_sw.id
                        if target_sw
                        else False
                    )
                    or (
                        tx.transaction_type == "T"
                        and tx.castody_type == "W"
                        and tx.to_sub_warehouse_id == target_sw.id
                        if target_sw
                        else False
                    )
                )
                else "OUT"
                if (
                    (
                        tx.transaction_type == "D"
                        and tx.from_sub_warehouse_id == target_sw.id
                        if target_sw
                        else False
                    )
                    or (
                        tx.transaction_type == "T"
                        and tx.castody_type == "W"
                        and tx.from_sub_warehouse_id == target_sw.id
                        if target_sw
                        else False
                    )
                )
                else "IGNORED"
            )

            self.stdout.write(
                f"   • {tx.document_number} | {tx.get_transaction_type_display()} | "
                f"Castody: {tx.get_castody_type_display()} | "
                f"From: {tx.from_sub_warehouse.name if tx.from_sub_warehouse else '-'} | "
                f"To: {tx.to_sub_warehouse.name if tx.to_sub_warehouse else '-'} | "
                f"Qty: {d.approved_quantity} → {direction}"
            )

        # 5. التشخيص النهائي
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("🔴 التشخيص:")
        self.stdout.write("=" * 70)

        if fis and fis.cached_quantity == 0 and expected_faculty > 0:
            self.stdout.write(
                self.style.ERROR(
                    f"❌ FacultyItemStock.cached_quantity = 0 لكن المتوقع = {expected_faculty}"
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    "💡 السبب الأرجح: المعاملات لا تتطابق مع faculty_id أو sub_warehouse_id"
                )
            )
        elif details_by_faculty.count() == 0:
            self.stdout.write(
                self.style.ERROR(
                    f"❌ لا توجد معاملات معتمدة لهذه الكلية ({faculty.name})"
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    "💡 السبب: المعاملات موجودة لكن faculty_id مختلف، أو approval_status != 'A'"
                )
            )
        elif incoming_faculty == 0 and outgoing_faculty == 0:
            self.stdout.write(
                self.style.ERROR("❌ المعاملات لا تتطابق مع target_sub_warehouse")
            )
            self.stdout.write(
                self.style.WARNING(
                    f"💡 السبب: item.category.sub_warehouse = {target_sw.name if target_sw else 'None'}\n"
                    f"     لكن المعاملات تستخدم مخزن فرعي مختلف"
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("✓ الكميات متطابقة"))

        self.stdout.write("\n💡 الحل المقترح:")
        if details_by_faculty.count() == 0:
            self.stdout.write(
                "   1. تأكد أن transaction.faculty_id = " + str(faculty_id)
            )
            self.stdout.write("   2. تأكد أن transaction.approval_status = 'A'")
        elif incoming_faculty == 0:
            self.stdout.write(
                "   1. تأكد أن item.category.sub_warehouse يطابق transaction.to_sub_warehouse"
            )
            self.stdout.write("   2. أو عدّل فئة الصنف لتشير للمخزن الصحيح")
        else:
            self.stdout.write(
                "   1. شغّل: uv run manage.py verify_stock_quantities --item="
                + str(item_id)
                + " --faculty="
                + str(faculty_id)
                + " --fix"
            )
