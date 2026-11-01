"""Contact-info masking for user-generated text that other users can read."""

import re

# Indian mobile numbers, optionally with +91/0 and common separators.
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?91[\s-]?|0)?([6-9]\d{4})[\s-]?(\d{5})(?!\d)"
)


def mask_phone_numbers(text: str) -> str:
    """Replace any Indian mobile number with a masked form that keeps the
    last four digits, so support can still reference the number."""

    def _replace(match: re.Match[str]) -> str:
        last_four = match.group(2)[-4:]
        return f"+91 ••••• •{last_four}"

    return _PHONE_RE.sub(_replace, text)
