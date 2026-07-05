import main


SETTINGS = {
    "notify_daily_digest": 1, "digest_time": "21:00", "notify_weekly": 0,
    "notify_long_timer": 1, "long_timer_hours": 4, "autosync_enabled": 1,
}


def test_build_notifications_view_text_and_buttons():
    text, kb = main.build_notifications_view(SETTINGS)
    assert "21:00" in text
    flat = [b for row in kb.inline_keyboard for b in row]
    callbacks = {b.callback_data for b in flat}
    assert {"notif_toggle_daily", "notif_toggle_weekly", "notif_toggle_timer",
            "notif_toggle_autosync", "notif_digest_time"} <= callbacks
    by_cb = {b.callback_data: b.text for b in flat}
    assert "✅" in by_cb["notif_toggle_daily"]      # включено
    assert "❌" in by_cb["notif_toggle_weekly"]     # выключено


def test_notif_toggle_field_map():
    assert main.NOTIF_TOGGLE_FIELDS["daily"] == "notify_daily_digest"
    assert main.NOTIF_TOGGLE_FIELDS["weekly"] == "notify_weekly"
    assert main.NOTIF_TOGGLE_FIELDS["timer"] == "notify_long_timer"
    assert main.NOTIF_TOGGLE_FIELDS["autosync"] == "autosync_enabled"


def test_valid_hhmm():
    assert main.valid_hhmm("21:00") is True
    assert main.valid_hhmm("9:05") is True
    assert main.valid_hhmm("24:00") is False
    assert main.valid_hhmm("21:60") is False
    assert main.valid_hhmm("2100") is False
    assert main.valid_hhmm("ab:cd") is False
