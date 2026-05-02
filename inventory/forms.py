# inventory/forms.py
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory

from .models import (
    Department,
    FacultyItemStock,
    Item,
    ItemCategory,
    ItemTransactionDetails,
    ItemTransactions,
    SubWarehouse,
    Supplier,
    Warehouse,
)
from .utils import (
    get_departments_for_user,
)

User = get_user_model()
SHARED_SUB_WAREHOUSES = SubWarehouse.objects.select_related("warehouse").order_by(
    "name"
)


class ItemForm(forms.ModelForm):
    """Global item form — includes sub_warehouse for selecting home sub-warehouse."""

    class Meta:
        model = Item
        fields = [
            "code",
            "name",
            "category",
            "limit_quantity",
            "unit",
            "unit_fraction",
            "spacefication",
            "item_image",
        ]
        widgets = {
            "code": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "dir": "ltr",
                    "placeholder": "أدخل كود الصنف أو اتركه فارغاً للإنشاء التلقائي",
                    "maxlength": "100",
                }
            ),
            "name": forms.TextInput(attrs={"class": "form-control", "dir": "rtl"}),
            "category": forms.Select(
                attrs={
                    "class": "form-select",
                    "required": "required",
                }
            ),
            "limit_quantity": forms.NumberInput(attrs={"class": "form-control"}),
            "unit": forms.Select(attrs={"class": "form-select"}),
            "unit_fraction": forms.NumberInput(attrs={"class": "form-control"}),
            "spacefication": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "item_image": forms.FileInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        kwargs.pop("user_faculty", None)  # Accept but ignore legacy kwarg
        super().__init__(*args, **kwargs)

        # Set queryset for category field
        self.fields["category"].queryset = ItemCategory.objects.all().order_by("name")
        self.fields["category"].empty_label = "-- اختر الفئة --"

        # Set help text and placeholders
        self.fields[
            "code"
        ].help_text = "يمكن تعديله، يجب أن يكون فريداً. اتركه فارغاً للإنشاء التلقائي"
        if self.instance.pk and self.instance.code:
            self.fields["code"].widget.attrs["placeholder"] = ""

    def clean_code(self):
        code = self.cleaned_data.get("code")
        if not code or code.strip() == "":
            return None
        code = code.strip()
        queryset = Item.objects.filter(code=code)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise ValidationError(
                "هذا الكود مستخدم بالفعل لصنف آخر. يرجى اختيار كود فريد."
            )
        return code


