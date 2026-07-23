from django.core.management.base import BaseCommand
from wallet.models import Wallet

class Command(BaseCommand):
    help = "Reconciles denormalized wallet balances against the sum of completed transaction records."

    def handle(self, *args, **options):
        wallets = Wallet.objects.all()
        reconciled = 0
        discrepancies = 0

        self.stdout.write(f"Starting reconciliation check for {wallets.count()} wallets...")

        for wallet in wallets:
            old_balance = wallet.balance
            new_balance = wallet.recalculate_balance()
            if old_balance != new_balance:
                discrepancies += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"[FIXED] Wallet ID {wallet.id} ({wallet.user}): "
                        f"Old={old_balance}, Recalculated={new_balance}"
                    )
                )
            else:
                reconciled += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Reconciliation complete! Matched: {reconciled}, Fixed Discrepancies: {discrepancies}"
            )
        )
