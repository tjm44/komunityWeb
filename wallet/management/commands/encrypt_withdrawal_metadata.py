"""
Management command: encrypt_withdrawal_metadata
===============================================
One-time migration to encrypt plaintext bank account numbers and mobile-money
phone numbers that are already stored in Transaction.withdrawal_metadata rows.

Usage:
    python manage.py encrypt_withdrawal_metadata          # dry-run (no DB writes)
    python manage.py encrypt_withdrawal_metadata --apply  # encrypt in-place

This command is idempotent: already-encrypted values (starting with 'gAAAAA')
are skipped so it is safe to re-run.
"""

from django.core.management.base import BaseCommand
from wallet.models import Transaction
from wallet.encryption import encrypt_metadata, is_encrypted, SENSITIVE_METADATA_KEYS


class Command(BaseCommand):
    help = "Encrypt plaintext sensitive fields in Transaction.withdrawal_metadata"

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Write encrypted values to the database (default is dry-run).',
        )

    def handle(self, *args, **options):
        apply = options['apply']
        mode = "APPLY" if apply else "DRY-RUN"
        self.stdout.write(self.style.WARNING(f"[{mode}] Starting withdrawal_metadata encryption pass..."))

        qs = Transaction.objects.exclude(withdrawal_metadata__isnull=True)
        total = qs.count()
        updated = 0
        skipped = 0

        for tx in qs.iterator():
            meta = tx.withdrawal_metadata
            if not isinstance(meta, dict):
                continue

            needs_encryption = False
            for key in SENSITIVE_METADATA_KEYS:
                value = meta.get(key)
                if value and not is_encrypted(str(value)):
                    needs_encryption = True
                    break

            if not needs_encryption:
                skipped += 1
                continue

            encrypted_meta = encrypt_metadata(meta)

            if apply:
                Transaction.objects.filter(pk=tx.pk).update(withdrawal_metadata=encrypted_meta)
                updated += 1
                self.stdout.write(f"  Encrypted Transaction #{tx.id}")
            else:
                updated += 1
                self.stdout.write(f"  [DRY-RUN] Would encrypt Transaction #{tx.id}: {list(meta.keys())}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"[{mode}] Done. {total} rows scanned, {updated} encrypted, {skipped} already-encrypted/skipped."
        ))
        if not apply:
            self.stdout.write(self.style.WARNING(
                "Re-run with --apply to write changes to the database."
            ))
