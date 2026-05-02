# inventory/management/commands/create_faculty_stocks.py
from django.core.management.base import BaseCommand

from inventory.models import FacultyItemStock, Item


class Command(BaseCommand):
    help = "Create FacultyItemStock records for all items"

    def handle(self, *args, **options):
        created = 0
        for item in Item.objects.all():
            if item.sub_warehouse and item.sub_warehouse.faculty:
                stock, created_flag = FacultyItemStock.objects.get_or_create(
                    item=item,
                    sub_warehouse=item.sub_warehouse,
                    faculty=item.sub_warehouse.faculty,
                    defaults={"cached_quantity": item.cached_quantity},
                )
                if created_flag:
                    created += 1
                    self.stdout.write(f"✓ Created stock for {item.name}")

        self.stdout.write(
            self.style.SUCCESS(f"\n✅ Created {created} FacultyItemStock records")
        )
