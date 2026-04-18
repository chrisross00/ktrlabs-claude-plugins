"""Sluggify free-form title strings for filesystem paths."""
from __future__ import annotations

import re
import unicodedata

MAX_SLUG_LEN = 60


def slugify(title: str) -> str:
    # Strip diacritics.
    nfkd = unicodedata.normalize("NFKD", title)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Keep alphanumerics; everything else becomes a separator.
    lowered = ascii_only.lower()
    collapsed = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    if not collapsed:
        return "untitled"
    return collapsed[:MAX_SLUG_LEN].rstrip("-")
