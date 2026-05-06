# inventory/models.py
import logging
import re

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.db import transaction as db_transaction
from django.db.models import Case, F, IntegerField, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

# ... (inside ItemTransactions class) ...
from administration.models import Department, Faculty, InventoryYear

logger = logging.getLogger(__name__)


# inventory/models.py


def calculate_authoritative_net_quantity(item, faculty, sub_warehouse=None):
    """
    Authoritative quantity calculation that properly handles reversals.
    - Excludes REV- documents
    - Excludes original transactions where is_reversed=True
    - Excludes reversal transactions (reversed_transaction__isnull=False)
    """
    qs = (
        ItemTransactionDetails.objects.filter(
            item=item,
            transaction__faculty=faculty,
            transaction__approval_status=ItemTransactions.APPROVAL_STATUS.APPROVED,
            transaction__deleted=False,
            transaction__transaction_type__in=["A", "D", "R"],
        )
        .exclude(
            # Exclude manual REV- documents
            transaction__document_number__startswith="REV-"
        )
        .exclude(
            # Exclude original transactions that have been reversed
            transaction__is_reversed=True
        )
        .exclude(
            # Exclude reversal transactions (they reference original via reversed_transaction)
            transaction__reversed_transaction__isnull=False
        )
    )

    # Strict sub_warehouse matching
    if sub_warehouse:
        qs = qs.filter(
            Q(transaction__to_sub_warehouse=sub_warehouse)
            | Q(transaction__from_sub_warehouse=sub_warehouse)
        )

    net = (
        qs.aggregate(
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

    return max(0, net)


class Warehouse(models.Model):
    """Global warehouse - shared across all faculties."""

    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="اسم المخزن الرئيسي",
    )

    class Meta:
        verbose_name = "المخزن الرئيسي"
        verbose_name_plural = "المخازن الرئيسية"
        ordering = ["name"]

    def __str__(self):
        return self.name


class SubWarehouse(models.Model):
    """
    Global sub-warehouse - shared across all faculties.
    Names must be unique globally (not per-faculty).
    """

    name = models.CharField(
        max_length=100,
        verbose_name="اسم المخزن الفرعي",
    )
    code = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        verbose_name="كود المخزن",
        help_text="كود مختصر للمخزن يُستخدم في أرقام المستندات (اختياري)",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        verbose_name="المخزن الرئيسي",
        related_name="sub_warehouses",
    )

    class Meta:
        verbose_name = "المخزن الفرعي"
        verbose_name_plural = "المخازن الفرعية"
        unique_together = ("name",)
        indexes = [models.Index(fields=["code"])]

    def __str__(self):
        return f"{self.name} ({self.warehouse.name})"

    def save(self, *args, **kwargs):
        # Auto-generate code after the object has a PK
        is_new = self.pk is None
        logger.info(
            f"SubWarehouse save: is_new={is_new}, pk={self.pk}, name={self.name}"
        )
        super().save(*args, **kwargs)
        if not self.code and self.name:
            name_part = "".join(c for c in self.name[:3].upper() if c.isalnum())
            self.code = f"{name_part}{self.id:03d}"
            # Avoid recursive save loop – update only the code column directly
            SubWarehouse.objects.filter(pk=self.pk).update(code=self.code)


class ItemCategory(models.Model):
    """Global item category - shared across all faculties."""

    name = models.CharField(max_length=100, verbose_name="اسم فئة الصنف")
    sub_warehouse = models.ForeignKey(
        SubWarehouse,
        on_delete=models.CASCADE,
        verbose_name="المخازن الفرعية",
        related_name="item_categories",
    )

    class Meta:
        verbose_name = "فئة الصنف"
        verbose_name_plural = "فئات الأصناف"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return self.name


