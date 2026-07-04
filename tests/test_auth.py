import hashlib
import hmac
import json
import time
from typing import Optional
from urllib.parse import urlencode

import pytest

from api import validate_init_data

BOT_TOKEN = "123456:TEST-TOKEN"


def build_init_data(bot_token: str = BOT_TOKEN, auth_date: Optional[int] = None, user_id: int = 42) -> str:
    if auth_date is None:
        auth_date = int(time.time())
    fields = {
        "auth_date": str(auth_date),
        "query_id": "AAErCzMRAAAAACsLMxG5TDPu",
        "user": json.dumps({"id": user_id, "first_name": "Test", "username": "test"}),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_valid_init_data():
    user = validate_init_data(build_init_data(), BOT_TOKEN)
    assert user is not None
    assert user["id"] == 42


def test_tampered_hash_rejected():
    init_data = build_init_data() + "x"
    assert validate_init_data(init_data, BOT_TOKEN) is None


def test_wrong_token_rejected():
    init_data = build_init_data(bot_token="999:OTHER-TOKEN")
    assert validate_init_data(init_data, BOT_TOKEN) is None


def test_stale_auth_date_rejected():
    two_days_ago = int(time.time()) - 2 * 24 * 60 * 60
    init_data = build_init_data(auth_date=two_days_ago)
    assert validate_init_data(init_data, BOT_TOKEN) is None


def test_empty_init_data_rejected():
    assert validate_init_data("", BOT_TOKEN) is None
