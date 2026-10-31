from datetime import datetime, timezone

import pytest

from ascend_agents.compliance import (
    contact_block_reason,
    in_calling_window,
    line_type_hold_reason,
    mask_phone,
    normalize_phone,
)
from ascend_agents.config import load_campaign

from .conftest import IN_HOURS, WEEKEND


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("(602) 555-0143", "+16025550143"),
        ("+1 602-555-0143", "+16025550143"),
        ("1.602.555.0143", "+16025550143"),
        ("602555014", None),          # too short
        ("+44 20 7946 0958", None),   # not NANP
        ("(102) 555-0143", None),     # invalid area code
        ("", None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_mask_phone_hides_digits():
    assert mask_phone("+16025550143") == "+1******0143"


def test_calling_window_respects_local_time_and_weekdays():
    window = load_campaign().calling
    assert in_calling_window(window, "America/Phoenix", IN_HOURS)       # 11:00 local
    assert not in_calling_window(window, "America/Phoenix", WEEKEND)    # Sunday
    early = datetime(2026, 11, 3, 13, 0, tzinfo=timezone.utc)           # 06:00 Phoenix
    assert not in_calling_window(window, "America/Phoenix", early)
    assert in_calling_window(window, "America/New_York", early) is False  # 08:00 NY, before 09:30


def test_mobile_and_unverified_lines_are_held_by_default():
    window = load_campaign().calling
    assert line_type_hold_reason("landline", window) == ""
    assert line_type_hold_reason("fixedVoip", window) == ""
    assert "mobile" in line_type_hold_reason("mobile", window)
    assert "unverified" in line_type_hold_reason("", window)


def test_contact_block_reasons():
    none = frozenset()
    assert contact_block_reason({"dnd": True}, none)
    assert contact_block_reason({"dndSettings": {"Call": {"status": "active"}}}, none)
    assert contact_block_reason({"tags": ["ASCEND-DNC"]}, none)
    assert contact_block_reason({"phone": "(602) 555-0143"}, frozenset({"+16025550143"}))
    assert contact_block_reason({"phone": "+16025550143", "tags": ["ascend-prospect"]}, none) == ""


def test_config_rejects_window_outside_tcpa_hours(tmp_path):
    from ascend_agents.config import DEFAULT_CAMPAIGN

    text = DEFAULT_CAMPAIGN.read_text().replace('end: "16:30"', 'end: "21:30"')
    bad = tmp_path / "c.yaml"
    bad.write_text(text)
    with pytest.raises(ValueError):
        load_campaign(bad)