class Item(models.Model):
    """
    Global item catalog - shared across all faculties.

    - Item names/codes are globally unique (no duplication across faculties)
    - Quantities per faculty are stored in FacultyItemStock
    - Legacy cached_quantity is kept for backward compatibility
    """

    class ITEM_UNITS(models.TextChoices):
        Quantity = "Q", "عدد"
        Set = "S", "طقم"
        Kilogram = "K", "كيلو"
        Sheet = "L", "لفة"
        Book = "D", "دفتر"
        Piece = "P", "قطعة"
        Meter = "M", "متر"
        Sarnaja = "R", "سرنجة"
        Pack = "Z", "رزمة"
        Glass = "J", "زجاجة"
        Box = "B", "علبة"
        Vial = "F", "فيال"
        Strip = "I", "شريط"
        Pen = "N", "قلم"
        Bottle = "E", "أنبوبة"
        Capsule = "X", "خرطوش"
        Ampoule = "A", "أمبول"
        Case = "C", "كيس"
        Basket = "T", "بكرة"
        Package = "U", "عبوة"
        Sawal = "G", "شوال"
        Carton = "O", "كرتونة"
        Bag = "Y", "كيس"
        Litre = "H", "لتر"

    code = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True,
        help_text="يمكن تعديله، يجب أن يكون فريداً",
        verbose_name="كود الصنف",
    )

    name = models.CharField(
        max_length=1000,
        unique=True,
        verbose_name="اسم الصنف",
        help_text="يجب أن يكون اسم الصنف فريداً عالمياً",
    )

    category = models.ForeignKey(
        ItemCategory, on_delete=models.CASCADE, verbose_name="فئة الصنف"
    )
    limit_quantity = models.PositiveIntegerField(verbose_name="حد الكمية")
    unit_fraction = models.PositiveIntegerField(default=1, verbose_name="كسر الوحدة")
    unit = models.CharField(
        max_length=2,
        choices=ITEM_UNITS.choices,
        default=ITEM_UNITS.Quantity,
        verbose_name="وحدة القياس",
    )
    spacefication = models.TextField(
        verbose_name="مواصفات الصنف", blank=True, null=True
    )

    cached_quantity = models.IntegerField(
        default=0,
        verbose_name="الكمية المخزنة",
        help_text="تُحدَّث تلقائياً عند اعتماد السندات فقط",
    )
    last_quantity_update = models.DateTimeField(
        null=True, blank=True, verbose_name="آخر تحديث للكمية"
    )
    item_image = models.ImageField(
        upload_to="item_images/",
        blank=True,
        null=True,
        verbose_name="صورة الصنف",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="أنشئ بواسطة",
        related_name="created_items",
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="حدث بواسطة",
        related_name="updated_items",
    )

    class Meta:
        verbose_name = "الصنف"
        verbose_name_plural = "الأصناف"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["cached_quantity"]),
            models.Index(fields=["last_quantity_update"]),
            models.Index(fields=["cached_quantity", "limit_quantity"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cached_quantity__gte=0),
                name="non_negative_quantity",
            ),
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    def current_quantity(self):
        """Return total quantity across all faculty stock rows."""
        total = self.faculty_stocks.aggregate(
            total=Coalesce(Sum("cached_quantity"), Value(0))
        )["total"]
        return total or 0

    def is_low_stock(self):
        return self.cached_quantity <= self.limit_quantity and self.cached_quantity > 0

    def is_out_of_stock(self):
        return self.cached_quantity == 0

    def current_quantity_for_sub_warehouse(self, sub_warehouse):
        """Get current quantity in a specific sub-warehouse across faculties."""
        total = self.faculty_stocks.filter(sub_warehouse=sub_warehouse).aggregate(
            total=Coalesce(Sum("cached_quantity"), Value(0))
        )["total"]
        return total or 0

    def current_quantity_for_user(self, user):
        """
        Get current quantity owned by a specific user - APPROVED TRANSACTIONS ONLY.
        Calculates: (Approved Disbursements TO user + Approved Transfers TO user)
        - (Approved Transfers FROM user + Approved Returns FROM user)
        """
        if not user or not hasattr(user, "id"):
            return 0

        approved_status = ItemTransactions.APPROVAL_STATUS.APPROVED
        user_faculty_id = getattr(getattr(user, "profile", None), "faculty_id", None)
        faculty_filter = (
            {"transaction__faculty_id": user_faculty_id} if user_faculty_id else {}
        )

        disbursements = (
            ItemTransactionDetails.objects.filter(
                item=self,
                transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Disbursement,
                transaction__to_user=user,
                transaction__approval_status=approved_status,
                transaction__deleted=False,
                **faculty_filter,
            ).aggregate(total=Coalesce(Sum("approved_quantity"), Value(0)))["total"]
            or 0
        )

        transfers_in = (
            ItemTransactionDetails.objects.filter(
                item=self,
                transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Transfer,
                transaction__to_user=user,
                transaction__approval_status=approved_status,
                transaction__deleted=False,
                **faculty_filter,
            ).aggregate(total=Coalesce(Sum("approved_quantity"), Value(0)))["total"]
            or 0
        )

        transfers_out = (
            ItemTransactionDetails.objects.filter(
                item=self,
                transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Transfer,
                transaction__from_user=user,
                transaction__approval_status=approved_status,
                transaction__deleted=False,
                **faculty_filter,
            ).aggregate(total=Coalesce(Sum("approved_quantity"), Value(0)))["total"]
            or 0
        )

        returns = (
            ItemTransactionDetails.objects.filter(
                item=self,
                transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Return,
                transaction__from_user=user,
                transaction__approval_status=approved_status,
                transaction__deleted=False,
                **faculty_filter,
            ).aggregate(total=Coalesce(Sum("approved_quantity"), Value(0)))["total"]
            or 0
        )

        return max(0, disbursements + transfers_in - transfers_out - returns)

    def get_stock_status(self):
        """Get human-readable stock status."""
        if self.cached_quantity <= 0:
            return "نافد"
        elif self.cached_quantity <= self.limit_quantity:
            return "احتياطي منخفض"
        return "متوفر"

    @classmethod
    def sync_global_quantity(cls, item_id):
        """
        Set Item.cached_quantity = SUM(FacultyItemStock.cached_quantity).
        Single source of truth: never calculates from transactions directly.
        """
        from django.db.models import Sum, Value
        from django.db.models.functions import Coalesce

        total = (
            FacultyItemStock.objects.filter(item_id=item_id).aggregate(
                total=Coalesce(Sum("cached_quantity"), Value(0))
            )["total"]
            or 0
        )

        cls.objects.filter(id=item_id).update(
            cached_quantity=total, last_quantity_update=timezone.now()
        )
        return total

    def __str__(self):
        return self.name

    def to_dict(self):
        """Convert item to dictionary for audit logging."""
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "sub_warehouse": self.sub_warehouse.id if self.sub_warehouse else None,
            "warehouse": self.warehouse.id if self.warehouse else None,
            "category": self.category.id if self.category else None,
            "cached_quantity": self.cached_quantity,
            "limit_quantity": self.limit_quantity,
            "unit": self.unit,
            "unit_fraction": self.unit_fraction,
            "spacefication": self.spacefication,
        }


