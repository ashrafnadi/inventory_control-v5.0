# inventory/utils.py
import logging
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import F, Q
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from weasyprint import HTML

from administration.models import Department

from .models import (
    FacultyItemStock,
    Item,
    ItemPriceHistory,
    ItemTransactions,
    SubWarehouse,
    TransactionAuditLog,
)

logger = logging.getLogger(__name__)

User = get_user_model()


def get_inventory_users_for_user(user):
    """Get inventory users from same faculty with warehouse departments."""
    if not user or not hasattr(user, "profile") or not user.profile.faculty:
        return User.objects.none()

    faculty = user.profile.faculty
    return (
        User.objects.filter(
            profile__faculty=faculty,
            profile__is_inventory_employee=True,
        )
        .filter(
            Q(profile__department__name__icontains="مخزن")
            | Q(profile__department__name__icontains="مخازن")
        )
        .select_related("profile", "profile__department")
        .distinct()
    )


def get_departments_for_user(user):
    if not user or not hasattr(user, "profile") or not user.profile.faculty:
        return Department.objects.none()
    return Department.objects.filter(faculty=user.profile.faculty).order_by("name")


def get_sub_warehouses_for_user(user):
    if not user or not hasattr(user, "profile"):
        return SubWarehouse.objects.none()

    return SubWarehouse.objects.select_related("warehouse").order_by("name")


def get_inventory_users_for_sub_warehouse(sub_warehouse_id, faculty=None):
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
        .select_related("profile", "profile__department")
        .distinct()
    )


def get_users_for_department(department_id):
    if not department_id or not str(department_id).isdigit():
        return User.objects.none()

    try:
        department = Department.objects.select_related("faculty").get(id=department_id)
        return (
            User.objects.filter(
                profile__department=department,
                profile__faculty=department.faculty,
            )
            .select_related("profile")
            .distinct()
        )
    except Department.DoesNotExist:
        return User.objects.none()


def log_transaction_action(
    transaction, action, user, request, old_data=None, details=None
):
    try:
        audit_log = TransactionAuditLog(
            transaction=transaction,
            action=action,
            performed_by=user,
            timestamp=timezone.now(),
            ip_address=request.META.get("REMOTE_ADDR", ""),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:255]
            if request.META.get("HTTP_USER_AGENT")
            else "",
        )

        snapshot = transaction.to_dict()
        if details:
            snapshot["audit_details"] = details

        audit_log.transaction_snapshot = snapshot

        if old_data:
            changed_fields = transaction.get_changed_fields(old_data)
            if changed_fields:
                audit_log.changed_fields = changed_fields

        audit_log.save()
        return audit_log

    except Exception as e:
        logger.error(f"Failed to log transaction action: {str(e)}", exc_info=True)
        return None


def get_low_stock_items(request):
    if not (hasattr(request.user, "profile") and request.user.profile.faculty):
        return FacultyItemStock.objects.none()

    faculty = request.user.profile.faculty
    return (
        FacultyItemStock.objects.filter(faculty=faculty)
        .filter(Q(cached_quantity=0) | Q(cached_quantity__lte=F("limit_quantity")))
        .select_related("item", "item__category", "sub_warehouse", "faculty")
        .order_by("sub_warehouse__name", "item__category__name", "item__name")
    )


def get_transfer_items_for_source(
    source_id, source_type, item_query=None, faculty=None
):
    items = Item.objects.none()

    if source_type == "sub_warehouse" and source_id and str(source_id).isdigit():
        stocks = FacultyItemStock.objects.filter(
            sub_warehouse_id=source_id, cached_quantity__gt=0
        )
        if faculty is not None:
            stocks = stocks.filter(faculty=faculty)
        items = Item.objects.filter(faculty_stocks__in=stocks).distinct()
        if item_query:
            items = items.filter(name__icontains=item_query)

    elif source_type == "user" and source_id and str(source_id).isdigit():
        items = Item.objects.filter(
            itemtransactiondetails__transaction__to_user_id=source_id,
            itemtransactiondetails__approved_quantity__gt=0,
            itemtransactiondetails__transaction__approval_status=ItemTransactions.APPROVAL_STATUS.APPROVED,
            itemtransactiondetails__transaction__deleted=False,
            itemtransactiondetails__transaction__transaction_type__in=[
                ItemTransactions.TRANSACTION_TYPES.Disbursement,
                ItemTransactions.TRANSACTION_TYPES.Transfer,
            ],
        ).distinct()
        if faculty is not None:
            items = items.filter(itemtransactiondetails__transaction__faculty=faculty)
        if item_query:
            items = items.filter(name__icontains=item_query)

    return items.select_related("category", "sub_warehouse").order_by("name")


def render_to_pdf(request, template, context, is_page_break=False):
    html_string = render_to_string(template, context, request=request)
    if is_page_break:
        return html_string + '<div style="page-break-after: always;"></div>'
    return html_string


def render_pdf_file(request, pdf_filename, html_string):
    try:
        html = HTML(string=html_string, base_url=request.build_absolute_uri("/"))
        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{pdf_filename}"'
        html.write_pdf(response)
        return response
    except Exception as e:
        logger.error(f"PDF generation error: {str(e)}", exc_info=True)
        response = HttpResponse(
            "حدث خطأ أثناء إنشاء ملف PDF", content_type="text/plain"
        )
        response.status_code = 500
        return response


def create_pdf_report(request, template, context, pdf_filename, is_page_break=False):
    html_string = render_to_pdf(
        request=request,
        template=template,
        context=context,
        is_page_break=is_page_break,
    )
    return render_pdf_file(
        request=request,
        pdf_filename=pdf_filename,
        html_string=html_string,
    )


