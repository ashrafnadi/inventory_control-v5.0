# inventory/management/commands/run_all_scripts_from_migrations.py
from datetime import datetime

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run all synchronization and maintenance scripts in order"

    def add_arguments(self, parser):
        parser.add_argument("--faculty", type=int, help="Target faculty ID")
        parser.add_argument(
            "--dry-run", action="store_true", help="Run in dry-run mode only"
        )
        parser.add_argument(
            "--stop-on-error", action="store_true", help="Stop execution on first error"
        )

    def handle(self, *args, **options):
        faculty = options.get("faculty")
        dry_run = options.get("dry_run", False)
        stop_on_error = options.get("stop_on_error", False)

        self.stdout.write(
            f"\n🕒 Execution started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.stdout.write(
            self.style.SUCCESS("🚀 Running all synchronization scripts...\n")
        )

        # 🔧 Define the scripts to run in order
        commands = [
            {
                "name": "makemigrations",
                "kwargs": {},
            },
            {
                "name": "migrate",
                "kwargs": {},
            },
            {
                "name": "fix_transaction_document_numbers",
                "kwargs": {},
            },
            {
                "name": "sync_category_subwarehouse",
                "kwargs": {},
            },
            {
                "name": "populate_faculty_item_stock",
                "kwargs": {},
            },
            {
                "name": "fix_cached_quantities",
                "kwargs": {"faculty": faculty, "dry_run": dry_run},
            },
            {
                "name": "verify_stock_quantities",
                "kwargs": {"faculty": faculty},
            },
            {
                "name": "sync_faculty_stocks",
                "kwargs": {"faculty": faculty, "dry_run": dry_run},
            },
            {
                "name": "fix_all_quantities",
                "kwargs": {"faculty": faculty, "dry_run": dry_run},
            },
        ]

        success_count = 0
        failed = []

        for cmd in commands:
            cmd_name = cmd["name"]
            self.stdout.write(f"\n{'=' * 60}")
            self.stdout.write(self.style.SUCCESS(f"▶️  Running: {cmd_name}"))
            self.stdout.write(f"{'=' * 60}")

            try:
                # ✅ Call the command with the appropriate kwargs only
                call_command(cmd_name, **cmd.get("kwargs", {}))
                success_count += 1
            except Exception as e:
                failed.append({"name": cmd_name, "error": str(e)})
                self.stdout.write(
                    self.style.ERROR(f"❌ Failed: {cmd_name}\n   Error: {e}")
                )
                if stop_on_error:
                    self.stdout.write(
                        self.style.WARNING("\n🛑 Stopped (--stop-on-error enabled)")
                    )
                    break

        # 📊 الملخص النهائي
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(self.style.SUCCESS("✅ Execution completed successfully!"))
        self.stdout.write(f"📈 نجح: {success_count}/{len(commands)}")
        if failed:
            self.stdout.write(self.style.ERROR(f"💥 Failed: {len(failed)}"))
            for f in failed:
                self.stdout.write(f"   • {f['name']}: {f['error']}")
        self.stdout.write(
            f"🕒 Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.stdout.write(f"{'=' * 60}\n")