class FacultyItemStock(models.Model):
    """Faculty-isolated quantity for a shared item in a shared sub-warehouse."""

    faculty = models.ForeignKey(
        Faculty,
        on_delete=models.CASCADE,
        related_name="item_stocks",
        verbose_name="الكلية",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="faculty_stocks",
        verbose_name="الصنف",
    )
    sub_warehouse = models.ForeignKey(
        SubWarehouse,
        on_delete=models.CASCADE,
        related_name="item_stocks",
        verbose_name="المخزن الفرعي",
    )
    cached_quantity = models.IntegerField(default=0, verbose_name="الكمية المخزنة")
    limit_quantity = models.PositiveIntegerField(default=0, verbose_name="حد الكمية")
    last_quantity_update = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="آخر تحديث للكمية",
    )

    class Meta:
        verbose_name = "مخزون الكلية"
        verbose_name_plural = "مخزون الكليات"
        unique_together = ("faculty", "item", "sub_warehouse")
        indexes = [
            models.Index(fields=["faculty", "sub_warehouse", "cached_quantity"]),
            models.Index(fields=["faculty", "item", "sub_warehouse"]),
            models.Index(fields=["cached_quantity", "limit_quantity"]),
            models.Index(fields=["faculty", "sub_warehouse", "item"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cached_quantity__gte=0),
                name="non_negative_faculty_stock_quantity_v2",
            )
        ]

    def __str__(self):
        return f"{self.faculty.name} - {self.sub_warehouse.name} - {self.item.name}"

    def get_stock_status(self):
        if self.cached_quantity <= 0:
            return "نفذ"
        if self.cached_quantity <= self.limit_quantity:
            return "احتياطي منخفض"
        return "متوفر"

    @classmethod
    def get_or_create_for(cls, item, sub_warehouse, faculty, limit_quantity=None):
        return cls.objects.get_or_create(
            faculty=faculty,
            item=item,
            sub_warehouse=sub_warehouse,
            defaults={"limit_quantity": limit_quantity or item.limit_quantity},
        )

    @classmethod
    def recalculate_authoritative(cls, item, faculty, sub_warehouse):
        """Update FacultyItemStock using the exact view logic. Returns the new quantity (int)."""
        net_qty = calculate_authoritative_net_quantity(item, faculty, sub_warehouse)
        cls.objects.update_or_create(
            faculty=faculty,
            item=item,
            sub_warehouse=sub_warehouse,
            defaults={
                "cached_quantity": net_qty,
                "limit_quantity": item.limit_quantity,
                "last_quantity_update": timezone.now(),
            },
        )
        return net_qty

    @classmethod
    def recalculate_total_faculty_quantity(cls, faculty, item):
        """
        Calculates net approved quantity for an item across ALL sub-warehouses in a faculty.
        Updates ALL FacultyItemStock records for this faculty/item with the same total.
        Uses authoritative logic.
        """
        net_qty = calculate_authoritative_net_quantity(
            item, faculty, sub_warehouse=None
        )

        # Update ALL FacultyItemStock records for this faculty/item to the total faculty quantity
        cls.objects.filter(faculty=faculty, item=item).update(
            cached_quantity=net_qty,
            limit_quantity=item.limit_quantity,
            last_quantity_update=timezone.now(),
        )
        return net_qty

    @classmethod
    def batch_recalculate(cls, items, sub_warehouses, faculty=None):
        """
        Recalculate authoritative quantities for multiple items & sub-warehouses.
        :param items: QuerySet or list of Item instances
        :param sub_warehouses: QuerySet or list of SubWarehouse instances
        :param faculty: Faculty instance (required)
        """
        if not faculty:
            return

        for item in items:
            for sub_warehouse in sub_warehouses:
                cls.recalculate_authoritative(
                    item=item,
                    faculty=faculty,
                    sub_warehouse=sub_warehouse,
                )


class ItemPriceHistory(models.Model):
    """Track price history for items."""

    item = models.ForeignKey(Item, on_delete=models.CASCADE, verbose_name="الصنف")
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="السعر")
    date = models.DateTimeField(auto_now_add=True, verbose_name="التاريخ")

    class Meta:
        verbose_name = "تاريخ سعر الصنف"
        verbose_name_plural = "تاريخ سعر الأصناف"
        ordering = ["-date"]
        indexes = [models.Index(fields=["item", "-date"])]

    def __str__(self):
        return f"{self.item.name} - {self.price} - {self.date}"


