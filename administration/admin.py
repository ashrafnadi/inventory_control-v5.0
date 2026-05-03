# admin.py
from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import Department, Faculty, InventoryYear, SystemSettings, UserProfile


class UserProfileInlineForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["department"].queryset = Department.objects.none()

        faculty_id = None
        if self.instance and self.instance.pk and self.instance.faculty_id:
            faculty_id = self.instance.faculty_id
        elif self.data:
            for key, value in self.data.items():
                if key.endswith("-faculty") and value:
                    faculty_id = value
                    break

        if faculty_id:
            self.fields["department"].queryset = Department.objects.filter(
                faculty_id=faculty_id
            ).order_by("name")
        elif self.instance and self.instance.department_id:
            self.fields["department"].queryset = Department.objects.filter(
                pk=self.instance.department_id
            )


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    form = UserProfileInlineForm
    can_delete = False
    verbose_name = "ملف المستخدم"
    verbose_name_plural = "ملف المستخدم"
    fieldsets = (
        (
            "الحالة",
            {
                "fields": (
                    "is_user",
                    "is_inventory_manager",
                    "is_inventory_employee",
                    "is_administration_manager",
                    "is_faculty_manager",
                )
            },
        ),
        (
            "المعلومات الشخصية",
            {
                "fields": (
                    "phone",
                    "national_id",
                    "faculty",
                    "department",
                )
            },
        ),
    )


admin.site.unregister(User)


class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)

    def get_inline_instances(self, request, obj=None):
        if obj is None:
            return []
        return super().get_inline_instances(request, obj)


admin.site.register(User, UserAdmin)
admin.site.register(Faculty)
admin.site.register(Department)


@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        (
            "إعدادات الجلسة",
            {"fields": ("idle_timeout_minutes", "session_warning_minutes")},
        ),
    )

    def has_add_permission(self, request):
        return not SystemSettings.objects.exists()


@admin.register(InventoryYear)
class InventoryYearAdmin(admin.ModelAdmin):
    list_display = ("year", "is_open", "opened_at", "closed_at")
    list_filter = ("is_open",)
    readonly_fields = ("opened_at", "closed_at")


admin.site.site_header = "لوحة إدارة نظام المخازن - جامعة بنها"
admin.site.site_title = "نظام المخازن - جامعة بنها"
admin.site.index_title = "لوحة تحكم إدارة نظام المخازن - جامعة بنها"
admin.site.empty_value_display = "-لا يوجد-"
admin.site.login_error_message = "اسم المستخدم أو كلمة المرور غير صحيحة. حاول مرة أخرى."
admin.site.login_template = "account/login.html"
admin.site.logout_template = "account/logout.html"
# admin.site.password_change_template = "account/partials/change_password.html"
# admin.site.password_change_done_template = "account/partials/change_password_done.html"
