"""Plain-text presentation: short blocks, exact decimal notation, explicit UTC."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation


def number(value):
    if value is None:
        return "N/A"
    try:
        decimal = Decimal(str(value))
        if not decimal.is_finite():
            return "N/A"
        result = format(decimal, "f")
        return result.rstrip("0").rstrip(".") if "." in result else result
    except InvalidOperation:
        return "N/A"


def utc_time(value):
    if value is None:
        return "N/A"
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return "waktu tanpa zona"
        return stamp.astimezone(UTC).strftime("%d %b %Y, %H:%M:%S UTC")
    except (ValueError, TypeError):
        return "N/A"


def block(title, *lines):
    return title + "\n\n" + "\n".join(lines)
