# inventory/management/commands/fix_duplicate_item_names.py
import logging

from django.core.management.base import BaseCommand

from inventory.models import Item

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Find and fix duplicate item names by appending a unique number"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without making changes",
        )
        parser.add_argument(
            "--scope",
            choices=["global", "sub_warehouse"],
            default="global",
            help="Check duplicates globally (default) or within sub_warehouse",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        scope = options["scope"]

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting duplicate check (scope: {scope}, dry-run: {dry_run})"
            )
        )

        if scope == "global":
            self._fix_global_duplicates(dry_run)
        else:
            self._fix_sub_warehouse_duplicates(dry_run)

        self.stdout.write(self.style.SUCCESS("Done!"))

    def _fix_global_duplicates(self, dry_run):
        """Find items with duplicate names globally and fix them."""
        from django.db.models import Count

        # Find names that appear more than once
        duplicate_names = (
            Item.objects.values("name")
            .annotate(name_count=Count("id"))
            .filter(name_count__gt=1)
            .values_list("name", flat=True)
        )

        if not duplicate_names:
            self.stdout.write(
                self.style.SUCCESS("✓ No global duplicate item names found.")
            )
            return

        self.stdout.write(
            self.style.WARNING(f"Found {len(duplicate_names)} duplicate name(s):")
        )
        for name in duplicate_names:
            self.stdout.write(f"  - '{name}'")

        fixed_count = 0
        for name in duplicate_names:
            # Get all items with this name, ordered by ID (keep first as-is)
            items = Item.objects.filter(name=name).order_by("id")

            for idx, item in enumerate(items):
                if idx == 0:
                    # Keep the first occurrence unchanged
                    self.stdout.write(f"  ✓ Keeping: '{item.name}' (ID: {item.id})")
                    continue

                # Generate new unique name
                new_name = self._generate_unique_name(name, idx)

                if dry_run:
                    self.stdout.write(
                        f"  → Would update: ID {item.id} '{item.name}' → '{new_name}'"
                    )
                else:
                    try:
                        item.name = new_name
                        item.save(update_fields=["name"])
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  ✓ Updated: ID {item.id} '{item.name}' → '{new_name}'"
                            )
                        )
                        fixed_count += 1
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(
                                f"  ✗ Failed to update ID {item.id}: {str(e)}"
                            )
                        )

        if not dry_run:
            self.stdout.write(
                self.style.SUCCESS(f"\nFixed {fixed_count} duplicate item name(s).")
            )

    def _fix_sub_warehouse_duplicates(self, dry_run):
        """Find items with duplicate names within the same sub_warehouse."""
        from django.db.models import Count

        # Find (name, sub_warehouse) pairs that appear more than once
        duplicates = (
            Item.objects.values("name", "sub_warehouse_id")
            .annotate(count=Count("id"))
            .filter(count__gt=1)
        )

        if not duplicates:
            self.stdout.write(
                self.style.SUCCESS(
                    "✓ No duplicate item names within sub_warehouses found."
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"Found {len(duplicates)} duplicate(s) within sub_warehouse(s):"
            )
        )

        fixed_count = 0
        for dup in duplicates:
            name = dup["name"]
            sub_wh_id = dup["sub_warehouse_id"]

            items = Item.objects.filter(name=name, sub_warehouse_id=sub_wh_id).order_by(
                "id"
            )

            for idx, item in enumerate(items):
                if idx == 0:
                    self.stdout.write(
                        f"  ✓ Keeping: '{item.name}' @ SubWarehouse {sub_wh_id} (ID: {item.id})"
                    )
                    continue

                new_name = self._generate_unique_name(name, idx)

                if dry_run:
                    self.stdout.write(
                        f"  → Would update: ID {item.id} '{item.name}' → '{new_name}'"
                    )
                else:
                    try:
                        item.name = new_name
                        item.save(update_fields=["name"])
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  ✓ Updated: ID {item.id} '{item.name}' → '{new_name}'"
                            )
                        )
                        fixed_count += 1
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(
                                f"  ✗ Failed to update ID {item.id}: {str(e)}"
                            )
                        )

        if not dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nFixed {fixed_count} duplicate item name(s) within sub_warehouses."
                )
            )

    def _generate_unique_name(self, base_name, counter, max_attempts=1000):
        """Generate a unique name by appending -1, -2, etc."""
        for i in range(1, max_attempts + 1):
            candidate = f"{base_name}-{i}"
            # Check if this name already exists globally
            if not Item.objects.filter(name=candidate).exists():
                return candidate
        # Fallback: use UUID if we can't find a unique name
        import uuid

        return f"{base_name}-{uuid.uuid4().hex[:8]}"