class ItemTransactionForm(forms.ModelForm):
    class Meta:
        model = ItemTransactions
        fields = [
            "transaction_type",
            "castody_type",
            "document_type",
            "from_sub_warehouse",
            "to_sub_warehouse",
            "to_department",
            "to_user",
            "notes",
            "created_by",
            "approval_status",
            "faculty",
        ]
        widgets = {
            "transaction_type": forms.HiddenInput(),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control border-0 p-0 bg-transparent shadow-none",
                    "rows": 1,
                    "placeholder": "اكتب ملاحظاتك هنا...",
                    "style": "resize: none; outline: none;",
                }
            ),
            "created_by": forms.HiddenInput(),
            "approval_status": forms.HiddenInput(),
            "faculty": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.user_type = kwargs.pop("user_type", None)
        self.from_sub_warehouse_id = kwargs.pop("from_sub_warehouse_id", None)
        self.to_department_id = kwargs.pop("to_department_id", None)
        super().__init__(*args, **kwargs)

        # Auto-set faculty from user profile
        if self.user and hasattr(self.user, "profile") and self.user.profile.faculty:
            self.instance.faculty = self.user.profile.faculty
            self.fields["faculty"].initial = self.user.profile.faculty.id

        if self.instance.pk is None:
            self.fields["created_by"].initial = self.user.id
            self.fields[
                "approval_status"
            ].initial = ItemTransactions.APPROVAL_STATUS.PENDING
            self.fields[
                "transaction_type"
            ].initial = ItemTransactions.TRANSACTION_TYPES.Disbursement

        self.fields["created_by"].disabled = True
        self.fields["approval_status"].disabled = True
        self.fields["transaction_type"].disabled = True

        # Filter warehouses to faculty scope if needed
        if self.instance.faculty:
            self.fields["from_sub_warehouse"].queryset = (
                SubWarehouse.objects.filter(item_stocks__faculty=self.instance.faculty)
                .distinct()
                .order_by("name")
            )
            self.fields["to_sub_warehouse"].queryset = (
                SubWarehouse.objects.filter(item_stocks__faculty=self.instance.faculty)
                .distinct()
                .order_by("name")
            )
        else:
            self.fields["from_sub_warehouse"].queryset = SHARED_SUB_WAREHOUSES
            self.fields["to_sub_warehouse"].queryset = SHARED_SUB_WAREHOUSES

        self.fields["to_department"].queryset = get_departments_for_user(self.user)

    def clean(self):
        cleaned_data = super().clean()
        castody_type = cleaned_data.get("castody_type")
        to_sub_warehouse = cleaned_data.get("to_sub_warehouse")
        to_department = cleaned_data.get("to_department")
        to_user = cleaned_data.get("to_user")

        if castody_type == ItemTransactions.CASTODY_TYPES.Warehouse:
            if not to_sub_warehouse:
                self.add_error(
                    "to_sub_warehouse", "هذا الحقل مطلوب عند اختيار عهدة مخزنية."
                )
            cleaned_data["to_department"] = None
            cleaned_data["to_user"] = None
        elif castody_type in (
            ItemTransactions.CASTODY_TYPES.Personal,
            ItemTransactions.CASTODY_TYPES.Branch,
        ):
            if not to_department:
                self.add_error("to_department", "هذا الحقل مطلوب.")
            if not to_user:
                self.add_error("to_user", "هذا الحقل مطلوب.")
            cleaned_data["to_sub_warehouse"] = None

        return cleaned_data


