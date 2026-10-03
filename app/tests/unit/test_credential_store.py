"""Tests unitarios del credential store (credenciales admin inyectado).

El token ENC NUNCA se devuelve por ninguna API: solo `token_configured`.
Todos los tests usan un directorio TEMP como project root: nunca tocan
el .env real del proyecto.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import credential_store

_VALID_TOKEN = "ENC SH2l0bGFtcGhvbmUxMjM0NTY3ODk="


class CredentialStoreTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="credstore_test_")
        self.env_path = os.path.join(self.tmp, ".env")
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for name in ("FORTIGATE_ADMIN_USER", "FORTIGATE_ADMIN_PASSWORD_ENC"):
            os.environ.pop(name, None)
        # El .env vive en TEMP; se elimina al cerrar el test
        try:
            os.remove(self.env_path)
        except OSError:
            pass


class TestLoadCredentials(CredentialStoreTestBase):
    def test_load_missing_env_returns_defaults(self):
        creds = credential_store.load_credentials(self.tmp)
        self.assertEqual(creds, {"user": "claro", "token_configured": False})

    def test_load_empty_token_not_configured(self):
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write("FORTIGATE_ADMIN_USER=bak\nFORTIGATE_ADMIN_PASSWORD_ENC=\n")
        creds = credential_store.load_credentials(self.tmp)
        self.assertEqual(creds, {"user": "bak", "token_configured": False})

    def test_load_never_returns_token_value(self):
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write(f"FORTIGATE_ADMIN_PASSWORD_ENC={_VALID_TOKEN}\n")
        creds = credential_store.load_credentials(self.tmp)
        self.assertTrue(creds["token_configured"])
        self.assertNotIn(_VALID_TOKEN, str(creds))


class TestSaveCredentials(CredentialStoreTestBase):
    def test_round_trip_save_and_load(self):
        creds = credential_store.save_credentials(self.tmp, "bak-admin", _VALID_TOKEN)
        self.assertEqual(creds, {"user": "bak-admin", "token_configured": True})
        self.assertNotIn(_VALID_TOKEN, str(creds))
        reloaded = credential_store.load_credentials(self.tmp)
        self.assertEqual(reloaded, {"user": "bak-admin", "token_configured": True})
        self.assertTrue(os.path.exists(self.env_path))

    def test_save_updates_environ_for_running_process(self):
        credential_store.save_credentials(self.tmp, "bak-admin", _VALID_TOKEN)
        self.assertEqual(os.environ.get("FORTIGATE_ADMIN_USER"), "bak-admin")
        self.assertEqual(os.environ.get("FORTIGATE_ADMIN_PASSWORD_ENC"), _VALID_TOKEN)

    def test_invalid_token_raises(self):
        for bad in ("D34db33f", "ENC ", "ENC con espacios!!", "enc AAAA=="):
            with self.assertRaises(ValueError):
                credential_store.save_credentials(self.tmp, "u", bad)
        self.assertFalse(os.path.exists(self.env_path))

    def test_empty_user_raises(self):
        for bad in ("", "   "):
            with self.assertRaises(ValueError):
                credential_store.save_credentials(self.tmp, bad, _VALID_TOKEN)
        self.assertFalse(os.path.exists(self.env_path))

    def test_missing_token_field_raises(self):
        with self.assertRaises(ValueError):
            credential_store.save_credentials(self.tmp, "u", None)
        self.assertFalse(os.path.exists(self.env_path))

    def test_save_preserves_other_lines_and_order(self):
        original = (
            "# comentario general\n"
            "TELEGRAM_BOT_TOKEN=12345:dummy\n"
            "TELEGRAM_CHAT_ID=-100200\n"
        )
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write(original)
        credential_store.save_credentials(self.tmp, "bak", _VALID_TOKEN)
        with open(self.env_path, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.splitlines()
        self.assertEqual(lines[0], "# comentario general")
        self.assertEqual(lines[1], "TELEGRAM_BOT_TOKEN=12345:dummy")
        self.assertEqual(lines[2], "TELEGRAM_CHAT_ID=-100200")
        self.assertIn("FORTIGATE_ADMIN_PASSWORD_ENC=" + _VALID_TOKEN, lines)
        self.assertIn("FORTIGATE_ADMIN_USER=bak", lines)
        self.assertNotIn(_VALID_TOKEN, content.split("TELEGRAM")[0])

    def test_save_updates_existing_key_without_duplicates(self):
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write(
                "TELEGRAM_CHAT_ID=-1\n"
                "FORTIGATE_ADMIN_USER=viejo\n"
                "FORTIGATE_ADMIN_PASSWORD_ENC=ENC VIEJO123=\n"
            )
        credential_store.save_credentials(self.tmp, "nuevo", "ENC NUEVO456=")
        with open(self.env_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content.count("FORTIGATE_ADMIN_USER="), 1)
        self.assertEqual(content.count("FORTIGATE_ADMIN_PASSWORD_ENC="), 1)
        self.assertIn("FORTIGATE_ADMIN_USER=nuevo", content)
        self.assertIn("ENC NUEVO456=", content)
        self.assertNotIn("ENC VIEJO123=", content)
        self.assertIn("TELEGRAM_CHAT_ID=-1", content)

    def test_user_value_is_stripped(self):
        creds = credential_store.save_credentials(self.tmp, "  bak  ", _VALID_TOKEN)
        self.assertEqual(creds["user"], "bak")
        with open(self.env_path, "r", encoding="utf-8") as f:
            self.assertIn("FORTIGATE_ADMIN_USER=bak", f.read())


if __name__ == "__main__":
    unittest.main()
