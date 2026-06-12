"""Jua weather API client (stub).

Real integration plan: query Jua for climate normals / extremes at the
deployment location and convert them into design constraints (operating
temperature range, humidity, UV exposure). Until that lands this returns
canned notes; JUA_API_KEY is read so the call signature will not change
when the real client is wired in.
"""

from __future__ import annotations

from .. import config


def climate_notes(location: str | None = None) -> list[str]:
    # TODO: call the Jua API with config.env("JUA_API_KEY") and `location`.
    del location
    source = "Jua stub" + (" (key configured)" if config.env("JUA_API_KEY") else "")
    return [
        f"Outdoor deployment ({source}): design for -10..45 C ambient and "
        "condensing humidity; derate LiPo charging below 0 C.",
        f"Outdoor deployment ({source}): specify conformal coating and an "
        "IP54+ enclosure; UV-stable plastics if sun-exposed.",
    ]
