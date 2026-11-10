import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import provision_firebase_user


class ProvisionFirebaseUserTests(unittest.TestCase):
    def setUp(self):
        self.user_ref = Mock()
        self.users_collection = Mock()
        self.users_collection.stream.return_value = []
        self.users_collection.document.return_value = self.user_ref
        self.db = Mock()
        self.db.collection.return_value = self.users_collection
        self.auth_user = SimpleNamespace(uid="auth-uid", custom_claims=None)
        self.auth = Mock()
        self.auth.get_user_by_email.return_value = self.auth_user
        self.production_settings = SimpleNamespace(use_emulators=False)

    def test_links_existing_auth_account_to_firestore_and_role_claims(self):
        with (
            patch.object(provision_firebase_user.firebase_config, "settings",
                         return_value=self.production_settings),
            patch.object(provision_firebase_user.firebase_config, "auth_client",
                         return_value=self.auth),
            patch.object(provision_firebase_user.firebase_config, "firestore_client",
                         return_value=self.db),
        ):
            provision_firebase_user.provision_user(
                "Admin@Example.com", "admin-user", "admin"
            )

        self.auth.get_user_by_email.assert_called_once_with("admin@example.com")
        self.user_ref.create.assert_called_once()
        record = self.user_ref.create.call_args.args[0]
        self.assertEqual(record["email"], "admin@example.com")
        self.assertEqual(record["role"], "admin")
        self.assertEqual(record["uid"], "auth-uid")
        self.assertNotIn("password", record)
        self.auth.set_custom_user_claims.assert_called_once()
        claims = self.auth.set_custom_user_claims.call_args.args[1]
        self.assertEqual(claims["role"], "admin")
        self.assertEqual(claims["accountId"], record["id"])

    def test_refuses_to_provision_against_emulators(self):
        with patch.object(
            provision_firebase_user.firebase_config,
            "settings",
            return_value=SimpleNamespace(use_emulators=True),
        ):
            with self.assertRaisesRegex(ValueError, "emulator mode is enabled"):
                provision_firebase_user.provision_user(
                    "admin@example.com", "admin-user", "admin"
                )

        self.auth.get_user_by_email.assert_not_called()


if __name__ == "__main__":
    unittest.main()
