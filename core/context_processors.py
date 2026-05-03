from django.conf import settings

from administration.models import InventoryYear, SystemSettings
from inventory.models import SubWarehouse


def settings_processor(request):
    """
    Context processor to add settings to the context.
    """
    try:
        system_settings = SystemSettings.get()
        idle_timeout_ms = system_settings.idle_timeout_minutes * 60 * 1000
        session_warning_ms = max(
            system_settings.session_warning_minutes * 60 * 1000, 30000
        )
    except Exception:
        system_settings = None
        idle_timeout_ms = settings.SESSION_COOKIE_AGE * 1000
        session_warning_ms = 300000

    try:
        open_year = InventoryYear.get_open_year()
    except Exception:
        open_year = None

    user = getattr(request, "user", None)
    user_display_name = "زائر"
    department_name = ""
    if user and user.is_authenticated:
        user_display_name = user.get_full_name() or user.username
        department = getattr(getattr(user, "profile", None), "department", None)
        faculty = getattr(getattr(user, "profile", None), "faculty", None)
        department_name = (
            department.name if department else (faculty.name if faculty else "")
        )

    db_engine = settings.DATABASES["default"]["ENGINE"]
    is_postgres = "postgresql" in db_engine.lower()

    return {
        "APPLICATION_NAME": settings.APPLICATION_NAME,
        "is_postgres": is_postgres,
        "LOGIN_PAGE_TITLE": settings.LOGIN_PAGE_TITLE,
        "HOME_PAGE_TITLE": settings.HOME_PAGE_TITLE,
        "ORDER_PAGE_TITLE": settings.ORDER_PAGE_TITLE,
        "COPYRIGHT_NAME": settings.COPYRIGHT_NAME,
        "COPYRIGHT_YEAR": settings.COPYRIGHT_YEAR,
        "system_settings": system_settings,
        "open_year": open_year,
        "idle_timeout_ms": idle_timeout_ms,
        "session_warning_ms": session_warning_ms,
        "user_display_name": user_display_name,
        "department": department_name,
        "faculty": faculty.name if faculty else "",
    }


def sub_warehouses_processor(request):
    """Add shared sub-warehouses to the global template context."""
    context = {}

    if request.user.is_authenticated:
        sub_warehouses = SubWarehouse.objects.select_related("warehouse").order_by(
            "name"
        )

        context["sub_warehouses"] = sub_warehouses

        selected_sub_warehouse_id = request.GET.get(
            "sub_warehouse"
        ) or request.session.get("selected_sub_warehouse_id")
        if selected_sub_warehouse_id:
            try:
                selected_sub_warehouse_id = int(selected_sub_warehouse_id)
                context["selected_sub_warehouse_id"] = selected_sub_warehouse_id
                request.session["selected_sub_warehouse_id"] = selected_sub_warehouse_id
            except (ValueError, TypeError):
                pass

    return context
