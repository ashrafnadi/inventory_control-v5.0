from django.contrib.auth.models import User
from django.test import TestCase

from administration.models import Department, Faculty, UserProfile
from inventory.models import (
    FacultyItemStock,
    Item,
    ItemCategory,
    SubWarehouse,
    Warehouse,
)


class SharedCatalogIsolationTests(TestCase):
    def setUp(self):
        self.faculty_a = Faculty.objects.create(name="Faculty A")
        self.faculty_b = Faculty.objects.create(name="Faculty B")
        self.department_a = Department.objects.create(
            name="Dept A", faculty=self.faculty_a
        )
        self.department_b = Department.objects.create(
            name="Dept B", faculty=self.faculty_b
        )

        self.user_a = User.objects.create_user(username="a", password="x")
        UserProfile.objects.filter(user=self.user_a).update(
            faculty=self.faculty_a,
            department=self.department_a,
            is_inventory_manager=True,
        )
        self.user_a.refresh_from_db()

        self.warehouse = Warehouse.objects.create(name="Central")
        self.sub_warehouse = SubWarehouse.objects.create(
            name="Shared Lab", warehouse=self.warehouse
        )
        self.category = ItemCategory.objects.create(name="Devices")
        self.category.sub_warehouse.add(self.sub_warehouse)
        self.item = Item.objects.create(
            code="ITEM-1",
            name="Microscope",
            sub_warehouse=self.sub_warehouse,
            warehouse=self.warehouse,
            category=self.category,
            limit_quantity=2,
            unit="Q",
        )

    def test_item_catalog_is_shared(self):
        self.assertEqual(Item.objects.filter(name="Microscope").count(), 1)
        self.assertEqual(SubWarehouse.objects.filter(name="Shared Lab").count(), 1)
        self.assertEqual(ItemCategory.objects.filter(name="Devices").count(), 1)

    def test_faculty_item_stock_is_isolated(self):
        FacultyItemStock.objects.create(
            faculty=self.faculty_a,
            item=self.item,
            sub_warehouse=self.sub_warehouse,
            cached_quantity=5,
            limit_quantity=2,
        )
        FacultyItemStock.objects.create(
            faculty=self.faculty_b,
            item=self.item,
            sub_warehouse=self.sub_warehouse,
            cached_quantity=9,
            limit_quantity=2,
        )

        self.assertEqual(
            FacultyItemStock.objects.get(
                faculty=self.faculty_a, item=self.item
            ).cached_quantity,
            5,
        )
        self.assertEqual(
            FacultyItemStock.objects.get(
                faculty=self.faculty_b, item=self.item
            ).cached_quantity,
            9,
        )
