"""The regulatory profile is a safety surface: dated, sourced, overridable, and it
must announce its own age. These tests lock that contract — the loader, the CBOM
default wiring, and the two API surfaces that expose staleness."""

from __future__ import annotations

import datetime

import pytest

from pqcsched import regulatory as reg
from pqcsched.cbom import CbomPolicy


# --- the loader / profile integrity -----------------------------------------

def test_profile_has_dates_disclaimer_and_sources():
    s = reg.status()
    # dated and parseable
    datetime.date.fromisoformat(s["as_of"])
    datetime.date.fromisoformat(s["review_due"])
    assert s["disclaimer"]  # non-empty "verify, not legal advice" text
    assert reg.REVIEW_DUE > reg.AS_OF
    # every mandate is sourced (no unverifiable date)
    assert s["mandates"], "profile must list mandates"
    for m in s["mandates"]:
        assert m.get("authority") and m.get("source", "").startswith("http")
        assert m.get("milestones")


def test_staleness_flips_after_review_due():
    before = reg.REVIEW_DUE - datetime.timedelta(days=1)
    after = reg.REVIEW_DUE + datetime.timedelta(days=1)
    assert reg.is_stale(before) is False
    assert reg.is_stale(after) is True
    assert reg.status(before)["stale"] is False
    assert reg.status(after)["stale"] is True
    assert reg.status(after)["days_old"] > 0


def test_default_deadline_period_maps_real_mandates():
    base = reg.PROFILE["default_deadline_policy"]["base_year"]
    # signing is the tightest real mandate (CNSA 2.0 software/firmware 2027)
    assert reg.default_deadline_period("signing_key", base) == 2027 - base
    assert reg.default_deadline_period("ca", base) == 2029 - base
    # unknown class falls back to the disallow backstop, never to "no deadline"
    assert reg.default_deadline_period("something-unknown", base) == \
        reg.default_deadline_period("default", base)
    assert reg.default_deadline_period("default", base) is not None
    # offsets are non-negative period indices
    for cls in ("signing_key", "ca", "protocol", "leaf", "key", "algorithm", "default"):
        assert reg.default_deadline_period(cls, base) >= 0


# --- the dangerous path: CBOM defaults must come FROM the dated profile -------

def test_cbom_default_deadlines_are_sourced_from_profile():
    """Regression for the original safety bug: CBOM defaults were hardcoded and
    did not match real mandates. They must now equal the profile-derived periods."""
    p = CbomPolicy()
    assert p.deadline_ca == reg.default_deadline_period("ca")
    assert p.deadline_key == reg.default_deadline_period("key")
    assert p.deadline_leaf == reg.default_deadline_period("leaf")
    assert p.deadline_algorithm == reg.default_deadline_period("algorithm")
    assert p.deadline_protocol == reg.default_deadline_period("protocol")
    assert p.deadline_default == reg.default_deadline_period("default")
    # and they are real-mandate-shaped: CAs no later than the disallow backstop
    assert p.deadline_ca <= p.deadline_algorithm


# --- the API surfaces that expose age to clients ------------------------------

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from pqcsched.api import app
    return TestClient(app)


def test_get_regulatory_returns_dated_sourced_profile(client):
    r = client.get("/regulatory")
    assert r.status_code == 200
    j = r.json()
    assert j["as_of"] == reg.PROFILE["as_of"]
    assert "stale" in j and "disclaimer" in j
    assert j["mandates"], "clients must be able to see which mandates applied"


def test_plan_stamps_every_response_with_regulatory_age(client):
    r = client.post("/plan", json={"sample": "enterprise", "capacity": 60, "time_limit": 8})
    assert r.status_code == 200
    j = r.json()
    rb = j.get("regulatory")
    assert rb, "every plan must carry the age + source of the data it used"
    assert rb["as_of"] == reg.PROFILE["as_of"]
    assert {"review_due", "days_old", "stale", "disclaimer"} <= set(rb)
