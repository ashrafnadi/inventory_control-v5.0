# inventory/management/commands/generate_item_codes.py
import logging
import uuid

from django.core.management.base import BaseCommand

from inventory.models import Item

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Generate UUID codes for items without codes"

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Generate codes for ALL items (not just those without codes)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit the number of items to process",
        )

    def handle(self, *args, **options):
        generate_all = options.get("all", False)
        limit = options.get("limit")

        # Get items to process
        if generate_all:
            queryset = Item.objects.all()
            self.stdout.write(
                self.style.NOTICE(
                    "⚠️  Processing ALL items (including those with codes)"
                )
            )
        else:
            queryset = Item.objects.filter(code__isnull=True) | Item.objects.filter(
                code=""
            )
            self.stdout.write(
                self.style.NOTICE("ℹ️  Processing only items without codes")
            )

        if limit:
            queryset = queryset[:limit]

        total_count = queryset.count()
        self.stdout.write(
            self.style.SUCCESS(f"📦 Found {total_count} items to process\n")
        )

        updated_count = 0
        failed_count = 0
        skipped_count = 0

        for idx, item in enumerate(queryset.iterator(), start=1):
            try:
                # Skip if item already has a code (when using --all)
                if not generate_all and item.code:
                    skipped_count += 1
                    continue

                # Generate new code
                new_code = f"I-{uuid.uuid4().hex[:8].upper()}"

                # Check for uniqueness (rare but possible)
                max_attempts = 5
                attempts = 0
                while (
                    Item.objects.filter(code=new_code).exists()
                    and attempts < max_attempts
                ):
                    new_code = f"I-{uuid.uuid4().hex[:8].upper()}"
                    attempts += 1

                if attempts >= max_attempts:
                    raise Exception(
                        f"Could not generate unique code after {max_attempts} attempts"
                    )

                # Update item
                item.code = new_code
                item.save(update_fields=["code"])

                updated_count += 1

                # Show progress (every 10 items or last item)
                if idx % 10 == 0 or idx == total_count:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"✓ [{idx}/{total_count}] {item.name} → {item.code}"
                        )
                    )

            except Exception as e:
                failed_count += 1

                # Log error but continue processing
                error_msg = (
                    f"✗ [{idx}/{total_count}] {item.name} (ID: {item.id}) → {str(e)}"
                )
                self.stdout.write(self.style.ERROR(error_msg))
                logger.error(f"Failed to generate code for item {item.id}: {str(e)}")

                # Continue to next item (don't raise exception)
                continue

        # Print summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("📊 SUMMARY"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"✅ Successfully updated: {updated_count} items")

        if failed_count > 0:
            self.stdout.write(self.style.ERROR(f"❌ Failed: {failed_count} items"))

        if skipped_count > 0:
            self.stdout.write(self.style.WARNING(f"⚠️  Skipped: {skipped_count} items"))

        self.stdout.write(f"📦 Total processed: {total_count} items")
        self.stdout.write("=" * 60 + "\n")

        # Exit with error code if there were failures
        if failed_count > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"⚠️  Completed with {failed_count} error(s). Check logs for details."
                )
            )