class ItemTransactionAdditionForm(forms.ModelForm):
    class Meta:
        model = ItemTransactions
        fields = [
            "id",
            "document_type",
            "transaction_type",
            "to_sub_warehouse",
            "inventory_user",
            "castody_type",
            "supplier",
            "notes",
            "created_by",
            "approval_status",
        ]
        widgets = {
            "id": forms.HiddenInput(),
            "transaction_type": forms.HiddenInput(),
            "castody_type": forms.HiddenInput(),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control border-0 p-0 bg-transparent shadow-none",
                    "rows": 1,
                    "placeholder": "اكتب ملاحظاتك هنا...",
                    "style": "resize: none; outline: none;",
                }
            ),
            "created_by": forms.HiddenInput(),
            "approval_status": forms.HiddenInput(),
            "inventory_user": forms.HiddenInput(),
            "approved_quantity": forms.NumberInput(
                attrs={"class": "form-control form-control-sm"}
            ),
            "price": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "step": "0.01",
                    "min": "0",
                    "placeholder": "أدخل السعر",
                }
            ),
            "status": forms.Select(attrs={"class": "form-select form-select-sm"}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.user_type = kwargs.pop("user_type", None)
        self.to_warehouse_id = kwargs.pop("to_warehouse_id", None)
        super().__init__(*args, **kwargs)

        if self.instance.pk is None:
            self.fields["created_by"].initial = self.user.id
            self.fields[
                "approval_status"
            ].initial = ItemTransactions.APPROVAL_STATUS.PENDING
            self.fields["inventory_user"].initial = self.user.id

        self.fields["created_by"].disabled = True
        self.fields["approval_status"].disabled = True
        self.fields["inventory_user"].disabled = True

        self.fields[
            "transaction_type"
        ].initial = ItemTransactions.TRANSACTION_TYPES.Addition
        self.fields["castody_type"].initial = ItemTransactions.CASTODY_TYPES.Warehouse
        self.fields["transaction_type"].disabled = True
        self.fields["castody_type"].disabled = True
        self.fields["to_sub_warehouse"].queryset = SHARED_SUB_WAREHOUSES

        if "approval_user" in self.fields:
            del self.fields["approval_user"]

        self.fields["inventory_user"].queryset = User.objects.filter(id=self.user.id)

    def clean_inventory_user(self):
        return self.user

    def clean(self):
        cleaned_data = super().clean()
        item = cleaned_data.get("item")
        price = cleaned_data.get("price")
        approved_quantity = cleaned_data.get("approved_quantity")

        # If item is selected AND quantity > 0, price must be > 0
        if item and approved_quantity and approved_quantity > 0:
            if price is None or price <= 0:
                raise ValidationError({"price": "يجب إدخال سعر للصنف عند إضافة كمية."})

        return cleaned_data


class ItemTransactionReturnForm(forms.ModelForm):
    class Meta:
        model = ItemTransactions
        fields = [
            "transaction_type",
            "castody_type",
            "document_type",
            "to_sub_warehouse",
            "from_department",
            "from_user",
            "notes",
            "inventory_user",
            "approval_user",
            "created_by",
            "approval_status",
        ]
        widgets = {
            "transaction_type": forms.HiddenInput(),
            "castody_type": forms.HiddenInput(),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control border-0 p-0 bg-transparent shadow-none",
                    "rows": 1,
                    "placeholder": "اكتب ملاحظاتك هنا...",
                    "style": "resize: none; outline: none;",
                }
            ),
            "created_by": forms.HiddenInput(),
            "approval_status": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.user_type = kwargs.pop("user_type", None)
        super().__init__(*args, **kwargs)
        if self.instance.pk is None:  # New transaction
            self.fields["created_by"].initial = self.user.id
            self.fields[
                "approval_status"
            ].initial = ItemTransactions.APPROVAL_STATUS.PENDING
        self.fields["created_by"].disabled = True
        self.fields["approval_status"].disabled = True
        self.fields[
            "transaction_type"
        ].initial = ItemTransactions.TRANSACTION_TYPES.Return
        self.fields["castody_type"].initial = ItemTransactions.CASTODY_TYPES.Warehouse
        self.fields["transaction_type"].disabled = True
        self.fields["castody_type"].disabled = True

        if self.user and hasattr(self.user, "profile") and self.user.profile.faculty:
            faculty = self.user.profile.faculty
            self.fields["to_sub_warehouse"].queryset = SHARED_SUB_WAREHOUSES
            self.fields["from_department"].queryset = Department.objects.filter(
                faculty=faculty
            )

        self.fields["inventory_user"].queryset = (
            User.objects.filter(id=self.user.id) if self.user else User.objects.none()
        )
        self.fields["inventory_user"].initial = self.user

        # Handle approval_user field consistently
        if self.user_type == "inventory_employee":
            if "approval_user" in self.fields:
                del self.fields["approval_user"]
        elif self.user_type == "inventory_manager":
            if "approval_user" in self.fields:
                self.fields["approval_user"].widget = forms.Select(
                    attrs={"class": "form-select", "disabled": "disabled"}
                )
                if not self.instance.pk:
                    self.fields["approval_user"].initial = self.user
        else:
            if "inventory_user" in self.fields:
                self.fields["inventory_user"].widget = forms.HiddenInput()
            if "approval_user" in self.fields:
                self.fields["approval_user"].widget = forms.HiddenInput()

    def clean(self):
        cleaned_data = super().clean()
        from_user = cleaned_data.get("from_user")
        if not from_user:
            raise ValidationError("يجب تحديد الموظف المرتجع منه.")
        return cleaned_data


