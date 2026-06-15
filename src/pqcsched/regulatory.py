"""The regulatory profile — a SINGLE, DATED, SOURCED source of truth for PQC
mandate deadlines.

Why this module exists (a safety property, not a convenience): deadlines change,
and a compliance tool that serves stale dates *with confidence* is worse than one
that admits its data's age. So:

* every regulatory date lives in ``data/regulatory.json`` (decoupled from code) —
  updating is a verified data edit + a bumped ``as_of`` + cited sources, never a
  hunt through hardcoded values;
* the profile carries an ``as_of`` and a ``review_due`` date, and :func:`status`
  computes **staleness at runtime** so the API/UI can surface the data's age and a
  "verify against current mandates" disclaimer on every suggestion;
* the defaults are explicitly a *starting point you should override*, never an
  assertion of law.

Fully-automatic self-update is deliberately NOT done: there is no official
machine-readable feed of regulatory deadlines, so auto-scraping risks injecting
wrong dates with false confidence. Updates are human-verified (see
``UPDATING_REGULATORY.md``); a scheduled CI job flags when a review is due.
"""

from __future__ import annotations

import datetime
import json
import os

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "regulatory.json")

with open(_PATH, encoding="utf-8") as _fh:
    PROFILE: dict = json.load(_fh)

AS_OF = datetime.date.fromisoformat(PROFILE["as_of"])
REVIEW_DUE = datetime.date.fromisoformat(PROFILE["review_due"])
DISCLAIMER: str = PROFILE["disclaimer"]
MANDATES: list = PROFILE["mandates"]
STANDARDS: dict = PROFILE.get("standards", {})
_DDL: dict = PROFILE["default_deadline_policy"]


def is_stale(today: datetime.date | None = None) -> bool:
    """True if the profile is past its review-due date (needs human re-verification)."""
    return (today or datetime.date.today()) > REVIEW_DUE


def days_old(today: datetime.date | None = None) -> int:
    return ((today or datetime.date.today()) - AS_OF).days


def status(today: datetime.date | None = None) -> dict:
    """Runtime regulatory status for the API/UI: the data, its age, and whether it
    is stale. Surfacing this on every suggestion is the core mitigation against
    silently serving outdated mandates."""
    today = today or datetime.date.today()
    return {
        "as_of": PROFILE["as_of"],
        "review_due": PROFILE["review_due"],
        "days_old": (today - AS_OF).days,
        "stale": today > REVIEW_DUE,
        "disclaimer": DISCLAIMER,
        "mandates": MANDATES,
        "standards": STANDARDS,
        "threat_context": PROFILE.get("threat_context", {}),
        "default_policy_profile": _DDL.get("profile"),
    }


def default_deadline_period(asset_class: str, base_year: int | None = None) -> int | None:
    """Default mandated deadline for a coarse asset class, as a **period offset**
    (years after ``base_year``), or ``None`` if unmandated. Used only when a CBOM
    carries no deadline of its own; always overridable.
    """
    by = _DDL["by_asset_class"]
    year = by.get(asset_class, by.get("default"))
    if year is None:
        return None
    base = base_year if base_year is not None else _DDL["base_year"]
    return max(0, int(year) - int(base))
