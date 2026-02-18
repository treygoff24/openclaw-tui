def relative_time(updated_at_ms: int, now_ms: int) -> str:
    """Format relative time. < 30s = 'active', else '5s/14m/3h/2d ago'."""
    # Handle future times
    if now_ms < updated_at_ms:
        return "active"

    delta_ms = now_ms - updated_at_ms
    delta_seconds = delta_ms / 1000

    # 30 seconds or less → "active"
    if delta_seconds <= 30:
        return "active"

    # 30s to < 60s → "Xs ago"
    if delta_seconds < 60:
        seconds = int(delta_seconds)
        return f"{seconds}s ago"

    # 60s to < 3600s → "Xm ago"
    if delta_seconds < 3600:
        minutes = int(delta_seconds // 60)
        return f"{minutes}m ago"

    # 3600s to < 86400s → "Xh ago"
    if delta_seconds < 86400:
        hours = int(delta_seconds // 3600)
        return f"{hours}h ago"

    # >= 86400s → "Xd ago"
    days = int(delta_seconds // 86400)
    return f"{days}d ago"