class ItemTransactionTransferForm(forms.ModelForm):
    class Meta:
        model = ItemTransactions
        fields = [
            "document_type",
            "transaction_type",
            "castody_type",
            # Warehouse custody fields
            "from_sub_warehouse",
            "to_sub_warehouse",
            # Department/personal custody fields
            "from_department",
            "from_user",
            "to_department",
            "to_user",
            "notes",
            "created_by",
            "approval_status",
        ]
        widgets = {
            "transaction_type": forms.HiddenInput(),
            "castody_type": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control border-0 p-0 bg-transparent shadow-none",
                    "rows": 1,
                    "placeholder": "اكتب ملاحظاتك هنا...",
                    "style": "resize: none; outline: none;",
                }
            ),
            "document_number": forms.TextInput(attrs={"class": "form-control"}),
            "document_type": forms.Select(attrs={"class": "form-select"}),
            "created_by": forms.HiddenInput(),
            "approval_status": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.user_type = kwargs.pop("user_type", None)
        super().__init__(*args, **kwargs)

        if self.instance.pk is None:  # New transaction
            self.fields["created_by"].initial = self.user.id
            self.fields[
                "approval_status"
            ].initial = ItemTransactions.APPROVAL_STATUS.PENDING

        self.fields["created_by"].disabled = True
        self.fields["approval_status"].disabled = True

        # Set transaction type to Transfer
        self.fields[
            "transaction_type"
        ].initial = ItemTransactions.TRANSACTION_TYPES.Transfer
        self.fields["transaction_type"].disabled = True

        # Faculty isolation for all fields
        if self.user and hasattr(self.user, "profile") and self.user.profile.faculty:
            faculty = self.user.profile.faculty

            # Warehouse custody fields
            self.fields["from_sub_warehouse"] = forms.ModelChoiceField(
                queryset=SHARED_SUB_WAREHOUSES,
                required=False,
                widget=forms.Select(attrs={"class": "form-select"}),
                label="من المخزن الفرعي",
                empty_label="---------",
            )
            self.fields["to_sub_warehouse"] = forms.ModelChoiceField(
                queryset=SHARED_SUB_WAREHOUSES,
                required=False,
                widget=forms.Select(attrs={"class": "form-select"}),
                label="إلى المخزن الفرعي",
                empty_label="---------",
            )

            # Department custody fields
            self.fields["from_department"] = forms.ModelChoiceField(
                queryset=Department.objects.filter(faculty=faculty),
                required=False,
                widget=forms.Select(attrs={"class": "form-select"}),
                label="من القسم",
                empty_label="---------",
            )
            self.fields["to_department"] = forms.ModelChoiceField(
                queryset=Department.objects.filter(faculty=faculty),
                required=False,
                widget=forms.Select(attrs={"class": "form-select"}),
                label="إلى القسم",
                empty_label="---------",
            )

            # User fields (will be populated dynamically)
            self.fields["from_user"] = forms.ModelChoiceField(
                queryset=User.objects.none(),
                required=False,
                widget=forms.Select(
                    attrs={"class": "form-select", "disabled": "disabled"}
                ),
                label="من الموظف",
                empty_label="---------",
            )
            self.fields["to_user"] = forms.ModelChoiceField(
                queryset=User.objects.none(),
                required=False,
                widget=forms.Select(
                    attrs={"class": "form-select", "disabled": "disabled"}
                ),
                label="إلى الموظف",
                empty_label="---------",
            )

        else:
            # Fallback for users without faculty
            self.fields["from_sub_warehouse"] = forms.ModelChoiceField(
                queryset=SubWarehouse.objects.none(),
                required=False,
                widget=forms.Select(
                    attrs={"class": "form-select", "disabled": "disabled"}
                ),
                label="من المخزن الفرعي",
                empty_label="---------",
            )
            self.fields["to_sub_warehouse"] = forms.ModelChoiceField(
                queryset=SubWarehouse.objects.none(),
                required=False,
                widget=forms.Select(
                    attrs={"class": "form-select", "disabled": "disabled"}
                ),
                label="إلى المخزن الفرعي",
                empty_label="---------",
            )
            self.fields["from_department"] = forms.ModelChoiceField(
                queryset=Department.objects.none(),
                required=False,
                widget=forms.Select(
                    attrs={"class": "form-select", "disabled": "disabled"}
                ),
                label="من القسم",
                empty_label="---------",
            )
            self.fields["to_department"] = forms.ModelChoiceField(
                queryset=Department.objects.none(),
                required=False,
                widget=forms.Select(
                    attrs={"class": "form-select", "disabled": "disabled"}
                ),
                label="إلى القسم",
                empty_label="---------",
            )
            self.fields["from_user"] = forms.ModelChoiceField(
                queryset=User.objects.none(),
                required=False,
                widget=forms.Select(
                    attrs={"class": "form-select", "disabled": "disabled"}
                ),
                label="من الموظف",
                empty_label="---------",
            )
            self.fields["to_user"] = forms.ModelChoiceField(
                queryset=User.objects.none(),
                required=False,
                widget=forms.Select(
                    attrs={"class": "form-select", "disabled": "disabled"}
                ),
                label="إلى الموظف",
                empty_label="---------",
            )

        # Handle approval_user field consistently
        if self.user_type == "inventory_employee":
            if "approval_user" in self.fields:
                del self.fields["approval_user"]
        elif self.user_type == "inventory_manager":
            # Managers can see approval_user but cannot edit it
            if "approval_user" in self.fields:
                self.fields["approval_user"].widget = forms.Select(
                    attrs={"class": "form-select", "disabled": "disabled"}
                )
                if not self.instance.pk:
                    self.fields["approval_user"].initial = self.user
        else:
            if "approval_user" in self.fields:
                self.fields["approval_user"].widget = forms.HiddenInput()

    def clean(self):
        cleaned_data = super().clean()
        castody_type = cleaned_data.get("castody_type")

        # Clear opposite fields based on custody type
        if castody_type == ItemTransactions.CASTODY_TYPES.Warehouse:
            cleaned_data["from_department"] = None
            cleaned_data["to_department"] = None
            cleaned_data["from_user"] = None
            cleaned_data["to_user"] = None

            from_sw = cleaned_data.get("from_sub_warehouse")
            to_sw = cleaned_data.get("to_sub_warehouse")

            if not from_sw:
                self.add_error(
                    "from_sub_warehouse", "هذا الحقل مطلوب عند اختيار عهدة مخزنية."
                )
            if not to_sw:
                self.add_error(
                    "to_sub_warehouse", "هذا الحقل مطلوب عند اختيار عهدة مخزنية."
                )
            if from_sw and to_sw and from_sw == to_sw:
                self.add_error(
                    "to_sub_warehouse", "لا يمكن النقل إلى نفس المخزن الفرعي."
                )

        elif castody_type == ItemTransactions.CASTODY_TYPES.Personal:
            cleaned_data["from_sub_warehouse"] = None
            cleaned_data["to_sub_warehouse"] = None

            from_user = cleaned_data.get("from_user")
            to_user = cleaned_data.get("to_user")

            if not from_user:
                self.add_error("from_user", "يجب تحديد الموظف المرسل.")
            if not to_user:
                self.add_error("to_user", "يجب تحديد الموظف المستلم.")
            if from_user and to_user and from_user == to_user:
                self.add_error("to_user", "لا يمكن النقل إلى نفس الموظف.")

        elif castody_type == ItemTransactions.CASTODY_TYPES.Branch:
            cleaned_data["from_sub_warehouse"] = None
            cleaned_data["to_sub_warehouse"] = None

            from_dept = cleaned_data.get("from_department")
            to_dept = cleaned_data.get("to_department")

            if not from_dept:
                self.add_error("from_department", "يجب تحديد القسم المرسل.")
            if not to_dept:
                self.add_error("to_department", "يجب تحديد القسم المستلم.")
            if from_dept and to_dept and from_dept == to_dept:
                self.add_error("to_department", "لا يمكن النقل إلى نفس القسم.")

        return cleaned_data

    def clean_from_sub_warehouse(self):
        sub_warehouse = self.cleaned_data.get("from_sub_warehouse")
        if (
            sub_warehouse
            and hasattr(self.user, "profile")
            and self.user.profile.faculty
        ):
            pass
        return sub_warehouse

    def clean_to_sub_warehouse(self):
        sub_warehouse = self.cleaned_data.get("to_sub_warehouse")
        if (
            sub_warehouse
            and hasattr(self.user, "profile")
            and self.user.profile.faculty
        ):
            pass
        return sub_warehouse


