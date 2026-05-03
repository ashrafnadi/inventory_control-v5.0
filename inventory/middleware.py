import logging
import time

from django.conf import settings
from django.contrib.auth import logout
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


def get_idle_timeout_seconds():
    try:
        from administration.models import SystemSettings

        return SystemSettings.get().idle_timeout_minutes * 60
    except Exception:
        return getattr(settings, "SESSION_COOKIE_AGE", 1800)


class InventoryPermissionMiddleware(MiddlewareMixin):
    """
    Middleware to enforce inventory permissions and faculty isolation.
    """

    def process_view(self, request, view_func, view_args, view_kwargs):
        # Skip if user is not authenticated or accessing login page
        if not request.user.is_authenticated or request.path.startswith(
            "/accounts/login/"
        ):
            return None

        # Check if view requires inventory permissions
        view_name = view_func.__name__
        inventory_views = [
            "transaction_approve_view",
            "transaction_reject_view",
            "transaction_delete_view",
            "transaction_update_view",
        ]

        if view_name not in inventory_views:
            return None

        # Faculty existence check
        if not (hasattr(request.user, "profile") and request.user.profile.faculty):
            raise PermissionDenied("ليس لديك كليّة مرتبطة بحسابك.")

        # Role check for approval/rejection
        if view_name in ["transaction_approve_view", "transaction_reject_view"]:
            if not (
                hasattr(request.user, "profile")
                and request.user.profile.is_inventory_manager
            ):
                raise PermissionDenied("ليس لديك صلاحية اعتماد السندات.")

        # Faculty isolation for specific transaction
        if "pk" in view_kwargs:
            from .models import ItemTransactions

            try:
                transaction = ItemTransactions.objects.select_related(
                    "created_by__profile"
                ).get(pk=view_kwargs["pk"])
            except ItemTransactions.DoesNotExist:
                raise Http404

            # Guard against incomplete data
            if not hasattr(transaction.created_by, "profile"):
                logger.error("Transaction %s has no creator profile", view_kwargs["pk"])
                raise PermissionDenied("بيانات السند غير مكتملة.")

            if (
                transaction.created_by.profile.faculty_id
                != request.user.profile.faculty_id
            ):
                raise PermissionDenied(
                    "ليس لديك صلاحية الوصول إلى سندات الكليات الأخرى."
                )

        return None


class SessionTimeoutMiddleware:
    """
    Logs out user after SESSION_COOKIE_AGE seconds of inactivity,
    regardless of browser close behavior.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip for anonymous users, login page, or static files
        if not request.user.is_authenticated:
            return self.get_response(request)

        if request.path in [reverse("login"), reverse("logout"), "/static/", "/media/"]:
            return self.get_response(request)

        # Check last activity timestamp
        last_activity = request.session.get("last_activity")
        now = time.time()

        if last_activity and (now - last_activity) > get_idle_timeout_seconds():
            # Session expired → logout and redirect
            logout(request)
            return redirect("login")

        # Update last activity timestamp
        request.session["last_activity"] = now
        request.session.modified = True  # Ensure session is saved

        return self.get_response(request)
