"""Symmetric encryption for target-DB passwords (Fernet).

Master key: env V2_SECRET_KEY, else a 0600 key file (V2_SECRET_KEY_FILE,
default <repo>/secrets/master.key — shared with v1), generated on first use.
Plaintext passwords are never stored in the metastore.
"""
import os

from cryptography.fernet import Fernet

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


def _key_path():
    return (os.environ.get("V2_SECRET_KEY_FILE")
            or os.environ.get("DB2DOC_SECRET_KEY_FILE")
            or os.path.join(_REPO, "secrets", "master.key"))


def _load_or_create_key():
    env = os.environ.get("V2_SECRET_KEY")
    if env:
        return env.encode()
    path = _key_path()
    if not os.path.isabs(path):
        path = os.path.join(_REPO, path)
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read().strip()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    key = Fernet.generate_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


_FERNET = None


def _fernet():
    global _FERNET
    if _FERNET is None:
        _FERNET = Fernet(_load_or_create_key())
    return _FERNET


def encrypt(plaintext):
    return _fernet().encrypt((plaintext or "").encode()).decode()


def decrypt(token):
    if not token:
        return ""
    return _fernet().decrypt(token.encode()).decode()
