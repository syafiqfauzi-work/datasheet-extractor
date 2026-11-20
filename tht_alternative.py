"""
tht_alternative.py  -  THT override for ASI + SMD alternative finder (R* / RG)

Rule (Component Engineering):
  * Mounting = THT  -> ASI is forced to U or V, regardless of the other parameters
  * An SMD alternative that follows the RG ASI rules exists  -> ASI = U  (list it in the Alternative tab)
  * No SMD alternative                                      -> ASI = V

An SMD alternative is accepted only if it:
  - is SMD (never THT)
  - has the same resistance or the nearest preferred value (E96-closest-to-E12 = ASI-T)
  - is not an E192-exclusive value (that would be ASI-U/V again)
  - has TC <= 200 ppm/K
  - has tolerance <= the original tolerance
  - has power rating >= the original (approximate allowed down to 90 % -> flagged)
  - termination SN (preferred, ASI-T) or another ASI-O termination
"""

from __future__ import annotations

import json
import math
import re
from typing import Callable, Optional

# --------------------------------------------------------------------------- #
# 1. THT detection
# --------------------------------------------------------------------------- #
_THT_RE = re.compile(
    r"(\bTHT\b|\bTHW\b|through[\s\-]?hole|\baxial\b|\bradial\b|\bleaded\b|"
    r"\bRM[\s\-]?\d|\bTO[\s\-]?220\b|\bTO[\s\-]?247\b|\bSIP\b|\bDIP\b)",
    re.I,
)
_SMD_RE = re.compile(r"(\bSMD\b|\bSMT\b|surface[\s\-]?mount|\bchip\b|\bMELF\b|"
                     r"\b0[0-9]{3}\b|\b1[0-9]{3}\b|\b2[0-9]{3}\b|D2?PAK|TO[\s\-]?26[23]|TO[\s\-]?252)",
                     re.I)


def is_tht(mounting: str | None, package: str | None = "") -> bool:
    """True when mounting/package text says through-hole."""
    text = f"{mounting or ''} {package or ''}"
    if not text.strip():
        return False
    if _THT_RE.search(text):
        # 'SMD' explicitly mentioned in mounting wins over a package hint
        return not (mounting and _SMD_RE.search(mounting) and not _THT_RE.search(mounting))
    return False


# --------------------------------------------------------------------------- #
# 2. Value helpers (E-series)
# --------------------------------------------------------------------------- #
E96_PREFERRED_T = [1.00, 1.21, 1.50, 1.82, 2.21, 2.74, 3.32, 3.92, 4.75, 5.62, 6.81, 8.25]


def _eseries(n: int) -> list[float]:
    vals = [round(10 ** (i / n), 2) for i in range(n)]
    if n == 192:  # IEC 60063 deviation from the formula
        vals = [9.20 if v == 9.19 else v for v in vals]
    return vals


E96 = set(_eseries(96))
E192 = set(_eseries(192))
E192_EXCLUSIVE = E192 - E96


