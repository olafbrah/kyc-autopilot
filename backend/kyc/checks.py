"""Deterministic KYC checks. Code decides what code can decide; the model only sees the results.

Each check returns {"status": "clear" | "info" | "review" | "fail", "detail": str, ...}.
Risk tier: any fail -> high, any review -> medium, else low (shown in the UI as the screening result Hit / Needs review /
Clear). It summarises the checks; it is not a customer risk rating. Only low-tier cases can ever be auto-cleared.
"""
import json
import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

WATCHLIST = json.loads((Path(__file__).parent / "data" / "watchlist.json").read_text())
# Illustrative lists; in production these come from compliance's country-risk methodology (FATF lists etc.).
HIGH_RISK_COUNTRIES = {"KP", "IR", "MM"}
ELEVATED_RISK_COUNTRIES = {"SY", "YE", "SS", "HT", "VE", "AF"}
EDD_MONTHLY_VOLUME = 50_000  # USD; above this, enhanced due diligence by a human
DOC_FORMATS = {"passport": r"^[A-Z0-9]{8,9}$", "national_id": r"^[A-Z0-9]{6,12}$", "drivers_license": r"^[A-Z0-9-]{6,15}$"}


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return " ".join(sorted(re.sub(r"[^a-z ]", " ", s).split()))


def similarity(a: str, b: str) -> float:
    return round(SequenceMatcher(None, normalize(a), normalize(b)).ratio(), 3)


def _best(name: str, entries: list[dict]) -> tuple[float, dict | None]:
    scored = [(similarity(name, e["name"]), e) for e in entries]
    return max(scored, key=lambda t: t[0]) if scored else (0.0, None)


def _parse(d: str | None) -> date | None:
    try:
        return date.fromisoformat(d) if d else None
    except ValueError:
        return None


def sanctions(a: dict) -> dict:
    score, e = _best(a["full_name"], WATCHLIST["sanctions"])
    if e and score >= 0.9 and e["dob"] == a.get("date_of_birth"):
        return {"status": "fail", "detail": f"Match on {e['list']}: {e['name']} (score {score}, DOB matches)", "score": score}
    if e and score >= 0.82:
        return {"status": "review", "detail": f"Possible match on {e['list']}: {e['name']} (score {score})", "score": score}
    return {"status": "clear", "detail": "No sanctions match", "score": score}


def pep(a: dict) -> dict:
    score, e = _best(a["full_name"], WATCHLIST["pep"])
    if e and score >= 0.9:
        return {"status": "review", "detail": f"Possible PEP: {e['name']}, {e['position']} ({e['country']})", "score": score}
    return {"status": "clear", "detail": "No PEP match", "score": score}


def id_document(a: dict, today: date) -> dict:
    doc = a.get("id_document") or {}
    expiry = _parse(doc.get("expiry"))
    fmt = DOC_FORMATS.get(doc.get("type", ""))
    if not doc or expiry is None or fmt is None:
        return {"status": "fail", "detail": "ID document missing or unreadable"}
    if not re.match(fmt, doc.get("number", "")):
        return {"status": "fail", "detail": f"{doc['type']} number has an invalid format"}
    if expiry < today:
        return {"status": "fail", "detail": f"{doc['type']} expired on {expiry.isoformat()}"}
    if (expiry - today).days < 30:
        return {"status": "review", "detail": f"{doc['type']} expires in {(expiry - today).days} days"}
    return {"status": "clear", "detail": f"Valid {doc['type']} until {expiry.isoformat()}"}


def identity_match(a: dict, today: date) -> dict:
    doc = a.get("id_document") or {}
    dob = _parse(a.get("date_of_birth"))
    if dob is None:
        return {"status": "fail", "detail": "Date of birth missing"}
    age = (today - dob).days // 365
    if age < 18:
        return {"status": "fail", "detail": f"Applicant is {age}, under 18"}
    if doc.get("dob_on_document") and doc["dob_on_document"] != a["date_of_birth"]:
        return {"status": "fail", "detail": f"DOB on document ({doc['dob_on_document']}) differs from application"}
    score = similarity(a["full_name"], doc.get("name_on_document", ""))
    if score < 0.9:
        return {"status": "review", "detail": f"Name on document differs from application (similarity {score})"}
    return {"status": "clear", "detail": "Name and DOB match the document"}


def country_risk(a: dict) -> dict:
    countries = {a.get("nationality"), a.get("country_of_residence")} - {None}
    if countries & HIGH_RISK_COUNTRIES:
        return {"status": "fail", "detail": f"High-risk jurisdiction: {', '.join(sorted(countries & HIGH_RISK_COUNTRIES))}"}
    if countries & ELEVATED_RISK_COUNTRIES:
        return {"status": "review", "detail": f"Elevated-risk jurisdiction: {', '.join(sorted(countries & ELEVATED_RISK_COUNTRIES))}"}
    return {"status": "clear", "detail": "No country-risk flags"}


def expected_volume(a: dict) -> dict:
    v = float(a.get("expected_monthly_volume") or 0)
    if v > EDD_MONTHLY_VOLUME:
        return {"status": "review", "detail": f"Expected volume ${v:,.0f}/month exceeds the EDD threshold"}
    return {"status": "clear", "detail": f"Expected volume ${v:,.0f}/month"}


def adverse_media(a: dict) -> dict:
    # The vendor returns name hits; deciding whether a hit is about *this* person is judgment, so it's left to the model.
    n = len(a.get("adverse_media") or [])
    return {"status": "info" if n else "clear", "detail": f"{n} media hit(s) on the applicant's name" if n else "No media hits"}


def run_checks(a: dict, today: date | None = None) -> tuple[dict, str]:
    today = today or date.today()
    results = {"sanctions": sanctions(a), "pep": pep(a), "id_document": id_document(a, today),
               "identity_match": identity_match(a, today), "country_risk": country_risk(a),
               "expected_volume": expected_volume(a), "adverse_media": adverse_media(a)}
    statuses = {r["status"] for r in results.values()}
    tier = "high" if "fail" in statuses else "medium" if "review" in statuses else "low"
    return results, tier
