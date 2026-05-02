# inventory/management/commands/recalculate_cached_quantities.py
"""
Legacy command — delegates to recalculate_faculty_stocks.
"""

from django.core.management.base import BaseCommand
from inventory.models import FacultyItemStock


class Command(BaseCommand):
    help = "Recalculate FacultyItemStock cached quantities (legacy alias)"

    def handle(self, *args, **options):
        self.stdout.write("Recalculating all FacultyItemStock quantities...")
        updated = FacultyItemStock.batch_recalculate()
        self.stdout.write(
            self.style.SUCCESS(f"Done. Updated {updated} stock record(s).")
        )