def parse_ohms(v) -> Optional[float]:
    """'33R', '4K7', '1.5k', '33 Ω', '0R1', '2M2', 33 -> float ohms."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().upper().replace("Ω", "").replace("OHM", "").replace(" ", "")
    s = s.replace(",", ".")
    m = re.fullmatch(r"(\d*)([RKMG])(\d*)", s)
    if m and (m.group(1) or m.group(3)):
        mult = {"R": 1, "K": 1e3, "M": 1e6, "G": 1e9}[m.group(2)]
        return float(f"{m.group(1) or '0'}.{m.group(3) or '0'}") * mult
    m = re.fullmatch(r"([\d.]+)([KMG]?)", s)
    if m:
        mult = {"": 1, "K": 1e3, "M": 1e6, "G": 1e9}[m.group(2)]
        return float(m.group(1)) * mult
    return None


def format_ohms(v: float) -> str:
    """33.2 -> '33R2', 1500 -> '1K5', 33 -> '33R'."""
    for div, letter in ((1e9, "G"), (1e6, "M"), (1e3, "K"), (1, "R")):
        if v >= div or letter == "R":
            x = round(v / div, 4)
            whole, _, frac = f"{x:g}".partition(".")
            return f"{whole}{letter}{frac}"
    return str(v)


def _mantissa(ohms: float) -> tuple[float, int]:
    exp = math.floor(math.log10(ohms))
    return round(ohms / 10 ** exp, 2), exp


def value_series_rating(ohms: float) -> str:
    """'T' for E96-closest-to-E12, 'U/V' for E192-exclusive, else 'O'."""
    mant, _ = _mantissa(ohms)
    if mant in E96_PREFERRED_T:
        return "T"
    if mant in E192_EXCLUSIVE:
        return "U/V"
    return "O"


def nearest_preferred(ohms: float) -> float:
    """Nearest ASI-T value (E96 closest to E12)."""
    mant, exp = _mantissa(ohms)
    cands = E96_PREFERRED_T + [10.0]
    best = min(cands, key=lambda c: abs(math.log(c / mant)))
    return round(best * 10 ** exp, 6)


# --------------------------------------------------------------------------- #
# 3. SMD package by power
# --------------------------------------------------------------------------- #
# (package, typical max rated power W) - standard thick/thin film + power SMD types
SMD_POWER_TABLE = [
    ("0402", 0.063), ("0603", 0.1), ("0805", 0.125), ("1206", 0.25),
    ("1210", 0.5), ("2010", 0.75), ("2512", 1.0),
    ("2512 high-power", 2.0), ("1225 wide terminal", 2.0),
    ("TO-252 (DPAK) power resistor", 5.0),
    ("TO-263 (D2PAK) power resistor", 20.0),
]


def smd_packages_for_power(p_w: Optional[float]) -> list[str]:
    """Smallest SMD packages that can carry p_w (first = preferred)."""
    if not p_w:
        return [p for p, _ in SMD_POWER_TABLE[:7]]
    ok = [p for p, pmax in SMD_POWER_TABLE if pmax >= p_w]
    return ok[:3] if ok else []


# --------------------------------------------------------------------------- #
# 4. Candidate check against the RG ASI rule
# --------------------------------------------------------------------------- #
def _num(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"[-+]?\d*\.?\d+", str(v).replace(",", "."))
    return float(m.group()) if m else None


def _power_w(v) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip().upper()
    m = re.fullmatch(r"(\d+)/(\d+)\s*W?", s)
    if m:
        return int(m.group(1)) / int(m.group(2))
    x = _num(s)
    if x is None:
        return None
    return x / 1000 if "MW" in s else x


def check_candidate(orig: dict, cand: dict) -> tuple[bool, str, list[str]]:
    """Return (accepted, candidate ASI, notes)."""
    notes: list[str] = []
    if is_tht(cand.get("mounting"), cand.get("package")):
        return False, "U/V", ["THT"]

    r_o, r_c = parse_ohms(orig.get("resistance")), parse_ohms(cand.get("resistance"))
    if not r_c:
        return False, "?", ["resistance unknown"]
    vs = value_series_rating(r_c)
    if vs == "U/V":
        return False, "U/V", ["E192-exclusive value"]
    if r_o and abs(r_c - r_o) / r_o > 0.05:
        return False, "?", [f"resistance too far from {format_ohms(r_o)}"]
    if r_o and r_c != r_o:
        notes.append(f"approx. value ({format_ohms(r_c)} vs {format_ohms(r_o)})")

    tc = _num(cand.get("tc"))
    if tc is None:
        notes.append("TC not stated - verify ≤ 200 ppm")
    elif abs(tc) > 200:
        return False, "U/V", ["TC > 200 ppm"]

    tol_o, tol_c = _num(orig.get("tolerance")), _num(cand.get("tolerance"))
    if tol_o is not None and tol_c is not None and tol_c > tol_o:
        return False, "?", [f"tolerance {tol_c}% worse than {tol_o}%"]

    p_o, p_c = _power_w(orig.get("power")), _power_w(cand.get("power"))
    if p_o and p_c:
        if p_c < 0.9 * p_o:
            return False, "?", [f"power {p_c} W < {p_o} W"]
        if p_c < p_o:
            notes.append(f"power slightly lower ({p_c} W vs {p_o} W) - check derating")
    elif p_o:
        notes.append("power not stated - verify")

    term = str(cand.get("termination") or "").upper()
    term_rating = "T" if (not term or "SN" in term or "TIN" in term) else "O"

    asi = "T" if (vs == "T" and term_rating == "T" and (tc is None or abs(tc) <= 200)) else "O"
    return True, asi, notes


# --------------------------------------------------------------------------- #
# 5. Sources of alternatives
# --------------------------------------------------------------------------- #
def _find_col(df, *keys):
    for c in df.columns:
        lc = str(c).lower()
        if all(k in lc for k in keys):
            return c
    return None


def dms_candidates(orig: dict, dms_df) -> list[dict]:
    """SMD parts already in DMS with the same / nearest preferred resistance."""
    if dms_df is None or len(dms_df) == 0:
        return []
    col = {
        "material": _find_col(dms_df, "material") or _find_col(dms_df, "sach"),
        "mpn": _find_col(dms_df, "mpn") or _find_col(dms_df, "part", "number"),
        "manufacturer": _find_col(dms_df, "manufact") or _find_col(dms_df, "hersteller"),
        "resistance": _find_col(dms_df, "resist"),
        "power": _find_col(dms_df, "power"),
        "tolerance": _find_col(dms_df, "tol"),
        "tc": _find_col(dms_df, "temp", "coef") or _find_col(dms_df, "tc"),
        "package": _find_col(dms_df, "package"),
        "mounting": _find_col(dms_df, "mount"),
        "asi": _find_col(dms_df, "asi"),
    }
    if not col["resistance"]:
        return []

    r_o = parse_ohms(orig.get("resistance"))
    targets = {r_o, nearest_preferred(r_o)} if r_o else set()
    out = []
    for _, row in dms_df.iterrows():
        r = parse_ohms(row[col["resistance"]])
        if not r or not any(t and abs(r - t) / t < 0.005 for t in targets):
            continue
        if col["asi"] and str(row[col["asi"]]).strip().upper()[:1] in ("U", "V"):
            continue  # don't propose parts that are themselves phase-out
        cand = {k: (row[c] if c else None) for k, c in col.items()}
        cand["source"] = "DMS"
        out.append(cand)
    return out


GEMINI_PROMPT = """You are a component engineer. The part below is a THROUGH-HOLE (THT) fixed resistor.
Propose up to {n} real, currently active SMD (surface-mount) replacement resistors.