# inventory/forms.py


class ItemTransactionDetailsDisbursementForm(forms.ModelForm):
    class Meta:
        model = ItemTransactionDetails
        fields = [
            "item",
            "order_quantity",
            "approved_quantity",
            "status",
            "notes",
            "price",
        ]
        widgets = {
            "item": forms.HiddenInput(),
            "order_quantity": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": "1"}
            ),
            "approved_quantity": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": "1"}
            ),
            "status": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control form-control-sm border-0 bg-transparent shadow-none",
                    "rows": "1",
                }
            ),
            "price": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "step": "0.01",
                    "min": "0",
                    "placeholder": "0.00",
                }
            ),
        }
        labels = {"price": "سعر العهدة"}

    def __init__(self, *args, **kwargs):
        self.faculty = kwargs.pop("faculty", None)
        self.from_sub_warehouse_id = kwargs.pop("from_sub_warehouse_id", None)
        super().__init__(*args, **kwargs)

        if not self.instance.pk and self.instance.item_id:
            latest = self.instance.item.itempricehistory_set.order_by("-date").first()
            if latest and latest.price:
                self.fields["price"].initial = latest.price
        elif not self.instance.pk and self.initial.get("item"):
            item = self.initial["item"]
            if hasattr(item, "itempricehistory_set"):
                latest = item.itempricehistory_set.order_by("-date").first()
                if latest and latest.price:
                    self.fields["price"].initial = latest.price

    def clean_item(self):
        """Ensure item is selected."""
        item = self.cleaned_data.get("item")
        if not item:
            raise forms.ValidationError("يجب اختيار صنف")
        return item

    # inventory/forms.py - Inside ItemTransactionDetailsDisbursementForm

    def clean_approved_quantity(self):
        """Validate approved quantity against FacultyItemStock (faculty-isolated)."""
        approved_qty = self.cleaned_data.get("approved_quantity")
        order_qty = self.cleaned_data.get("order_quantity")
        item = self.cleaned_data.get("item")

        if not approved_qty or not item:
            return approved_qty

        # Resolve faculty
        faculty = self.faculty
        if not faculty and self.instance.pk and self.instance.transaction_id:
            faculty = (
                ItemTransactions.objects.filter(id=self.instance.transaction_id)
                .values_list("faculty_id", flat=True)
                .first()
            )

        if not faculty:
            raise forms.ValidationError("لا يمكن التحقق من المخزون: الكلية غير محددة")

        # Resolve sub_warehouse
        sub_warehouse = None
        if self.from_sub_warehouse_id:
            try:
                sub_warehouse = SubWarehouse.objects.get(id=self.from_sub_warehouse_id)
            except SubWarehouse.DoesNotExist:
                pass

        # DIRECT QUERY TO FacultyItemStock (Fast & Matches Admin Dashboard)
        stock_record = FacultyItemStock.objects.filter(
            item=item, faculty=faculty, sub_warehouse=sub_warehouse
        ).first()

        available_stock = stock_record.cached_quantity if stock_record else 0

        # Validation
        if approved_qty > available_stock:
            error_msg = (
                f'الصنف "{item.name}": الكمية المنصرفة ({approved_qty}) '
                f"تتجاوز الكمية المتاحة في المخزن ({available_stock})."
            )
            if sub_warehouse:
                error_msg += f" (المخزن: {sub_warehouse.name})"
            raise forms.ValidationError(error_msg)

        if order_qty and approved_qty > order_qty:
            raise forms.ValidationError(
                "الكمية المنصرفة لا يمكن أن تتجاوز الكمية المطلوبة"
            )

        return approved_qty

    def clean_price(self):
        """Validate custody price: non-negative, optional."""
        price = self.cleaned_data.get("price")
        if price is None:
            return None
        if price < 0:
            raise forms.ValidationError("سعر العهدة لا يمكن أن يكون سالباً")
        if price != round(price, 2):
            raise forms.ValidationError("يرجى إدخال السعر بمنزلتين عشريتين كحد أقصى")
        return price

    def clean(self):
        """Cross-field validation."""
        cleaned_data = super().clean()
        item = cleaned_data.get("item")
        price = cleaned_data.get("price")

        # Optional warning if price is 0 but item has historical price
        if item and price == 0:
            latest = item.itempricehistory_set.order_by("-date").first()
            if latest and latest.price > 0:
                if not hasattr(self, "_warnings"):
                    self._warnings = {}
                self._warnings["price"] = (
                    f"تنبيه: آخر سعر مسجل لهذا الصنف هو {latest.price:.2f} ج.م. هل تريد ترك سعر العهدة 0.00؟"
                )

        return cleaned_data

    @property
    def warnings(self):
        """Template-accessible warnings."""
        return getattr(self, "_warnings", {})


