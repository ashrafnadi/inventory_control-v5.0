from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class SystemSettings(models.Model):
    idle_timeout_minutes = models.PositiveIntegerField(
        default=30,
        verbose_name="مدة الخمول قبل تسجيل الخروج (دقيقة)",
        help_text="عدد الدقائق بدون نشاط قبل تسجيل الخروج التلقائي.",
    )
    session_warning_minutes = models.PositiveIntegerField(
        default=5,
        verbose_name="التحذير قبل انتهاء الجلسة (دقيقة)",
        help_text="عدد الدقائق قبل انتهاء الجلسة لإظهار نافذة التحذير.",
    )

    class Meta:
        verbose_name = "إعدادات النظام"
        verbose_name_plural = "إعدادات النظام"

    def __str__(self):
        return "إعدادات النظام"

    def clean(self):
        super().clean()
        if self.idle_timeout_minutes < 1 or self.idle_timeout_minutes > 480:
            raise ValidationError(
                {"idle_timeout_minutes": "مدة الخمول يجب أن تكون بين 1 و480 دقيقة."}
            )
        if self.session_warning_minutes < 1:
            raise ValidationError(
                {
                    "session_warning_minutes": "وقت التحذير يجب أن يكون دقيقة واحدة على الأقل."
                }
            )
        if self.session_warning_minutes >= self.idle_timeout_minutes:
            raise ValidationError(
                {
                    "session_warning_minutes": "وقت التحذير يجب أن يكون أقل من مدة الخمول."
                }
            )

    def save(self, *args, **kwargs):
        self.pk = 1
        self.full_clean()
        super().save(*args, **kwargs)
        cache.delete("system_settings")

    @classmethod
    def get(cls):
        settings_obj = cache.get("system_settings")
        if settings_obj is None:
            settings_obj, _ = cls.objects.get_or_create(pk=1)
            cache.set("system_settings", settings_obj, timeout=60)
        return settings_obj


class InventoryYear(models.Model):
    year = models.PositiveIntegerField(unique=True, verbose_name="السنة")
    is_open = models.BooleanField(default=True, verbose_name="مفتوحة")
    opened_at = models.DateTimeField(default=timezone.now, verbose_name="تاريخ الفتح")
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ الإغلاق")

    class Meta:
        verbose_name = "سنة المخزون"
        verbose_name_plural = "سنوات المخزون"
        ordering = ["-year"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_open"],
                condition=models.Q(is_open=True),
                name="unique_open_inventory_year",
            )
        ]

    def __str__(self):
        status = "مفتوحة" if self.is_open else "مغلقة"
        return f"{self.year} - {status}"

    @classmethod
    def get_open_year(cls):
        open_year = cls.objects.filter(is_open=True).first()
        if open_year:
            return open_year
        return cls.objects.create(year=timezone.now().year, is_open=True)

    def close_and_open_next(self):
        if not self.is_open:
            raise ValidationError("هذه السنة مغلقة بالفعل.")
        next_year_value = self.year + 1
        if InventoryYear.objects.filter(is_open=True).exclude(pk=self.pk).exists():
            raise ValidationError("لا يمكن أن تكون أكثر من سنة مفتوحة.")

        self.is_open = False
        self.closed_at = timezone.now()
        self.save(update_fields=["is_open", "closed_at"])
        next_year, _ = InventoryYear.objects.get_or_create(
            year=next_year_value,
            defaults={"is_open": True, "opened_at": timezone.now()},
        )
        if not next_year.is_open:
            next_year.is_open = True
            next_year.opened_at = timezone.now()
            next_year.closed_at = None
            next_year.save(update_fields=["is_open", "opened_at", "closed_at"])
        return next_year


class Faculty(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="اسم الكلية")

    class Meta:
        verbose_name = "الكلية"
        verbose_name_plural = "الكليات"

    def __str__(self):
        return self.name


class Department(models.Model):
    name = models.CharField(max_length=100, unique=False, verbose_name="اسم القسم")
    faculty = models.ForeignKey(
        Faculty, on_delete=models.CASCADE, verbose_name="الكلية"
    )

    class Meta:
        verbose_name = "القسم"
        verbose_name_plural = "الأقسام"
        indexes = [
            models.Index(fields=["faculty", "name"]),
        ]
        ordering = ["faculty", "name"]

    def __str__(self):
        return f"{self.name} - {self.faculty.name}"


class UserProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="بيانات المستخدم",
    )
    phone = models.CharField(
        max_length=15, blank=True, null=True, unique=True, verbose_name="رقم الهاتف"
    )
    national_id = models.CharField(
        max_length=20, unique=False, blank=True, null=True, verbose_name="الرقم القومي"
    )
    faculty = models.ForeignKey(
        Faculty,
        on_delete=models.CASCADE,
        verbose_name="الكلية",
        null=True,
        blank=True,
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        verbose_name="القسم",
        null=True,
        blank=True,
    )
    is_user = models.BooleanField(default=True, verbose_name="مستخدم عادي")
    is_inventory_manager = models.BooleanField(
        default=False, verbose_name="مدير المخازن"
    )
    is_inventory_employee = models.BooleanField(
        default=False, verbose_name="موظف المخازن"
    )
    is_administration_manager = models.BooleanField(
        default=False, verbose_name="مدير الإدارة"
    )
    is_faculty_manager = models.BooleanField(default=False, verbose_name="مدير الكلية")

    class Meta:
        verbose_name = "ملف المستخدم"
        verbose_name_plural = "ملفات المستخدمين"

    def clean(self):
        super().clean()
        if (
            self.department
            and self.faculty
            and self.department.faculty_id != self.faculty_id
        ):
            raise ValidationError(
                {"department": "القسم المحدد لا ينتمي إلى الكلية المختارة."}
            )

    def save(self, *args, **kwargs):
        if self.department_id and not self.faculty_id:
            self.faculty = self.department.faculty
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        faculty_name = self.faculty.name if self.faculty else "بدون كلية"
        department_name = self.department.name if self.department else "بدون قسم"
        return f"{self.user.username} - {faculty_name} - {department_name}"
