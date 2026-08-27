"""
Encryption utilities for storing sensitive credentials in the database.
Uses Fernet (symmetric encryption) with key management.
"""

from cryptography.fernet import Fernet
import os

_KEY_ENV_VAR = "JIRA_ENCRYPTION_KEY"
_KEY_FILE = os.path.join(os.path.dirname(__file__), ".encryption_key")


def _get_or_generate_key() -> bytes:
    """Load encryption key from env or generate/store one."""
    key_env = os.environ.get(_KEY_ENV_VAR)
    if key_env:
        key = key_env.encode()
        # Validate it's a proper Fernet key
        try:
            Fernet(key)
            return key
        except Exception:
            raise ValueError(
                f"Invalid JIRA_ENCRYPTION_KEY from environment. "
                "Must be a 32-byte base64 key. Generate one with: "
                "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )

    # Try reading from a local file (dev-only; not for production)
    if os.path.exists(_KEY_FILE):
        with open(_KEY_FILE, "rb") as f:
            key = f.read()
        try:
            Fernet(key)
            return key
        except Exception:
            os.remove(_KEY_FILE)

    # Generate a new key and save it (development convenience)
    key = Fernet.generate_key()
    with open(_KEY_FILE, "wb") as f:
        f.write(key)
    return key


_KEY = _get_or_generate_key()
_fernet = Fernet(_KEY)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string value and return base64-encoded ciphertext."""
    return _fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext and return the plaintext."""
    return _fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def get_encryption_key() -> str:
    """Return the base64 encryption key (for display/reference only)."""
    return _KEY.decode("utf-8")
