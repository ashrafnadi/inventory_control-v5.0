# inventory/helper.py
import logging

from django.contrib.auth import get_user_model
from django.db.models import Q

from administration.models import Department
from inventory.models import FacultyItemStock, Item, ItemTransactions

User = get_user_model()
logger = logging.getLogger(__name__)


def _get_warehouse_users(sub_warehouse_id, faculty=None):
    """Return inventory users for a faculty; sub-warehouse stays shared."""
    if not sub_warehouse_id or not str(sub_warehouse_id).isdigit():
        return User.objects.none()

    target_faculty = faculty
    if target_faculty is None:
        return User.objects.none()

    qs = User.objects.filter(profile__is_inventory_employee=True)
    if target_faculty is not None:
        qs = qs.filter(profile__faculty=target_faculty)

    return (
        qs.filter(
            Q(profile__department__name__icontains="مخزن")
            | Q(profile__department__name__icontains="مخازن")
        )
        .select_related("profile", "profile__faculty", "profile__department")
        .distinct()
    )


def _get_department_users(department_id):
    """Return users belonging to a department with faculty isolation."""
    if not department_id or not str(department_id).isdigit():
        return User.objects.none()
    try:
        department = Department.objects.select_related("faculty").get(id=department_id)
        return User.objects.filter(
            profile__department=department, profile__faculty=department.faculty
        ).select_related("profile", "profile__faculty", "profile__department")
    except Department.DoesNotExist:
        return User.objects.none()


def _base_item_search(query, sub_warehouse_id=None, user=None, transaction_type=None):
    """
    Search global Item catalog, optionally filtered to items that have
    faculty stock in the given sub_warehouse.
    """
    if sub_warehouse_id and str(sub_warehouse_id).isdigit():
        items = (
            Item.objects.filter(faculty_stocks__sub_warehouse_id=sub_warehouse_id)
            .select_related("category")
            .distinct()
        )
    else:
        items = Item.objects.select_related("category")

    if user and transaction_type:
        items = items.filter(
            itemtransactiondetails__transaction__transaction_type=transaction_type,
            itemtransactiondetails__transaction__to_user=user,
            itemtransactiondetails__approved_quantity__gt=0,
        ).distinct()

    if query:
        if query.isdigit():
            items = items.filter(id=int(query))
        else:
            items = items.filter(
                Q(name__icontains=query) | Q(category__name__icontains=query)
            )

    return items


def _validate_transfer_stock(form, formset, user_profile):
    """Validate stock availability for transfer transactions."""
    errors = []
    castody_type = form.cleaned_data.get("castody_type")

    try:
        if castody_type == ItemTransactions.CASTODY_TYPES.Warehouse:
            from_sub_warehouse = form.cleaned_data.get("from_sub_warehouse")
            if not from_sub_warehouse:
                errors.append("يجب تحديد المخزن الفرعي المرسل.")
                return errors

            for form_detail in formset:
                if not form_detail.cleaned_data or form_detail.cleaned_data.get(
                    "DELETE"
                ):
                    continue
                item = form_detail.cleaned_data.get("item")
                approved_qty = form_detail.cleaned_data.get("approved_quantity", 0)
                if approved_qty <= 0 or not item:
                    continue

                stock = FacultyItemStock.objects.filter(
                    item=item,
                    sub_warehouse=from_sub_warehouse,
                    faculty=user_profile.faculty,
                ).first()
                current_stock = stock.cached_quantity if stock else 0

                if current_stock <= 0:
                    errors.append(
                        f"الصنف '{item.name}' نافد في المخزن الفرعي '{from_sub_warehouse.name}'."
                    )
                elif approved_qty > current_stock:
                    errors.append(
                        f"الكمية ({approved_qty}) من '{item.name}' تتجاوز المتوفر ({current_stock})."
                    )

        elif castody_type in [
            ItemTransactions.CASTODY_TYPES.Personal,
            ItemTransactions.CASTODY_TYPES.Branch,
        ]:
            from_user = form.cleaned_data.get("from_user")
            if not from_user:
                errors.append("يجب تحديد الموظف المرسل.")
                return errors

            for form_detail in formset:
                if not form_detail.cleaned_data or form_detail.cleaned_data.get(
                    "DELETE"
                ):
                    continue
                item = form_detail.cleaned_data.get("item")
                approved_qty = form_detail.cleaned_data.get("approved_quantity", 0)
                if approved_qty <= 0 or not item:
                    continue

                user_qty = item.current_quantity_for_user(from_user)
                if user_qty <= 0:
                    errors.append(
                        f"الموظف '{from_user.get_full_name()}' لا يمتلك الصنف '{item.name}'."
                    )
                elif approved_qty > user_qty:
                    errors.append(
                        f"الكمية ({approved_qty}) تتجاوز ما يمتلكه الموظف ({user_qty}) من '{item.name}'."
                    )

    except Exception as e:
        logger.error(f"Stock validation error: {str(e)}", exc_info=True)
        errors.append("حدث خطأ أثناء التحقق من الكميات. يرجى المحاولة مرة أخرى.")

    return errors