def validate_transfer_stock(transaction_form, transaction_details, faculty):
    errors = []
    castody_type = transaction_form.cleaned_data.get("castody_type")

    try:
        if castody_type == ItemTransactions.CASTODY_TYPES.Warehouse:
            from_sub_warehouse = transaction_form.cleaned_data.get("from_sub_warehouse")
            if not from_sub_warehouse:
                errors.append("المخزن الفرعي المرسل غير صالح أو لا ينتمي إلى كليتك.")
                return errors

            for detail in transaction_details:
                if hasattr(detail, "cleaned_data"):
                    if not detail.cleaned_data or detail.cleaned_data.get("DELETE"):
                        continue
                    item = detail.cleaned_data.get("item")
                    approved_qty = detail.cleaned_data.get("approved_quantity", 0)
                else:
                    item = detail.item
                    approved_qty = detail.approved_quantity

                if approved_qty <= 0 or not item:
                    continue

                stock = FacultyItemStock.objects.filter(
                    item=item,
                    sub_warehouse=from_sub_warehouse,
                    faculty=faculty,
                ).first()
                current_stock = stock.cached_quantity if stock else 0
                if current_stock <= 0:
                    errors.append(
                        f"الصنف '{item.name}' نافد في المخزن الفرعي '{from_sub_warehouse.name}'."
                    )
                elif approved_qty > current_stock:
                    errors.append(
                        f"الكمية ({approved_qty}) تتجاوز المتوفر ({current_stock}) من '{item.name}' في المخزن الفرعي '{from_sub_warehouse.name}'."
                    )

        elif castody_type in [
            ItemTransactions.CASTODY_TYPES.Personal,
            ItemTransactions.CASTODY_TYPES.Branch,
        ]:
            from_user = transaction_form.cleaned_data.get("from_user")
            if not from_user:
                errors.append("يجب تحديد الموظف المرسل.")
                return errors

            for detail in transaction_details:
                if hasattr(detail, "cleaned_data"):
                    if not detail.cleaned_data or detail.cleaned_data.get("DELETE"):
                        continue
                    item = detail.cleaned_data.get("item")
                    approved_qty = detail.cleaned_data.get("approved_quantity", 0)
                else:
                    item = detail.item
                    approved_qty = detail.approved_quantity

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


def verify_price_history(item, price, transaction_id=None):
    last_price = ItemPriceHistory.objects.filter(item=item).order_by("-date").first()
    if last_price and last_price.price == price:
        logger.debug(f"Price history verified for item {item.id}: {price}")
        return True

    logger.warning(
        f"Price history verification failed for item {item.id}. Expected: {price}, Found: {last_price.price if last_price else 'None'}"
    )
    return False


def is_safe_redirect_url(url, host):
    """
    Check if a URL is safe for redirect.
    Returns True if URL is relative or same-host absolute URL.
    """
    if not url:
        return False

    # Allow relative URLs (start with /)
    if url.startswith("/"):
        return True

    # Parse and check host
    parsed = urlparse(url)

    # Allow same-host URLs
    if parsed.netloc == host or parsed.netloc == "":
        return True

    # Allow URLs with allowed domains (optional)
    allowed_hosts = getattr(settings, "ALLOWED_REDIRECT_HOSTS", [])
    if parsed.netloc in allowed_hosts:
        return True

    return False


def _has_related_transactions(entity_type, entity_id):
    """
    Check if an entity has any related transactions.
    Returns (has_transactions: bool, message: str)
    """
    if entity_type == "user":
        # Check all user-related fields in ItemTransactions
        count = ItemTransactions.objects.filter(
            Q(from_user_id=entity_id)
            | Q(to_user_id=entity_id)
            | Q(created_by_id=entity_id)
            | Q(approval_user_id=entity_id)
            | Q(inventory_user_id=entity_id)
            | Q(deleted_by_id=entity_id)
            | Q(reversed_by_id=entity_id)
        ).count()
        if count > 0:
            return (
                True,
                f"لا يمكن حذف المستخدم لأن له {count} معاملة مرتبطة به في النظام.",
            )
        return False, ""

    elif entity_type == "department":
        # Check users in this department who have transactions
        from administration.models import UserProfile

        user_ids = UserProfile.objects.filter(department_id=entity_id).values_list(
            "user_id", flat=True
        )

        count = ItemTransactions.objects.filter(
            Q(from_user_id__in=user_ids)
            | Q(to_user_id__in=user_ids)
            | Q(created_by_id__in=user_ids)
            | Q(approval_user_id__in=user_ids)
            | Q(inventory_user_id__in=user_ids)
        ).count()

        if count > 0:
            return (
                True,
                f"لا يمكن حذف القسم لأن موظفيه لهم {count} معاملة مرتبطة في النظام.",
            )
        return False, ""

    elif entity_type == "faculty":
        # Check all transactions in this faculty + users in faculty
        from administration.models import UserProfile

        user_ids = UserProfile.objects.filter(faculty_id=entity_id).values_list(
            "user_id", flat=True
        )

        count = ItemTransactions.objects.filter(
            Q(faculty_id=entity_id)
            | Q(from_user_id__in=user_ids)
            | Q(to_user_id__in=user_ids)
            | Q(created_by_id__in=user_ids)
            | Q(approval_user_id__in=user_ids)
            | Q(inventory_user_id__in=user_ids)
        ).count()

        if count > 0:
            return True, f"لا يمكن حذف الكلية لأن لها {count} معاملة مرتبطة في النظام."
        return False, ""

    return False, ""
