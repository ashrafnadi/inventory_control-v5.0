from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .models import Department, Faculty, SystemSettings, UserProfile


class SessionSettingsForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = ["idle_timeout_minutes", "session_warning_minutes"]
        widgets = {
            "idle_timeout_minutes": forms.NumberInput(
                attrs={"class": "form-control", "min": 1, "max": 480}
            ),
            "session_warning_minutes": forms.NumberInput(
                attrs={"class": "form-control", "min": 1, "max": 60}
            ),
        }


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "dir": "rtl"}),
        }


class EmployeeForm(forms.ModelForm):
    """
    Form for employee profile.
    NOTE: first_name/last_name belong to User model, handled separately in view.
    """

    first_name = forms.CharField(
        max_length=30,
        widget=forms.TextInput(attrs={"class": "form-control", "dir": "rtl"}),
        label="الاسم الأول",
        required=True,
    )
    last_name = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
        initial="",
    )

    class Meta:
        model = UserProfile
        fields = ["phone", "department"]
        widgets = {
            "phone": forms.TextInput(attrs={"class": "form-control", "dir": "rtl"}),
            "department": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        user_faculty = kwargs.pop("user_faculty", None)
        super().__init__(*args, **kwargs)

        # Filter departments by faculty
        if user_faculty:
            self.fields["department"].queryset = Department.objects.filter(
                faculty=user_faculty
            ).order_by("name")
        else:
            self.fields["department"].queryset = Department.objects.none()

        # Pre-populate first_name from related User when editing
        if self.instance.pk and hasattr(self.instance, "user") and self.instance.user:
            if "first_name" not in self.initial:
                self.initial["first_name"] = self.instance.user.first_name

    def clean_phone(self):
        """Ensure phone is unique (per your model's unique=True constraint)."""
        phone = self.cleaned_data.get("phone")
        if phone:
            queryset = UserProfile.objects.filter(phone=phone)
            if self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise ValidationError("رقم الهاتف مستخدم بالفعل لموظف آخر.")
        return phone


class UserPasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(
        label="كلمة المرور القديمة",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "current-password",
                "autofocus": True,
                "dir": "rtl",
            }
        ),
    )
    new_password1 = forms.CharField(
        label="كلمة المرور الجديدة",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "new-password",
                "dir": "rtl",
            }
        ),
        help_text=password_validation.password_validators_help_text_html(),
    )
    new_password2 = forms.CharField(
        label="تأكيد كلمة المرور الجديدة",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "new-password",
                "dir": "rtl",
            }
        ),
        help_text="أدخل نفس كلمة المرور الجديدة للتأكيد.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add Bootstrap classes to all fields
        for field in self.fields.values():
            if "class" not in field.widget.attrs:
                field.widget.attrs["class"] = "form-control"

        # Add dir="rtl" to all fields
        for field in self.fields.values():
            if "dir" not in field.widget.attrs:
                field.widget.attrs["dir"] = "rtl"


class UserAdminForm(forms.ModelForm):
    """Combined form for User + UserProfile (Admin only)"""

    password = forms.CharField(
        label="كلمة المرور",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "اتركها فارغة للإبقاء على الحالية",
            }
        ),
        required=False,
    )
    faculty = forms.ModelChoiceField(
        queryset=Faculty.objects.all(),
        required=False,
        label="الكلية",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    department = forms.ModelChoiceField(
        queryset=Department.objects.all(),
        required=False,
        label="القسم",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    phone = forms.CharField(
        required=False,
        label="رقم الهاتف",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

    is_user = forms.BooleanField(required=False, label="مستخدم عادي", initial=True)
    is_inventory_manager = forms.BooleanField(required=False, label="مدير المخازن")
    is_inventory_employee = forms.BooleanField(required=False, label="موظف المخازن")
    is_administration_manager = forms.BooleanField(required=False, label="مدير الإدارة")
    is_faculty_manager = forms.BooleanField(required=False, label="مدير الكلية")

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "is_active",
            "is_staff",
            "is_superuser",
        ]
        widgets = {
            "username": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "اسم المستخدم"}
            ),
            "first_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "الاسم الأول"}
            ),
            "last_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "اسم العائلة"}
            ),
            "email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "البريد الإلكتروني"}
            ),
        }

    def __init__(self, *args, **kwargs):
        # Extract faculty_id from kwargs if provided (for AJAX pre-filtering)
        initial_faculty_id = kwargs.pop("initial_faculty_id", None)
        super().__init__(*args, **kwargs)

        # Filter department queryset if faculty is selected
        if initial_faculty_id:
            self.fields["department"].queryset = Department.objects.filter(
                faculty_id=initial_faculty_id
            ).order_by("name")
        elif (
            self.instance.pk
            and hasattr(self.instance, "profile")
            and self.instance.profile.faculty
        ):
            # When editing, pre-filter by user's current faculty
            self.fields["department"].queryset = Department.objects.filter(
                faculty=self.instance.profile.faculty
            ).order_by("name")
        else:
            # Default: show all departments (for superuser flexibility)
            self.fields["department"].queryset = Department.objects.all().order_by(
                "name"
            )

    def clean_username(self):
        username = self.cleaned_data.get("username")
        if User.objects.filter(username=username).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("اسم المستخدم موجود مسبقاً")
        return username


class FacultyForm(forms.ModelForm):
    class Meta:
        model = Faculty
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "اسم الكلية"}
            )
        }
        labels = {"name": "اسم الكلية"}

    def clean_name(self):
        name = self.cleaned_data.get("name", "").strip()
        if (
            Faculty.objects.filter(name__iexact=name)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise forms.ValidationError("كلية بهذا الاسم موجودة مسبقاً")
        return name


# administration/forms.py


class FacultyDepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name", "faculty"]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "اسم القسم"}
            ),
            "faculty": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {"name": "اسم القسم", "faculty": "الكلية"}

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get("name")
        faculty = cleaned_data.get("faculty")

        if name and faculty:
            # 🔍 Check for duplicates (case-insensitive)
            qs = Department.objects.filter(name__iexact=name.strip(), faculty=faculty)

            # Exclude current instance when editing
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                self.add_error(
                    "name",
                    f"يوجد قسم باسم '{name.strip()}' بالفعل في كلية '{faculty.name}'.",
                )

        return cleaned_data
