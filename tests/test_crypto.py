import importlib

import pytest


def _reload_crypto(monkeypatch, key):
    if key is None:
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    else:
        monkeypatch.setenv("ENCRYPTION_KEY", key)
    import crypto
    return importlib.reload(crypto)


def test_round_trip(monkeypatch):
    from cryptography.fernet import Fernet
    crypto = _reload_crypto(monkeypatch, Fernet.generate_key().decode())
    token = "pk_12345_SECRETTOKEN"
    enc = crypto.encrypt(token)
    assert enc != token
    assert crypto.decrypt(enc) == token


def test_missing_key_raises(monkeypatch):
    crypto = _reload_crypto(monkeypatch, None)
    with pytest.raises(RuntimeError):
        crypto.encrypt("anything")


def test_generate_key_is_usable(monkeypatch):
    crypto = _reload_crypto(monkeypatch, None)
    key = crypto.generate_key()
    crypto2 = _reload_crypto(monkeypatch, key)
    assert crypto2.decrypt(crypto2.encrypt("x")) == "x"
