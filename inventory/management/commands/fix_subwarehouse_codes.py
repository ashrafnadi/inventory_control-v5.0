# inventory/management/commands/fix_subwarehouse_codes.py
"""
Management command to backfill clean alphanumeric codes for existing SubWarehouse records.
Safe to run multiple times. Uses bulk updates for performance.
"""

import re
import unicodedata

from django.core.management.base import BaseCommand
from django.db.models import Q

from inventory.models import SubWarehouse


class Command(BaseCommand):
    help = "Generate clean alphanumeric codes for SubWarehouse records with empty/null codes"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making database changes",
        )

    def _generate_clean_code(self, name, obj_id):
        """Generate a predictable, unique alphanumeric code from Arabic/English name."""
        # Extended Arabic-to-Latin mapping for inventory contexts
        arabic_to_latin = {
            "م": "M",
            "خ": "KH",
            "ز": "Z",
            "ن": "N",
            "ك": "K",
            "ي": "Y",
            "ا": "A",
            "أ": "A",
            "إ": "E",
            "آ": "A",
            "ء": "",
            "ف": "F",
            "ح": "H",
            "س": "S",
            "ب": "B",
            "ط": "T",
            "ع": "A",
            "ر": "R",
            "ض": "D",
            "د": "D",
            "ة": "H",
            "ل": "L",
            "غ": "GH",
            "ت": "T",
            "ه": "H",
            "و": "W",
            "ى": "Y",
            "ث": "TH",
            "ج": "J",
            "ش": "SH",
            "ص": "S",
            "ظ": "DH",
            "ق": "Q",
            "ذ": "DH",
            "ؤ": "W",
            "ئ": "E",
            "ـ": "",
            "،": "",
            "؛": "",
            ".": "",
            "!": "",
            "?": "",
            "(": "",
            ")": "",
        }

        # Normalize Unicode and remove diacritics
        name = unicodedata.normalize("NFKD", name)
        name = "".join(c for c in name if not unicodedata.combining(c))

        # Extract first 3 meaningful characters
        clean_chars = []
        for char in name:
            if char.isspace():
                continue
            mapped = arabic_to_latin.get(char, char.upper())
            if mapped.isalnum():
                clean_chars.append(mapped)
            if len("".join(clean_chars)) >= 3:
                break

        # Build base code
        base_code = "".join(clean_chars).upper()

        # Guarantee uniqueness by appending zero-padded ID
        # Format: PREFIX + ID (e.g., "MKN001", "STR012")
        code = f"{base_code}{obj_id:03d}" if base_code else f"WH{obj_id:03d}"

        # Final sanitization: keep only alphanumeric, max 10 chars
        code = re.sub(r"[^A-Z0-9]", "", code)[:10]
        return code

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # Find records with null or empty codes
        qs = SubWarehouse.objects.filter(Q(code__isnull=True) | Q(code=""))
        to_update = list(qs)

        if not to_update:
            self.stdout.write(
                self.style.SUCCESS("✅ All sub-warehouses already have codes.")
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"🔍 Found {len(to_update)} sub-warehouses without codes."
            )
        )
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "🛑 DRY RUN MODE - No database changes will be made.\n"
                )
            )

        updated_records = []
        for sw in to_update:
            old_code = sw.code or "None"
            new_code = self._generate_clean_code(sw.name, sw.id)

            if old_code != new_code:
                sw.code = new_code
                updated_records.append(sw)
                self.stdout.write(f"  📝 {sw.name:<25} → {old_code:<8} | {new_code}")

        if updated_records:
            if dry_run:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"\n📊 Would update {len(updated_records)} sub-warehouses."
                    )
                )
            else:
                # BULK UPDATE for performance (1 query instead of N)
                SubWarehouse.objects.bulk_update(updated_records, ["code"])
                self.stdout.write(
                    self.style.SUCCESS(
                        f"\n✅ Successfully updated {len(updated_records)} sub-warehouses."
                    )
                )
        else:
            self.stdout.write(self.style.SUCCESS("\n✅ No codes needed regeneration."))