Original part:
{orig}

Hard requirements:
- SMD only (chip 0402..2512, high-power 2512/1225, or TO-252 / TO-263 power resistor)
- Resistance: {r_exact} (exact) or {r_pref} (nearest preferred value) - nothing else
- Tolerance <= {tol} %
- TC <= 200 ppm/K (lower is better)
- Power rating >= {power} W (suggested packages: {pkgs})
- Tin (SN) termination preferred
- Prefer major suppliers (Vishay, Yageo, Panasonic, KOA, Rohm, Bourns, TE, Susumu)

Return ONLY a JSON array, no prose. Each item:
{{"mpn": "", "manufacturer": "", "resistance": "", "tolerance": "", "tc": "",
  "power": "", "package": "", "mounting": "SMD", "termination": "", "remark": ""}}
"""


def llm_candidates(orig: dict, llm: Callable[[str], str], n: int = 5) -> list[dict]:
    r_o = parse_ohms(orig.get("resistance"))
    if not r_o:
        return []
    p_o = _power_w(orig.get("power"))
    prompt = GEMINI_PROMPT.format(
        n=n,
        orig=json.dumps(orig, ensure_ascii=False, default=str),
        r_exact=format_ohms(r_o),
        r_pref=format_ohms(nearest_preferred(r_o)),
        tol=_num(orig.get("tolerance")) or 1,
        power=p_o or "same as original",
        pkgs=", ".join(smd_packages_for_power(p_o)) or "power SMD",
    )
    try:
        raw = llm(prompt)
        raw = raw[raw.find("["): raw.rfind("]") + 1]
        items = json.loads(raw) if raw else []
    except Exception:
        return []
    for it in items:
        it["source"] = "Suggested (verify)"
    return [it for it in items if isinstance(it, dict)]


# --------------------------------------------------------------------------- #
# 6. Main entry
# --------------------------------------------------------------------------- #
def determine_tht_asi(orig: dict, dms_df=None, llm: Callable[[str], str] | None = None) -> dict:
    """
    orig keys used: resistance, tolerance, tc, power, mounting, package, mpn, manufacturer

    Returns:
      {"is_tht": bool, "asi": "U"|"V"|None, "reason": str, "alternatives": [dict, ...],
       "recommended_packages": [...], "preferred_value": "33R2"}
    """
    if not is_tht(orig.get("mounting"), orig.get("package")):
        return {"is_tht": False, "asi": None, "reason": "", "alternatives": []}

    r_o = parse_ohms(orig.get("resistance"))
    p_o = _power_w(orig.get("power"))

    raw = dms_candidates(orig, dms_df)
    if llm is not None:
        raw += llm_candidates(orig, llm)

    accepted, seen = [], set()
    for c in raw:
        key = (str(c.get("mpn") or c.get("material") or "")).strip().upper()
        if key and key in seen:
            continue
        ok, cand_asi, notes = check_candidate(orig, c)
        if ok:
            seen.add(key)
            c["candidate_asi"] = cand_asi
            c["notes"] = "; ".join(notes)
            accepted.append(c)

    # DMS first, then ASI-T before ASI-O, then exact value first
    accepted.sort(key=lambda c: (c.get("source") != "DMS",
                                 c.get("candidate_asi") != "T",
                                 "approx" in c.get("notes", "")))

    if accepted:
        asi, reason = "U", (f"THT mounting → phase-out. {len(accepted)} SMD alternative(s) "
                            f"following the RG ASI rule found (see Alternative tab).")
    else:
        asi, reason = "V", "THT mounting → not recommended. No SMD alternative found."

    return {
        "is_tht": True,
        "asi": asi,
        "reason": reason,
        "alternatives": accepted,
        "recommended_packages": smd_packages_for_power(p_o),
        "preferred_value": format_ohms(nearest_preferred(r_o)) if r_o else None,
    }


# --------------------------------------------------------------------------- #
# 7. Glue for app.py (extracted_data dict  ->  orig specs, override, UI)
# --------------------------------------------------------------------------- #
def _val(extracted: dict, *needles: str):
    """Value of the first key in extracted_data containing all needles (case-insensitive)."""
    for k, item in extracted.items():
        lk = k.lower()
        if all(n.lower() in lk for n in needles):
            v = item.get("value") if isinstance(item, dict) else item
            if v is not None and str(v).strip() not in ("", "N/A", "-"):
                return str(v)
    return None


def specs_from_extracted(extracted: dict, designation: str = "", manufacturer: str = "",
                         mpn: str = "") -> dict:
    """Build the 'orig' dict for determine_tht_asi from the app's extracted_data.
    Missing values are taken from the designation (e.g. '33R 1% 20PPM 3W')."""
    d = (designation or "").upper()
    m_r = re.match(r"\s*(\d*[RKMG]\d*|\d+(?:\.\d+)?)\b", d)
    m_tol = re.search(r"(\d+(?:\.\d+)?)\s*%", d)
    m_tc = re.search(r"(\d+)\s*PPM", d)
    m_p = re.search(r"(\d+(?:\.\d+)?|\d+/\d+)\s*W\b", d)
    return {
        "resistance": _val(extracted, "resistance") or (m_r.group(1) if m_r else None),
        "tolerance": _val(extracted, "tolerance") or _val(extracted, "tol") or (m_tol.group(1) if m_tol else None),
        "tc": _val(extracted, "temperature coefficient") or _val(extracted, "temp.coef")
              or (m_tc.group(1) if m_tc else None),
        "power": _val(extracted, "power") or (m_p.group(1) if m_p else None),
        "mounting": _val(extracted, "kind of mounting") or _val(extracted, "mounting"),
        "package": _val(extracted, "package type"),
        "termination": _val(extracted, "terminal plating"),
        "mpn": mpn,
        "manufacturer": manufacturer,
    }


ASI_TEXT = {
    "U": "U · Intended for phase out",
    "V": "V · Not recommended for new designs",
}


def apply_tht_override(asi_result: dict, tht: dict) -> dict:
    """Return a copy of asi_result with the overall ASI forced to U / V.
    Writes to whichever of the usual key names the rules module uses."""
    if not tht or not tht.get("is_tht"):
        return asi_result
    res = dict(asi_result)
    code = tht["asi"]
    for k in ("asi", "code", "result", "status", "rating", "level"):
        if k in res and not isinstance(res[k], (list, dict)):
            res[k] = code
    res["label"] = ASI_TEXT[code]
    for k in ("reason", "message", "msg", "summary", "note", "detail", "explanation"):
        if k in res and isinstance(res[k], str):
            res[k] = tht["reason"]
    res.setdefault("reason", tht["reason"])
    res["tht_override"] = code
    return res


def render_tht_alternatives(tht: dict) -> None:
    """Alternative tab content for a THT part."""
    import pandas as pd
    import streamlit as st

    code = tht["asi"]
    st.subheader(f"SMD alternatives · THT → ASI {code}")
    st.caption(f"Suggested SMD package(s) for this power: "
               f"{', '.join(tht['recommended_packages']) or 'n/a'} · "
               f"Nearest ASI-T value: {tht.get('preferred_value') or 'n/a'}")
    if not tht["alternatives"]:
        st.warning("No SMD alternative following the RG ASI rule was found → ASI V.")
        return
    cols = ["source", "material", "mpn", "manufacturer", "resistance", "tolerance", "tc",
            "power", "package", "termination", "candidate_asi", "notes"]
    df = pd.DataFrame(tht["alternatives"]).reindex(columns=cols)
    df = df.dropna(axis=1, how="all").fillna("")
    df.columns = [c.replace("_", " ").title().replace("Asi", "ASI").replace("Tc", "TC").replace("Mpn", "MPN")
                  for c in df.columns]
    st.dataframe(df.astype(str), width="stretch", hide_index=True)
    st.caption("“Suggested (verify)” rows come from the AI. Check the datasheet (power derating, "
               "heatsinking for TO-252/TO-263) before use. DMS rows are existing material numbers.")