class ItemTransactionDetailsAdditionForm(forms.ModelForm):
    price = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        label="سعر الصنف",
        widget=forms.NumberInput(
            attrs={
                "class": "form-control form-control-sm",
                "placeholder": "سعر الصنف",
                "step": "0.01",
                "min": "0",
            }
        ),
    )

    class Meta:
        model = ItemTransactionDetails
        fields = ("id", "item", "approved_quantity", "status", "notes", "price")
        widgets = {
            "id": forms.HiddenInput(),
            "item": forms.HiddenInput(),
            "approved_quantity": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": "1"}
            ),
            "status": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control border-0 bg-transparent shadow-none",
                    "rows": 1,
                    "placeholder": "ملاحظات الصنف...",
                    "style": "resize: none; outline: none; font-size: 0.9rem;",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["approved_quantity"].required = True
        if not self.fields["price"].initial:
            self.fields["price"].initial = "0.00"


class ItemTransactionDetailsReturnForm(forms.ModelForm):
    class Meta:
        model = ItemTransactionDetails
        fields = ("id", "item", "approved_quantity", "status", "notes")
        widgets = {
            "id": forms.HiddenInput(),
            "item": forms.HiddenInput(),
            "approved_quantity": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": "1"}
            ),
            "status": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control border-0 bg-transparent shadow-none",
                    "rows": 1,
                    "placeholder": "ملاحظات الصنف...",
                    "style": "resize: none; outline: none; font-size: 0.9rem;",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["approved_quantity"].required = True