class Supplier(models.Model):
    """Global supplier catalog."""

    name = models.CharField(max_length=100, unique=True, verbose_name="اسم الشركة")
    company_address = models.CharField(max_length=255, verbose_name="العنوان")
    company_phone = models.CharField(max_length=20, verbose_name="الهاتف")
    company_email = models.EmailField(
        null=True, blank=True, verbose_name="البريد الإلكتروني"
    )
    company_notes = models.TextField(null=True, blank=True, verbose_name="ملاحظات")
    contact_name = models.CharField(max_length=100, verbose_name="اسم المندوب")
    contact_address = models.CharField(max_length=255, verbose_name="العنوان")
    contact_phone = models.CharField(max_length=20, verbose_name="الهاتف")
    contact_email = models.EmailField(
        null=True, blank=True, verbose_name="البريد الإلكتروني"
    )
    contact_notes = models.TextField(null=True, blank=True, verbose_name="ملاحظات")

    class Meta:
        verbose_name = "المورد"
        verbose_name_plural = "الموردين"

    def __str__(self):
        return self.name


class ItemTransactions(models.Model):
    """
    Transaction record - faculty-isolated.
    Each transaction belongs to a specific faculty and can only be viewed/managed
    by users from that faculty (except superusers).
    """

    class TRANSACTION_TYPES(models.TextChoices):
        Addition = "A", "إضافة"
        Disbursement = "D", "صرف"
        Transfer = "T", "نقل عهدة"
        Return = "R", "ارجاع"

    class CASTODY_TYPES(models.TextChoices):
        Warehouse = "W", "عهدة مخزنية"
        Personal = "P", "عهدة شخصية"
        Branch = "B", "عهدة فرعية"

    class TRANSACTION_DOCUMENT_TYPES(models.TextChoices):
        Invoice = "I", "فاتورة"
        Return = "R", "إذن ارتجاع"
        Disbursement = "D", "إذن صرف"
        Increase = "C", "كشف زيادة"
        Administrative = "A", "شهادة إدارية"
        Balance = "B", "كشف عجز"
        Discount = "S", "سند خصم أصناف فاقدة أو تالفة"
        Sale = "M", "محضر بيع"
        Start = "T", "طلب تشغيل"
        Gift = "G", "إهداءات ليست النشاط الرئيسي للجهة"
        Exchange = "E", "طلب ارتجاع أصناف"
        Transfer = "F", "نقل عهدة"

    class APPROVAL_STATUS(models.TextChoices):
        PENDING = "P", "قيد الانتظار"
        APPROVED = "A", "معتمد"
        REJECTED = "R", "مرفوض"
        DELETED = "D", "محذوف"

    document_number = models.CharField(
        max_length=50,
        verbose_name="رقم المستند",
        blank=True,
        editable=False,
        unique=False,
    )
    transaction_type = models.CharField(
        max_length=1,
        choices=TRANSACTION_TYPES.choices,
        default=TRANSACTION_TYPES.Addition,
        verbose_name="نوع المعاملة",
    )
    castody_type = models.CharField(
        max_length=1,
        choices=CASTODY_TYPES.choices,
        default=CASTODY_TYPES.Warehouse,
        verbose_name="نوع العهدة",
    )
    document_type = models.CharField(
        max_length=1,
        choices=TRANSACTION_DOCUMENT_TYPES.choices,
        default=TRANSACTION_DOCUMENT_TYPES.Invoice,
        verbose_name="نوع المستند",
    )
    from_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name="from_main_transactions",
        null=True,
        blank=True,
        verbose_name="من المخزن الرئيسي",
    )
    to_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name="to_main_transactions",
        null=True,
        blank=True,
        verbose_name="إلى المخزن الرئيسي",
    )
    from_sub_warehouse = models.ForeignKey(
        SubWarehouse,
        on_delete=models.CASCADE,
        related_name="from_sub_transactions",
        null=True,
        blank=True,
        verbose_name="من المخزن الفرعي",
    )
    to_sub_warehouse = models.ForeignKey(
        SubWarehouse,
        on_delete=models.CASCADE,
        related_name="to_sub_transactions",
        null=True,
        blank=True,
        verbose_name="إلى المخزن الفرعي",
    )
    from_department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="from_transactions",
        null=True,
        blank=True,
        verbose_name="من القسم",
    )
    to_department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="to_transactions",
        null=True,
        blank=True,
        verbose_name="إلى القسم",
    )
    from_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="from_transactions",
        null=True,
        blank=True,
        verbose_name="من المستخدم",
    )
    to_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="to_transactions",
        null=True,
        blank=True,
        verbose_name="إلى المستخدم",
    )
    notes = models.TextField(null=True, blank=True, verbose_name="ملاحظات")
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        related_name="transactions",
        null=True,
        blank=True,
        verbose_name="المورد",
    )
    inventory_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="inventory_transactions",
        null=True,
        blank=True,
        verbose_name="موظف المخزن",
    )
    approval_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="approved_transactions",
        null=True,
        blank=True,
        verbose_name="المشرف",
    )
    approval_status = models.CharField(
        max_length=1,
        choices=APPROVAL_STATUS.choices,
        default=APPROVAL_STATUS.PENDING,
        verbose_name="حالة الاعتماد",
    )
    approval_date = models.DateTimeField(
        null=True, blank=True, verbose_name="تاريخ الاعتماد"
    )
    approval_notes = models.TextField(
        blank=True, null=True, verbose_name="ملاحظات الاعتماد"
    )
    deleted = models.BooleanField(default=False, verbose_name="محذوف")
    deleted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="deleted_transactions",
        null=True,
        blank=True,
        verbose_name="حُذف بواسطة",
    )
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ الحذف")
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="created_transactions",
        null=True,
        blank=True,
        verbose_name="أنشئ بواسطة",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")
    modified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="modified_transactions",
        null=True,
        blank=True,
        verbose_name="عُدل بواسطة",
    )
    modified_at = models.DateTimeField(
        null=True, blank=True, verbose_name="تاريخ التعديل"
    )
    is_reversed = models.BooleanField(
        default=False, verbose_name="تم عكسه", help_text="هل تم عكس هذا السند؟"
    )
    reversed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reversed_transactions",
        verbose_name="عكس بواسطة",
    )
    reversed_at = models.DateTimeField(
        null=True, blank=True, verbose_name="تاريخ العكس"
    )
    reversed_transaction = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="original_transaction",
        verbose_name="سند العكس",
        help_text="السند الذي تم إنشاؤه لعكس هذا السند",
    )
    faculty = models.ForeignKey(
        Faculty,
        on_delete=models.CASCADE,
        verbose_name="الكلية",
        help_text="الكلية المالكة لهذا السند",
    )
    year = models.ForeignKey(
        InventoryYear,
        on_delete=models.PROTECT,
        related_name="transactions",
        verbose_name="سنة المخزون",
        null=True,
        blank=True,
        help_text="السنة المفتوحة وقت إنشاء السند.",
    )

    class Meta:
        verbose_name = "السند"
        verbose_name_plural = "السندات"
        indexes = [
            models.Index(fields=["from_warehouse", "created_at"]),
            models.Index(fields=["to_warehouse", "created_at"]),
            models.Index(fields=["from_sub_warehouse", "created_at"]),
            models.Index(fields=["to_sub_warehouse", "created_at"]),
            models.Index(fields=["approval_status", "created_at"]),
            models.Index(
                fields=["transaction_type", "from_sub_warehouse", "document_number"]
            ),
            models.Index(fields=["is_reversed"]),
            models.Index(fields=["faculty", "created_at"]),
            models.Index(fields=["faculty", "approval_status"]),
            models.Index(fields=["year", "created_at"]),
            models.Index(fields=["year", "faculty", "-created_at"]),
            models.Index(fields=["faculty", "approval_status", "-created_at"]),
            models.Index(fields=["created_by", "faculty", "-created_at"]),
            models.Index(fields=["document_number"]),
            models.Index(fields=["notes"], name="idx_notes_search"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["transaction_type", "from_sub_warehouse", "document_number"],
                name="unique_doc_from_sub_warehouse",
                condition=models.Q(transaction_type__in=["D", "T"]),
            ),
        ]
        permissions = [
            ("approve_transaction", "يمكنه اعتماد السندات"),
            ("reject_transaction", "يمكنه رفض السندات"),
        ]

    def _get_scope_sub_warehouse(self):
        """
        Get the sub-warehouse that defines the scope for document_number uniqueness.
        - Addition/Return: use to_sub_warehouse (destination)
        - Disbursement/Transfer: use from_sub_warehouse (source)
        """
        if self.transaction_type in [
            self.TRANSACTION_TYPES.Addition,
            self.TRANSACTION_TYPES.Return,
        ]:
            return self.to_sub_warehouse
        return self.from_sub_warehouse

    @classmethod
    def _generate_document_number(
        cls, transaction_type, scope_sub_warehouse, faculty_id=None
    ):
        """
        Generate a strictly faculty & transaction-type isolated document number.
        Scope: (faculty_id, transaction_type, sub_warehouse, year)
        Starts at 0001 if no transactions exist, otherwise max_existing + 1.
        """

        type_prefixes = {
            cls.TRANSACTION_TYPES.Addition: "ADD",
            cls.TRANSACTION_TYPES.Disbursement: "DIS",
            cls.TRANSACTION_TYPES.Transfer: "TRF",
            cls.TRANSACTION_TYPES.Return: "RET",
        }
        prefix = type_prefixes.get(transaction_type, "DOC")
        faculty_segment = f"B{faculty_id}" if faculty_id else "B0"

        if scope_sub_warehouse:
            sub_wh_code = getattr(scope_sub_warehouse, "code", None)
            if not sub_wh_code:
                name_part = "".join(
                    c for c in scope_sub_warehouse.name[:3].upper() if c.isalnum()
                )
                sub_wh_code = f"{name_part}{scope_sub_warehouse.id:03d}"
        else:
            sub_wh_code = "GEN"

        current_year = InventoryYear.get_open_year().year
        base_pattern = f"{prefix}-{faculty_segment}-{sub_wh_code}-{current_year}-"

        # Strict regex to match ONLY numbers in this exact scope
        pattern_regex = (
            rf"^{re.escape(prefix)}-"
            rf"{re.escape(faculty_segment)}-"
            rf"{re.escape(sub_wh_code)}-"
            rf"{re.escape(str(current_year))}-"
            r"(\d+)$"
        )

        # 🔑 STRICT FACULTY ISOLATION: Filter directly by the faculty FK
        qs = cls.objects.filter(
            faculty_id=faculty_id,
            transaction_type=transaction_type,
            document_number__regex=pattern_regex,
        ).exclude(document_number="")

        # Apply sub-warehouse scope per transaction type
        if transaction_type in [
            cls.TRANSACTION_TYPES.Addition,
            cls.TRANSACTION_TYPES.Return,
        ]:
            qs = qs.filter(to_sub_warehouse=scope_sub_warehouse)
        else:
            qs = qs.filter(from_sub_warehouse=scope_sub_warehouse)

        # Find max existing sequential number in this scope
        max_number = 0
        for doc_num in qs.values_list("document_number", flat=True):
            match = re.match(pattern_regex, doc_num)
            if match:
                try:
                    num = int(match.group(1))
                    if num > max_number:
                        max_number = num
                except (ValueError, IndexError):
                    continue

        # Starts at 1 if max_number is 0, otherwise max + 1
        next_number = max_number + 1
        return f"{base_pattern}{next_number:04d}"

    def _get_affected_items(self):
        """Get all items affected by this transaction."""
        item_ids = self.itemtransactiondetails_set.values_list("item_id", flat=True)
        return Item.objects.filter(id__in=item_ids)

    def delete(self, *args, **kwargs):
        """Override delete to recalculate quantities AFTER soft delete."""
        affected_items = self._get_affected_items()
        sub_warehouses = [
            sw for sw in [self.from_sub_warehouse, self.to_sub_warehouse] if sw
        ]

        result = super().delete(*args, **kwargs)

        if affected_items.exists():
            for item in affected_items:
                if sub_warehouses:
                    for sw in sub_warehouses:
                        FacultyItemStock.recalculate_authoritative(
                            item, self.faculty, sw
                        )
                else:
                    # Fallback: recalculate all existing stocks for this item/faculty
                    for stock in FacultyItemStock.objects.filter(
                        faculty=self.faculty, item=item
                    ).select_related("sub_warehouse"):
                        FacultyItemStock.recalculate_authoritative(
                            item, self.faculty, stock.sub_warehouse
                        )
                # Sync global Item.cached_quantity
                Item.sync_global_quantity(item.id)

        return result

    def reverse_transaction(self, user, reason=""):
        """
        Reverse this transaction by marking it as reversed and creating an audit-only reversal record.
        Does NOT create a new inventory-affecting transaction.
        """
        if self.is_reversed:
            raise ValueError("هذا السند تم عكسه مسبقاً ولا يمكن عكسه مرة أخرى")
        if self.approval_status != self.APPROVAL_STATUS.APPROVED:
            raise ValueError("يمكن فقط عكس السندات المعتمدة")

        with db_transaction.atomic():
            # Mark original as reversed
            self.is_reversed = True
            self.reversed_by = user
            self.reversed_at = timezone.now()
            self.notes = f"{self.notes or ''} | تم عكس السند بسبب: {reason}"
            self.save(
                update_fields=["is_reversed", "reversed_by", "reversed_at", "notes"]
            )

            # Create SIMPLE reversal record for audit trail (NOT for inventory calculation)
            reversal = ItemTransactions.objects.create(
                document_number=f"REV-{self.document_number}",
                transaction_type=self.transaction_type,
                castody_type=self.castody_type,
                document_type=self.document_type,
                faculty=self.faculty,
                from_warehouse=self.to_warehouse,
                to_warehouse=self.from_warehouse,
                from_sub_warehouse=self.to_sub_warehouse,
                to_sub_warehouse=self.from_sub_warehouse,
                from_department=self.to_department,
                to_department=self.from_department,
                from_user=self.to_user,
                to_user=self.from_user,
                inventory_user=self.inventory_user,
                notes=f"عكس للسند {self.document_number}: {reason}",
                approval_status=self.APPROVAL_STATUS.APPROVED,
                created_by=user,
                year=self.year,
                # Mark reversal as non-inventory affecting
                is_reversed=False,  # This is the reversal itself
                reversed_transaction=self,  # Points back to original
            )

            # Copy details for audit trail
            for detail in self.itemtransactiondetails_set.all():
                ItemTransactionDetails.objects.create(
                    transaction=reversal,
                    item=detail.item,
                    order_quantity=detail.approved_quantity,
                    approved_quantity=detail.approved_quantity,
                    status=detail.status,
                    price=detail.price,
                )

            # Log audit action
            TransactionAuditLog.objects.create(
                transaction=reversal,
                action=TransactionAuditLog.ACTION_TYPES.CREATE,
                performed_by=user,
                transaction_snapshot=reversal.to_dict(),
                details=f"تم عكس السند {self.document_number}: {reason}",
            )

            # Recalculate affected items AFTER marking original as reversed
            self._recalculate_affected_items()

            return reversal

    def save(self, *args, **kwargs):
        """Override save to auto-generate document_number and recalculate quantities."""
        is_new = self.pk is None

        if is_new and not self.year_id:
            self.year = InventoryYear.get_open_year()

        if (
            not self.faculty_id
            and self.created_by
            and hasattr(self.created_by, "profile")
        ):
            self.faculty = self.created_by.profile.faculty

        if is_new and not self.document_number:
            with db_transaction.atomic():
                scope_sub_warehouse = self._get_scope_sub_warehouse()
                faculty_id = None
                if self.created_by and hasattr(self.created_by, "profile"):
                    faculty_id = self.created_by.profile.faculty_id
                self.document_number = self._generate_document_number(
                    self.transaction_type, scope_sub_warehouse, faculty_id=faculty_id
                )

        old_approval_status = None
        if not is_new:
            try:
                old = ItemTransactions.objects.get(pk=self.pk)
                old_approval_status = old.approval_status
            except ItemTransactions.DoesNotExist:
                pass

        super().save(*args, **kwargs)

        if not is_new and old_approval_status != self.approval_status:
            self._recalculate_affected_items()
        if is_new and self.approval_status == self.APPROVAL_STATUS.APPROVED:
            self._recalculate_affected_items()

    def __str__(self):
        return f"{self.document_number} ({self.get_transaction_type_display()})"

    def clean(self):
        """Validate transaction before saving."""
        super().clean()
        if not self.created_by:
            raise ValidationError("يجب تحديد الموظف المُنشئ للسند.")
        if hasattr(self.created_by, "profile"):
            if not self.created_by.profile.faculty:
                raise ValidationError("الموظف المُنشئ يجب أن يكون له كليّة مرتبطة.")
        else:
            raise ValidationError("حساب الموظف المُنشئ غير مكتمل (لا يوجد Profile).")

    def can_be_approved_by_user(self, user):
        """Check if user has permission to approve this transaction."""
        if not (hasattr(user, "profile") and user.profile.is_inventory_manager):
            return False
        return (
            self.approval_status == self.APPROVAL_STATUS.PENDING
            and hasattr(self.created_by, "profile")
            and hasattr(user, "profile")
            and self.created_by.profile.faculty_id == user.profile.faculty_id
        )

    def approve(self, user, notes=None):
        """Approve transaction and update quantities - ATOMIC OPERATION"""
        if not self.can_be_approved_by_user(user):
            raise PermissionDenied("ليس لديك صلاحية اعتماد هذا السند.")
        if self.approval_status != self.APPROVAL_STATUS.PENDING:
            raise ValueError("السند ليس في حالة انتظار الاعتماد")

        with db_transaction.atomic():
            self.approval_status = self.APPROVAL_STATUS.APPROVED
            self.approval_user = user
            self.approval_date = timezone.now()
            self.approval_notes = notes
            self.save()
            return True

    def reject(self, user, notes=None):
        """Reject transaction - NO quantity updates"""
        if not self.can_be_approved_by_user(user):
            raise PermissionDenied("ليس لديك صلاحية رفض هذا السند.")
        if self.approval_status != self.APPROVAL_STATUS.PENDING:
            raise ValueError("السند ليس في حالة انتظار الاعتماد")

        self.approval_status = self.APPROVAL_STATUS.REJECTED
        self.approval_user = user
        self.approval_date = timezone.now()
        self.approval_notes = notes or "مرفوض بدون سبب محدد"
        self.save()
        return True

    def to_dict(self):
        """Convert transaction to dictionary for audit logging."""
        return {
            "id": self.id,
            "document_number": self.document_number,
            "transaction_type": self.get_transaction_type_display(),
            "year": self.year.year if self.year else None,
            "castody_type": self.get_castody_type_display(),
            "document_type": self.get_document_type_display()
            if self.document_type
            else None,
            "from_sub_warehouse": self.from_sub_warehouse.name
            if self.from_sub_warehouse
            else None,
            "to_sub_warehouse": self.to_sub_warehouse.name
            if self.to_sub_warehouse
            else None,
            "from_department": self.from_department.name
            if self.from_department
            else None,
            "to_department": self.to_department.name if self.to_department else None,
            "from_user": self.from_user.get_full_name() if self.from_user else None,
            "to_user": self.to_user.get_full_name() if self.to_user else None,
            "inventory_user": self.inventory_user.get_full_name()
            if self.inventory_user
            else None,
            "approval_user": self.approval_user.get_full_name()
            if self.approval_user
            else None,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "created_by": self.created_by.get_full_name() if self.created_by else None,
            "details": [
                {
                    "id": detail.id,
                    "item": detail.item.name if detail.item else None,
                    "item_id": detail.item.id if detail.item else None,
                    "order_quantity": detail.order_quantity,
                    "approved_quantity": detail.approved_quantity,
                    "status": detail.get_status_display(),
                    "notes": detail.notes,
                }
                for detail in self.itemtransactiondetails_set.all()
            ],
        }

    def get_changed_fields(self, old_data):
        """Get changed fields between current transaction and old data."""
        changed_fields = {}
        current_data = self.to_dict()
        for field, old_value in old_data.items():
            current_value = current_data.get(field)
            if old_value != current_value:
                changed_fields[field] = {"old": old_value, "new": current_value}
        return changed_fields

    def _recalculate_affected_items(self):
        """Auto-trigger recalculation after approval, deletion, or reversal."""
        from django.utils import timezone

        item_ids = list(
            self.itemtransactiondetails_set.values_list("item_id", flat=True)
        )
        if not item_ids:
            return

        for item_id in item_ids:
            item = Item.objects.get(id=item_id)

            # Use the updated calculate_authoritative_net_quantity function
            net = calculate_authoritative_net_quantity(item, self.faculty)

            # Update ALL FacultyItemStock records for this faculty/item
            FacultyItemStock.objects.filter(faculty=self.faculty, item=item).update(
                cached_quantity=net,
                limit_quantity=item.limit_quantity,
                last_quantity_update=timezone.now(),
            )


