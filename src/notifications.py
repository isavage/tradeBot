"""Optional ntfy notifications for candidates and failed runs."""
from __future__ import annotations

import logging
import os
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)
def send_ntfy(message: str, title: str = "TradeBot", priority: int = 3) -> bool:
    server = os.getenv("NTFY_URL", "https://ntfy.sh").rstrip("/")
    topic = os.getenv("NTFY_TOPIC")
    if not topic:
        LOGGER.info("ntfy not configured; skipping notification")
        return False
    payload = message.encode("utf-8")
    try:
        request = Request(f"{server}/{topic}", data=payload, method="POST", headers={
            "Title": title,
            "Priority": str(priority),
            "Tags": "rotating_light" if priority >= 4 else "chart_with_upwards_trend",
        })
        with urlopen(request, timeout=15) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
        return True
    except Exception as exc:
        # Notification failures must not stop trading analysis.
        LOGGER.warning("ntfy notification failed: %s", exc)
        return False