class ItemTransactionDetailsTransferForm(forms.ModelForm):
    class Meta:
        model = ItemTransactionDetails
        fields = ("item", "order_quantity", "approved_quantity", "status", "notes")
        widgets = {
            "item": forms.HiddenInput(),
            "order_quantity": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": "1"}
            ),
            "approved_quantity": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": "0"}
            ),
            "status": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control border-0 bg-transparent shadow-none",
                    "rows": 1,
                    "placeholder": "ملاحظات الصنف...",
                    "style": "resize: none; outline: none; font-size: 0.9rem;",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "from_user" in self.fields:
            self.fields["from_user"].required = False
            self.fields[
                "from_user"
            ].queryset = User.objects.all()  # Give it a full queryset for POST
        if "to_user" in self.fields:
            self.fields["to_user"].required = False
            self.fields["to_user"].queryset = User.objects.all()
        self.fields["approved_quantity"].required = False

    def clean_approved_quantity(self):
        qty = self.cleaned_data.get("approved_quantity")
        if qty is None:
            return 0
        if qty < 0:
            raise ValidationError("الكمية المنقولة لا يمكن أن تكون سالبة.")
        return qty


class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = [
            "name",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "اسم المخزن الرئيسي"}
            ),
        }


class ItemCategoryForm(forms.ModelForm):
    """Global item category — sub_warehouse removed (categories are now shared)."""

    class Meta:
        model = ItemCategory
        fields = [
            "name",
            "sub_warehouse",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "اسم الفئة"}
            ),
            "sub_warehouse": forms.Select(
                attrs={"class": "form-select", "placeholder": "المخزن الفرعي"}
            ),
        }