class ItemTransactionDetails(models.Model):
    """Line items for a transaction."""

    class ITEMS_STATUS(models.TextChoices):
        New = "N", "جديد"
        Used = "U", "مستعمل"
        Repairable = "R", "قابل للاصلاح"
        Damaged = "D", "كهنة وخردة"

    status = models.CharField(
        max_length=1,
        choices=ITEMS_STATUS.choices,
        default=ITEMS_STATUS.New,
        verbose_name="حالة الصنف",
    )
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="السعر",
        default=0,
    )
    transaction = models.ForeignKey(
        ItemTransactions, on_delete=models.CASCADE, verbose_name="المعاملة"
    )
    item = models.ForeignKey(Item, on_delete=models.CASCADE, verbose_name="الصنف")
    order_quantity = models.PositiveIntegerField(
        verbose_name="الكمية المطلوبة", default=0, blank=True, null=True
    )
    approved_quantity = models.PositiveIntegerField(
        verbose_name="الكمية المنصرفة", default=0
    )
    notes = models.TextField(null=True, blank=True, verbose_name="ملاحظات")

    class Meta:
        verbose_name = "تفاصيل معاملة الصنف"
        verbose_name_plural = "تفاصيل معاملات الأصناف"
        ordering = ["id"]
        indexes = [models.Index(fields=["item", "transaction"])]

    def __str__(self):
        return f"{self.item.name} - {self.order_quantity} - {self.approved_quantity}"

    def get_total_items_for_user(self, user):
        """Get total items owned by a user across all transactions (never negative)."""
        user_faculty_id = getattr(getattr(user, "profile", None), "faculty_id", None)
        faculty_filter = (
            {"transaction__faculty_id": user_faculty_id} if user_faculty_id else {}
        )

        disbursements = ItemTransactionDetails.objects.filter(
            transaction__to_user=user,
            transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Disbursement,
            transaction__approval_status=ItemTransactions.APPROVAL_STATUS.APPROVED,
            transaction__deleted=False,
            **faculty_filter,
        ).aggregate(total=Coalesce(Sum("approved_quantity"), Value(0)))["total"]

        returns = ItemTransactionDetails.objects.filter(
            transaction__from_user=user,
            transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Return,
            transaction__approval_status=ItemTransactions.APPROVAL_STATUS.APPROVED,
            transaction__deleted=False,
            **faculty_filter,
        ).aggregate(total=Coalesce(Sum("approved_quantity"), Value(0)))["total"]

        return max(0, disbursements - returns)


