# inventory/admin.py
from django import forms
from django.contrib import admin, messages
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Max, Q, Sum
from django.forms.models import BaseInlineFormSet
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import path
from django.utils import timezone

from administration.models import Department, Faculty, UserProfile

from .models import (
    FacultyItemStock,
    Item,
    ItemCategory,
    ItemPriceHistory,
    ItemTransactionDetails,
    ItemTransactions,
    SubWarehouse,
    Supplier,
    Warehouse,
)


# CUSTOM FORM FOR TRANSACTION
class ItemTransactionAdminForm(forms.ModelForm):
    """Custom form for ItemTransactions in admin with dynamic field handling."""

    class Meta:
        model = ItemTransactions
        fields = "__all__"
        widgets = {
            "document_type": forms.Select(attrs={"class": "form-control"}),
            "transaction_type": forms.Select(attrs={"class": "form-control"}),
            "castody_type": forms.Select(attrs={"class": "form-control"}),
            "from_sub_warehouse": forms.Select(
                attrs={
                    "class": "form-control",
                    "data-dependent-field": "inventory_user",
                }
            ),
            "to_sub_warehouse": forms.Select(attrs={"class": "form-control"}),
            "from_department": forms.Select(
                attrs={
                    "class": "form-control",
                    "data-dependent-field": "from_user",
                }
            ),
            "to_department": forms.Select(
                attrs={
                    "class": "form-control",
                    "data-dependent-field": "to_user",
                }
            ),
            "from_user": forms.Select(attrs={"class": "form-control"}),
            "to_user": forms.Select(attrs={"class": "form-control"}),
            "inventory_user": forms.Select(attrs={"class": "form-control"}),
            "approval_user": forms.Select(attrs={"class": "form-control"}),
            "supplier": forms.Select(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "approval_notes": forms.Textarea(
                attrs={"class": "form-control", "rows": 3}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Filter warehouses and departments by faculty for non-superusers
        user = kwargs.get("initial", {}).get("created_by") or getattr(
            kwargs.get("instance", None), "created_by", None
        )

        if user and hasattr(user, "profile") and user.profile.faculty:
            faculty = user.profile.faculty
            if "from_sub_warehouse" in self.fields:
                self.fields[
                    "from_sub_warehouse"
                ].queryset = SubWarehouse.objects.filter(
                    item_stocks__faculty=faculty
                ).distinct()
            if "to_sub_warehouse" in self.fields:
                self.fields["to_sub_warehouse"].queryset = SubWarehouse.objects.filter(
                    item_stocks__faculty=faculty
                ).distinct()
            if "from_department" in self.fields:
                self.fields["from_department"].queryset = self.fields[
                    "from_department"
                ].queryset.filter(faculty=faculty)
            if "to_department" in self.fields:
                self.fields["to_department"].queryset = self.fields[
                    "to_department"
                ].queryset.filter(faculty=faculty)

        # Check if field exists before modifying
        if self.instance and self.instance.pk:
            if "document_number" in self.fields:
                self.fields["document_number"].widget.attrs["readonly"] = True
                self.fields[
                    "document_number"
                ].help_text = "يتم الإنشاء تلقائياً عند الحفظ"

        # Set initial approval_status to PENDING for new transactions
        if not self.instance.pk:
            if "approval_status" in self.fields:
                self.fields[
                    "approval_status"
                ].initial = ItemTransactions.APPROVAL_STATUS.PENDING


# INLINE FORM FOR TRANSACTION DETAILS
class ItemTransactionDetailsForm(forms.ModelForm):
    """Form for individual transaction detail with stock validation."""

    class Meta:
        model = ItemTransactionDetails
        fields = [
            "item",
            "order_quantity",
            "approved_quantity",
            "price",
            "status",
            "notes",
        ]
        widgets = {
            "item": forms.Select(attrs={"class": "form-control item-autocomplete"}),
            "order_quantity": forms.NumberInput(
                attrs={"class": "form-control order-quantity"}
            ),
            "approved_quantity": forms.NumberInput(
                attrs={"class": "form-control approved-quantity"}
            ),
            "price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "status": forms.Select(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Filter items by warehouse if transaction has from_sub_warehouse
        parent_instance = getattr(self, "parent_instance", None)
        if parent_instance and parent_instance.from_sub_warehouse:
            if "item" in self.fields:
                self.fields["item"].queryset = Item.objects.filter(
                    sub_warehouse=parent_instance.from_sub_warehouse
                ).select_related("category", "sub_warehouse")
        else:
            if "item" in self.fields:
                self.fields["item"].queryset = Item.objects.all().select_related(
                    "category"
                )

    def clean_approved_quantity(self):
        approved = self.cleaned_data.get("approved_quantity", 0)
        order = self.cleaned_data.get("order_quantity", 0)

        if approved > order:
            raise ValidationError("الكمية المنصرفة لا يمكن أن تتجاوز الكمية المطلوبة")

        # Stock validation — use FacultyItemStock (item is now global)
        item = self.cleaned_data.get("item")
        if item and approved > 0:
            # The admin inline doesn't know the sub_warehouse at form level,
            # so we take the total across all sub_warehouses as a conservative check.
            from inventory.models import FacultyItemStock

            total_available = sum(
                s.cached_quantity for s in FacultyItemStock.objects.filter(item=item)
            )
            if total_available < approved:
                raise ValidationError(
                    f"الكمية المنصرفة ({approved}) تتجاوز إجمالي الكمية المتاحة ({total_available})"
                )

        return approved


class ItemTransactionDetailsInlineFormSet(BaseInlineFormSet):
    """Custom formset for transaction details with stock validation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pass parent instance to each form for filtering
        for form in self.forms:
            form.parent_instance = self.instance

    def clean(self):
        """Validate total quantities don't exceed stock."""
        super().clean()

        if any(self.errors):
            return

        # Group items and sum quantities
        item_quantities = {}
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue

            item = form.cleaned_data.get("item")
            approved_qty = form.cleaned_data.get("approved_quantity", 0)

            if item and approved_qty > 0:
                if item.id not in item_quantities:
                    item_quantities[item.id] = {
                        "item": item,
                        "total_qty": 0,
                    }
                item_quantities[item.id]["total_qty"] += approved_qty

        # Validate against FacultyItemStock (item is global; pick the relevant sub_warehouse)
        from inventory.models import FacultyItemStock

        from_sub_warehouse = getattr(self.instance, "from_sub_warehouse", None)

        for item_id, data in item_quantities.items():
            item = data["item"]
            total_qty = data["total_qty"]

            if from_sub_warehouse:
                stock = FacultyItemStock.objects.filter(
                    item=item, sub_warehouse=from_sub_warehouse
                ).first()
                available = stock.cached_quantity if stock else 0
            else:
                available = sum(
                    s.cached_quantity
                    for s in FacultyItemStock.objects.filter(item=item)
                )

            if total_qty > available:
                raise ValidationError(
                    f"الصنف '{item.name}': الكمية الإجمالية ({total_qty}) تتجاوز الكمية المتاحة ({available})"
                )


class ItemTransactionDetailsInline(admin.TabularInline):
    """Editable inline for transaction details with full CRUD including DELETE."""

    model = ItemTransactionDetails
    form = ItemTransactionDetailsForm
    formset = ItemTransactionDetailsInlineFormSet
    extra = 1
    min_num = 1
    can_delete = True
    show_change_link = True

    readonly_fields = ()

    fields = (
        "item",
        "order_quantity",
        "approved_quantity",
        "price",
        "status",
        "notes",
    )

    # Enable autocomplete for item field
    autocomplete_fields = ["item"]

    def has_add_permission(self, request, obj=None):
        return (
            request.user.is_superuser
            or request.session.get("user_type") == "inventory_manager"
        )

    def has_delete_permission(self, request, obj=None):
        return (
            request.user.is_superuser
            or request.session.get("user_type") == "inventory_manager"
        )

    def has_change_permission(self, request, obj=None):
        return True


# TRANSACTION ADMIN WITH USER CUSTODY REPORT
@admin.register(ItemTransactions)
class ItemTransactionsAdmin(admin.ModelAdmin):
    """Admin for ItemTransactions with editable details inline and user custody report."""

    # Include inline for details
    inlines = [ItemTransactionDetailsInline]

    form = ItemTransactionAdminForm

    list_display = [
        "document_number",
        "transaction_type",
        "from_sub_warehouse",
        "to_sub_warehouse",
        "faculty_display",
        "year",
        "approval_status",
        "created_by",
        "created_at",
        "is_deleted",
    ]

    list_filter = [
        "transaction_type",
        "castody_type",
        "approval_status",
        "deleted",
        "created_at",
        "year",
    ]

    search_fields = [
        "document_number",
        "notes",
        "created_by__username",
        "created_by__first_name",
    ]

    # Conditional readonly fields with existence check
    def get_readonly_fields(self, request, obj=None):
        model_fields = [f.name for f in self.model._meta.get_fields()]

        if obj:
            return [
                field
                for field in [
                    "document_number",
                    "created_at",
                    "modified_at",
                    "deleted_at",
                    "deleted_by",
                    "approval_user",
                    "approval_date",
                    "approval_notes",
                ]
                if field in model_fields
            ]
        else:
            return [
                field
                for field in [
                    "created_at",
                    "modified_at",
                    "deleted_at",
                    "deleted_by",
                    "approval_user",
                    "approval_date",
                    "approval_notes",
                ]
                if field in model_fields
            ]

    fieldsets = (
        (
            "معلومات السند",
            {
                "fields": (
                    "document_number",
                    "transaction_type",
                    "castody_type",
                    "document_type",
                    "approval_status",
                    "year",
                ),
                "description": "المعلومات الأساسية للسند",
            },
        ),
        (
            "المخازن",
            {
                "fields": (
                    "from_warehouse",
                    "to_warehouse",
                    "from_sub_warehouse",
                    "to_sub_warehouse",
                ),
                "description": "تحديد المخازن الرئيسية والفرعية",
                "classes": ("collapse",),
            },
        ),
        (
            "الأطراف المعنية",
            {
                "fields": (
                    "from_department",
                    "to_department",
                    "from_user",
                    "to_user",
                    "inventory_user",
                    "supplier",
                ),
                "description": "الأقسام والموظفين المعنيين",
                "classes": ("collapse",),
            },
        ),
        (
            "الاعتماد",
            {
                "fields": (
                    "approval_user",
                    "approval_date",
                    "approval_notes",
                ),
                "description": "معلومات الاعتماد",
                "classes": ("collapse",),
            },
        ),
        (
            "معلومات إضافية",
            {
                "fields": (
                    "notes",
                    "created_by",
                    "created_at",
                    "modified_by",
                    "modified_at",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "حالة الحذف",
            {
                "fields": (
                    "deleted",
                    "deleted_by",
                    "deleted_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    change_list_template = (
        "admin/inventory/itemtransactions/change_list_with_report.html"
    )

    def has_delete_permission(self, request, obj=None):
        return (
            request.user.is_superuser
            or request.session.get("user_type") == "inventory_manager"
        )

    def has_add_permission(self, request):
        return (
            request.user.is_superuser
            or request.session.get("user_type") == "inventory_manager"
        )

    def has_view_permission(self, request, obj=None):
        return True

    def delete_model(self, request, obj):
        """Override to use model's delete method which recalculates quantities."""
        if request.user.is_superuser:
            # This will call ItemTransactions.delete() which recalculates
            obj.delete()  # Not super().delete_model()
            messages.success(
                request, f"تم حذف السند {obj.document_number} وتم تحديث الكميات."
            )
        else:
            super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        """Override bulk delete to recalculate quantities."""
        if request.user.is_superuser:
            # Get all affected items BEFORE deleting
            affected_item_ids = set()
            for trans in queryset:
                affected_item_ids.update(
                    trans.itemtransactiondetails_set.values_list("item_id", flat=True)
                )

            # Perform soft delete
            queryset.update(
                deleted=True, deleted_by=request.user, deleted_at=timezone.now()
            )

            # Recalculate quantities for affected items
            if affected_item_ids:
                Item.batch_update_cached_quantities(
                    Item.objects.filter(id__in=affected_item_ids)
                )

            messages.success(
                request, f"تم حذف {queryset.count()} سند وتم تحديث الكميات."
            )
        else:
            super().delete_queryset(request, queryset)

    def is_deleted(self, obj):
        if obj.deleted:
            return "✅ محذوف"
        return "✅ نشط"

    is_deleted.short_description = "الحالة"

    is_deleted.admin_order_field = "deleted"

    def faculty_display(self, obj):
        if obj.from_sub_warehouse:
            return obj.faculty.name
        elif obj.to_sub_warehouse:
            return obj.faculty.name
        return "-"

    faculty_display.short_description = "الكلية"

    def get_queryset(self, request):
        qs = (
            super()
            .get_queryset(request)
            .select_related(
                "faculty",
                "faculty",
                "inventory_user",
                "approval_user",
                "created_by",
            )
        )
        if not request.user.is_superuser:
            qs = qs.filter(
                Q(faculty=request.user.profile.faculty)
                | Q(faculty=request.user.profile.faculty),
                deleted=False,
            )
        return qs

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.modified_by = request.user
        obj.modified_at = timezone.now()
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        deleted_count = 0

        for obj in formset.deleted_objects:
            deleted_count += 1

        for instance in instances:
            instance.save()

        formset.save_m2m()

        if deleted_count > 0:
            messages.info(
                request,
                f"تم حذف {deleted_count} صنف من تفاصيل السند",
            )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "user-custody-report/",
                self.admin_site.admin_view(self.user_custody_report_view),
                name="user_custody_report",
            ),
            path(
                "inventory-users/",
                self.admin_site.admin_view(self.get_inventory_users),
                name="inventory_admin_inventory_users",
            ),
            path(
                "department-users/",
                self.admin_site.admin_view(self.get_department_users),
                name="inventory_admin_department_users",
            ),
            path(
                "item-stock/",
                self.admin_site.admin_view(self.get_item_stock),
                name="inventory_admin_item_stock",
            ),
        ]
        return custom_urls + urls

    # USER CUSTODY REPORT VIEW (HTML - NOT PDF)
    def user_custody_report_view(self, request):
        """
        Show all users and their custody items grouped by department.
        Ordered by user name within each department.
        Only accessible to superusers and staff.
        Displays as HTML page in admin interface.
        """
        # Only superusers and staff can access
        if not request.user.is_superuser and not request.user.is_staff:
            messages.error(request, "ليس لديك صلاحية الوصول إلى هذا التقرير.")
            return redirect("admin:index")

        # Get department filter from URL
        department_id = request.GET.get("department")
        search_query = request.GET.get("search", "").strip()

        # Get all users with custody items (approved disbursements and transfers only)
        users_with_items = (
            User.objects.filter(
                Q(
                    to_transactions__transaction_type=ItemTransactions.TRANSACTION_TYPES.Disbursement
                )
                | Q(
                    to_transactions__transaction_type=ItemTransactions.TRANSACTION_TYPES.Transfer
                ),
                to_transactions__approval_status=ItemTransactions.APPROVAL_STATUS.APPROVED,
                to_transactions__deleted=False,
            )
            .select_related("profile__department", "profile__faculty")
            .distinct()
            .order_by("profile__department__name", "last_name", "first_name")
        )

        # Filter by department if specified
        if department_id:
            users_with_items = users_with_items.filter(
                profile__department_id=department_id
            )

        # Filter by search query (user name or username)
        if search_query:
            users_with_items = users_with_items.filter(
                Q(username__icontains=search_query)
                | Q(first_name__icontains=search_query)
                | Q(last_name__icontains=search_query)
            )

        # Build department structure with users and their items
        departments = {}

        for user in users_with_items:
            dept_name = (
                user.profile.department.name if user.profile.department else "بدون قسم"
            )
            dept_id = user.profile.department.id if user.profile.department else 0

            if dept_id not in departments:
                departments[dept_id] = {
                    "id": dept_id,
                    "name": dept_name,
                    "users": [],
                    "total_items": 0,
                }

            # Get all items for this user (approved disbursements and transfers)
            user_items = (
                ItemTransactionDetails.objects.filter(
                    Q(
                        transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Disbursement
                    )
                    | Q(
                        transaction__transaction_type=ItemTransactions.TRANSACTION_TYPES.Transfer
                    ),
                    transaction__to_user=user,
                    transaction__approval_status=ItemTransactions.APPROVAL_STATUS.APPROVED,
                    transaction__deleted=False,
                )
                .select_related("item", "transaction")
                .values(
                    "item__id",
                    "item__name",
                    "item__code",
                    "item__unit",
                )
                .annotate(
                    total_quantity=Sum("approved_quantity"),
                    last_transaction=Max("transaction__created_at"),
                )
                .order_by("item__name")
            )

            # Calculate total items for this user
            user_total_items = sum(item["total_quantity"] for item in user_items)

            if user_items.exists():
                departments[dept_id]["users"].append(
                    {
                        "user": user,
                        "items": list(user_items),
                        "total_items": user_total_items,
                    }
                )
                departments[dept_id]["total_items"] += user_total_items

        # Get all departments for filter dropdown
        all_departments = Department.objects.all().order_by("name")

        # Calculate grand totals
        total_users = sum(len(dept["users"]) for dept in departments.values())
        grand_total_items = sum(dept["total_items"] for dept in departments.values())

        context = {
            **self.admin_site.each_context(request),
            "title": "تقرير عهدة الموظفين",
            "departments": sorted(departments.values(), key=lambda x: x["name"]),
            "all_departments": all_departments,
            "selected_department": department_id,
            "search_query": search_query,
            "total_users": total_users,
            "grand_total_items": grand_total_items,
            "total_departments": len(departments),
            "current_date": timezone.now(),
            "opts": self.model._meta,
        }

        return render(request, "admin/inventory/user_custody_report.html", context)

    # AJAX ENDPOINTS FOR DYNAMIC FIELDS
    def get_inventory_users(self, request):
        warehouse_id = request.GET.get("warehouse_id")
        if not warehouse_id:
            return JsonResponse({"error": "مطلوب تحديد المخزن"}, status=400)

        try:
            warehouse = SubWarehouse.objects.get(id=warehouse_id)
            faculty = None
            if hasattr(request.user, "profile"):
                faculty = request.user.profile.faculty
            users = (
                UserProfile.objects.filter(
                    user__is_active=True,
                    faculty=faculty,
                )
                .select_related("user")
                .values(
                    "user__id",
                    "user__username",
                    "user__first_name",
                    "user__last_name",
                )
            )

            user_choices = [
                {
                    "id": u["user__id"],
                    "label": f"{u['user__first_name']} {u['user__last_name']} ({u['user__username']})",
                }
                for u in users
            ]

            return JsonResponse({"users": user_choices})
        except SubWarehouse.DoesNotExist:
            return JsonResponse({"error": "المخزن غير موجود"}, status=404)

    def get_department_users(self, request):
        department_id = request.GET.get("department_id")
        if not department_id:
            return JsonResponse({"error": "مطلوب تحديد القسم"}, status=400)

        try:
            department = Department.objects.get(id=department_id)
            users = (
                department.userprofile_set.filter(user__is_active=True)
                .select_related("user")
                .values(
                    "user__id",
                    "user__username",
                    "user__first_name",
                    "user__last_name",
                )
            )

            user_choices = [
                {
                    "id": u["user__id"],
                    "label": f"{u['user__first_name']} {u['user__last_name']} ({u['user__username']})",
                }
                for u in users
            ]

            return JsonResponse({"users": user_choices})
        except Department.DoesNotExist:
            return JsonResponse({"error": "القسم غير موجود"}, status=404)

    def get_item_stock(self, request):
        item_id = request.GET.get("item_id")
        warehouse_id = request.GET.get("warehouse_id")

        if not item_id:
            return JsonResponse({"error": "مطلوب تحديد الصنف"}, status=400)

        try:
            item = Item.objects.select_related("category").get(id=item_id)
            from inventory.models import FacultyItemStock

            if warehouse_id:
                stock = FacultyItemStock.objects.filter(
                    item=item, sub_warehouse_id=int(warehouse_id)
                ).first()
                if not stock:
                    return JsonResponse(
                        {"error": "الصنف غير متوفر في هذا المخزن", "stock": 0},
                        status=400,
                    )
                qty = stock.cached_quantity
            else:
                qty = sum(
                    s.cached_quantity
                    for s in FacultyItemStock.objects.filter(item=item)
                )

            return JsonResponse(
                {
                    "item_id": item.id,
                    "item_name": item.name,
                    "stock": qty,
                    "unit": item.get_unit_display(),
                    "price": float(
                        item.itempricehistory_set.order_by("-date").first().price
                    )
                    if item.itempricehistory_set.exists()
                    else None,
                }
            )
        except Item.DoesNotExist:
            return JsonResponse({"error": "الصنف غير موجود"}, status=404)


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]


@admin.register(SubWarehouse)
class SubWarehouseAdmin(admin.ModelAdmin):
    list_display = ["name", "warehouse", "code"]
    list_filter = ["warehouse"]
    search_fields = ["name", "code"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if not request.user.is_superuser:
            return qs.filter(faculty=request.user.profile.faculty)
        return qs

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "faculty" and not request.user.is_superuser:
            kwargs["queryset"] = Faculty.objects.filter(
                id=request.user.profile.faculty.id
            )
        elif db_field.name == "warehouse" and not request.user.is_superuser:
            faculty_warehouses = SubWarehouse.objects.filter(
                item_stocks__faculty=request.user.profile.faculty
            ).values_list("warehouse_id", flat=True)
            kwargs["queryset"] = Warehouse.objects.filter(id__in=faculty_warehouses)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(ItemCategory)
class ItemCategoryAdmin(admin.ModelAdmin):
    """Global category — no sub_warehouse filter (categories shared across faculties)."""

    list_display = ["name", "item_count"]
    search_fields = ["name"]

    def item_count(self, obj):
        return obj.item_set.count()

    item_count.short_description = "عدد الأصناف"


class ItemPriceHistoryInline(admin.TabularInline):
    model = ItemPriceHistory
    extra = 0
    readonly_fields = ("date",)


class FacultyItemStockInline(admin.TabularInline):
    model = FacultyItemStock
    extra = 0
    readonly_fields = ("cached_quantity", "last_quantity_update")
    fields = (
        "sub_warehouse",
        "cached_quantity",
        "limit_quantity",
        "last_quantity_update",
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    """Global item catalog — quantities are in FacultyItemStock, not here."""

    inlines = [ItemPriceHistoryInline, FacultyItemStockInline]
    list_display = [
        "name",
        "code",
        "category",
        "unit",
        "limit_quantity",
        "total_stock",
    ]
    list_filter = ["category", "unit"]
    search_fields = ["name", "code"]

    def total_stock(self, obj):
        total = sum(s.cached_quantity for s in obj.faculty_stocks.all())
        return total

    total_stock.short_description = "إجمالي المخزون"


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["name", "company_phone", "contact_name"]
    search_fields = ["name", "contact_name"]


@admin.register(ItemPriceHistory)
class ItemPriceHistoryAdmin(admin.ModelAdmin):
    list_display = ["item", "price", "date"]
    list_filter = ["date", "item__category"]
    search_fields = ["item__name", "item__code"]
    readonly_fields = ["date"]


@admin.register(FacultyItemStock)
class FacultyItemStockAdmin(admin.ModelAdmin):
    list_display = (
        "item",
        "sub_warehouse",
        "faculty_name",
        "cached_quantity",
        "limit_quantity",
        "stock_status",
        "last_quantity_update",
    )
    list_filter = ("sub_warehouse__warehouse", "sub_warehouse")
    search_fields = ("item__name", "item__code", "sub_warehouse__name")
    readonly_fields = ("cached_quantity", "last_quantity_update")
    ordering = ("faculty__name", "sub_warehouse__name", "item__name")

    def faculty_name(self, obj):
        return obj.faculty.name

    faculty_name.short_description = "الكلية"
    faculty_name.admin_order_field = "faculty__name"

    def stock_status(self, obj):
        return obj.get_stock_status()

    stock_status.short_description = "الحالة"

    actions = ["recalculate_selected"]

    def recalculate_selected(self, request, queryset):
        from inventory.models import FacultyItemStock as FIS

        item_ids = list(queryset.values_list("item_id", flat=True).distinct())
        sw_ids = list(queryset.values_list("sub_warehouse_id", flat=True).distinct())
        from inventory.models import Item as ItemModel
        from inventory.models import SubWarehouse as SWModel

        updated = FIS.batch_recalculate(
            items=ItemModel.objects.filter(id__in=item_ids),
            sub_warehouses=SWModel.objects.filter(id__in=sw_ids),
        )
        self.message_user(
            request, f"تم إعادة حساب {updated} سجل مخزون.", messages.SUCCESS
        )

    recalculate_selected.short_description = "إعادة حساب الكميات للسجلات المحددة"
