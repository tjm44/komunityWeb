from django.test import TestCase
from wallet.flutterwave import get_access_token, charge_voucher, initiate_transfer
import uuid

class FlutterwaveIntegrationTest(TestCase):
    def test_oauth_token_retrieval(self):
        try:
            token = get_access_token()
            self.assertIsNotNone(token)
            self.assertTrue(len(token) > 0)
            print("\n[SUCCESS] OAuth Token retrieved from Flutterwave Sandbox!")
        except Exception as e:
            self.fail(f"OAuth Token retrieval failed: {e}")

    def test_voucher_charge_graceful_fail(self):
        # We test with an invalid pin to make sure the endpoint receives our request
        # and returns a structured validation/auth response rather than crashing.
        ref = f"test-topup-{uuid.uuid4().hex[:8]}"
        res = charge_voucher(
            voucher_pin="9999999999999999",  # Mock invalid pin
            amount=100.00,
            email="test@komunity.com",
            phone_number="0821234567",
            tx_ref=ref
        )
        self.assertIn('success', res)
        print(f"\n[SUCCESS] Voucher charge response received: success={res['success']}")

from django.contrib.auth import get_user_model
from wallet.models import Wallet, Transaction
from wallet.webhooks import handle_charge_completed

User = get_user_model()

class WalletLedgerResilienceTest(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(email="user1@example.com", password="password123")
        self.user2 = User.objects.create_user(email="user2@example.com", password="password123")
        self.wallet1 = Wallet.objects.get(user=self.user1)
        self.wallet2 = Wallet.objects.get(user=self.user2)

    def test_denormalized_balance_and_webhook(self):
        self.assertEqual(self.wallet1.balance, 0.00)

        # Create pending deposit transaction
        tx_ref = "test-deposit-100"
        tx = Transaction.objects.create(
            wallet=self.wallet1,
            transaction_type=Transaction.TransactionType.TOP_UP,
            amount=100.00,
            status=Transaction.TransactionStatus.PENDING,
            idempotency_key=tx_ref
        )

        # Simulate webhook payload
        data = {
            'reference': tx_ref,
            'amount': 100.00,
            'status': 'successful',
            'id': 'flw-123456'
        }

        response = handle_charge_completed(data)
        self.assertEqual(response.status_code, 200)

        self.wallet1.refresh_from_db()
        tx.refresh_from_db()

        self.assertEqual(self.wallet1.balance, 100.00)
        self.assertEqual(tx.status, Transaction.TransactionStatus.COMPLETED)

        # Test Idempotency: Repeating webhook call shouldn't double credit
        response_repeat = handle_charge_completed(data)
        self.assertEqual(response_repeat.status_code, 200)

        self.wallet1.refresh_from_db()
        self.assertEqual(self.wallet1.balance, 100.00)
