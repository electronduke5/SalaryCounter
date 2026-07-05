import os
import sys

from cryptography.fernet import Fernet

_KEY_ENV = "ENCRYPTION_KEY"

_INSTRUCTIONS = (
    f"{_KEY_ENV} is not set or invalid. Generate one with:\n"
    "    python crypto.py genkey\n"
    f"then add it to your .env as {_KEY_ENV}=<value>."
)


def get_fernet() -> Fernet:
    key = os.environ.get(_KEY_ENV)
    if not key:
        raise RuntimeError(_INSTRUCTIONS)
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise RuntimeError(_INSTRUCTIONS) from exc


def encrypt(plaintext: str) -> str:
    return get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return get_fernet().decrypt(token.encode()).decode()


def generate_key() -> str:
    return Fernet.generate_key().decode()


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "genkey":
        print(generate_key())
    else:
        print("usage: python crypto.py genkey")
        sys.exit(1)
