from __future__ import annotations

import pytest

from openclaw_tui.utils.time import relative_time


class TestRelativeTime:
    """Tests for relative time formatting."""

    @pytest.mark.parametrize(
        "delta_ms,expected",
        [
            # delta < 30s → "active"
            (0, "active"),
            (1, "active"),
            (10000, "active"),
            (29999, "active"),
            # 30s ≤ delta < 60s → "Xs ago"
            (30000, "active"),  # boundary: strictly < 30s
            (30001, "30s ago"),
            (45000, "45s ago"),
            (59999, "59s ago"),
            # 60s ≤ delta < 3600s → "Xm ago"
            (60000, "1m ago"),
            (120000, "2m ago"),
            (840000, "14m ago"),
            (3540000, "59m ago"),
            # 3600s ≤ delta < 86400s → "Xh ago"
            (3600000, "1h ago"),
            (7200000, "2h ago"),
            (10800000, "3h ago"),
            (82800000, "23h ago"),
            # delta ≥ 86400s → "Xd ago"
            (86400000, "1d ago"),
            (172800000, "2d ago"),
            (604800000, "7d ago"),
        ],
    )
    def test_various_deltas(self, delta_ms: int, expected: str):
        """Test various time deltas with expected outputs."""
        now_ms = 1000000  # arbitrary reference point
        result = relative_time(now_ms - delta_ms, now_ms)
        assert result == expected

    def test_future_time_returns_active(self):
        """When now_ms < updated_at_ms (future), should return 'active'."""
        now_ms = 1000000
        future_updated_at = 2000000  # in the future
        result = relative_time(future_updated_at, now_ms)
        assert result == "active"

    def test_boundary_30_seconds(self):
        """Exactly 30000ms should return 'active' (strictly < 30s)."""
        now_ms = 1000000
        result = relative_time(now_ms - 30000, now_ms)
        assert result == "active"

    def test_boundary_30001_ms(self):
        """Exactly 30001ms should return '30s ago'."""
        now_ms = 1000000
        result = relative_time(now_ms - 30001, now_ms)
        assert result == "30s ago"