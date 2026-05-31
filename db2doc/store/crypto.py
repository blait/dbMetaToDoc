"""Symmetric encryption for target DB passwords (Fernet).

Master key from env DB2DOC_SECRET_KEY, else from a 0600 file, else generated
and persisted on first use.  Never store plaintext passwords in the metastore.
"""
import os
from cryptography.fernet import Fernet
from .. import config


def _load_or_create_key():
    if config.SECRET_KEY:
        return config.SECRET_KEY.encode()
    path = config.SECRET_KEY_FILE
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read().strip()
    # generate + persist (0600)
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
    if plaintext is None:
        plaintext = ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token):
    if not token:
        return ""
    return _fernet().decrypt(token.encode()).decode()