class FacultyAwareDisbursementFormSet(forms.BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        self.faculty = kwargs.pop("faculty", None)
        self.from_sub_warehouse_id = kwargs.pop("from_sub_warehouse_id", None)
        super().__init__(*args, **kwargs)

    def _construct_form(self, i, **kwargs):
        kwargs["faculty"] = self.faculty
        kwargs["from_sub_warehouse_id"] = self.from_sub_warehouse_id
        return super()._construct_form(i, **kwargs)


ItemTransactionDetailsDisbursementFormSet = inlineformset_factory(
    ItemTransactions,
    ItemTransactionDetails,
    form=ItemTransactionDetailsDisbursementForm,
    formset=FacultyAwareDisbursementFormSet,
    extra=1,
    can_delete=True,
    validate_max=True,
)


ItemTransactionDetailsDisbursementFormSet = inlineformset_factory(
    ItemTransactions,
    ItemTransactionDetails,
    form=ItemTransactionDetailsDisbursementForm,
    formset=FacultyAwareDisbursementFormSet,
    extra=1,
    can_delete=True,
    validate_max=True,
)


ItemTransactionDetailsFormSet = inlineformset_factory(
    ItemTransactions,
    ItemTransactionDetails,
    form=ItemTransactionDetailsDisbursementForm,
    fields=("item", "order_quantity", "approved_quantity", "status", "notes"),
    extra=1,
    can_delete=True,
)

ItemTransactionDetailsAdditionFormSet = inlineformset_factory(
    ItemTransactions,
    ItemTransactionDetails,
    form=ItemTransactionDetailsAdditionForm,
    fields=("item", "approved_quantity", "status", "notes", "price"),
    extra=1,
    can_delete=True,
)

ItemTransactionDetailsReturnFormSet = inlineformset_factory(
    ItemTransactions,
    ItemTransactionDetails,
    form=ItemTransactionDetailsReturnForm,
    fields=("item", "approved_quantity", "status", "notes"),
    extra=1,
    can_delete=True,
)

ItemTransactionDetailsTransferFormSet = inlineformset_factory(
    ItemTransactions,
    ItemTransactionDetails,
    form=ItemTransactionDetailsTransferForm,
    fields=("item", "order_quantity", "approved_quantity", "status", "notes"),
    extra=1,
    can_delete=True,
)


class SubWarehouseForm(forms.ModelForm):
    """Form for creating/editing sub-warehouses (faculty-scoped)"""

    class Meta:
        model = SubWarehouse
        fields = ["name", "warehouse"]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "اسم المخزن الفرعي",
                    "dir": "rtl",
                }
            ),
            "warehouse": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "name": "اسم المخزن الفرعي",
            "warehouse": "المخزن الرئيسي",
        }

    def __init__(self, *args, **kwargs):
        kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        # For superusers, show all options
        self.fields["warehouse"].queryset = Warehouse.objects.all()


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = [
            "name",
            "company_address",
            "company_phone",
            "company_email",
            "company_notes",
            "contact_name",
            "contact_address",
            "contact_phone",
            "contact_email",
            "contact_notes",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "اسم الشركة",
                    "dir": "rtl",
                }
            ),
            "company_address": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "عنوان الشركة",
                    "dir": "rtl",
                }
            ),
            "company_phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "هاتف الشركة",
                    "dir": "rtl",
                }
            ),
            "company_email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "بريد الشركة الإلكتروني"}
            ),
            "company_notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "placeholder": "ملاحظات الشركة",
                    "rows": 3,
                    "dir": "rtl",
                }
            ),
            "contact_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "اسم المندوب",
                    "dir": "rtl",
                }
            ),
            "contact_address": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "عنوان المندوب",
                    "dir": "rtl",
                }
            ),
            "contact_phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "هاتف المندوب",
                    "dir": "rtl",
                }
            ),
            "contact_email": forms.EmailInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "بريد المندوب الإلكتروني",
                }
            ),
            "contact_notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "placeholder": "ملاحظات المندوب",
                    "rows": 3,
                    "dir": "rtl",
                }
            ),
        }