class TransactionAuditLog(models.Model):
    """Audit trail for transaction changes."""

    class ACTION_TYPES(models.TextChoices):
        CREATE = "C", "إنشاء"
        UPDATE = "U", "تعديل"
        DELETE = "D", "حذف"
        RESTORE = "S", "استعادة"
        APPROVE = "A", "اعتماد"
        REJECT = "R", "رفض"
        VIEW = "V", "عرض"

    transaction = models.ForeignKey(
        ItemTransactions,
        on_delete=models.CASCADE,
        related_name="audit_logs",
        verbose_name="السند",
    )
    action = models.CharField(
        max_length=1, choices=ACTION_TYPES.choices, verbose_name="نوع الإجراء"
    )
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transaction_audits",
        verbose_name="نفّذ بواسطة",
    )
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإجراء")
    transaction_snapshot = models.JSONField(
        null=True, blank=True, verbose_name="لقطة السند"
    )
    changed_fields = models.JSONField(
        null=True, blank=True, verbose_name="الحقول المعدلة"
    )
    ip_address = models.GenericIPAddressField(
        null=True, blank=True, verbose_name="عنوان IP"
    )
    user_agent = models.TextField(null=True, blank=True, verbose_name="وكيل المستخدم")

    class Meta:
        verbose_name = "سجل تدقيق المعاملة"
        verbose_name_plural = "سجلات تدقيق المعاملات"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.get_action_display()} - {self.transaction.document_number} - {self.timestamp}"
