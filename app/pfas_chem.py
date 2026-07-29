"""Code-side PFAS chemical reference: abbreviation -> full name, CAS, PubChem CID,
and the applicable drinking-water regulatory limits.

WHY THIS IS CODE, NOT DATABASE
------------------------------
PFAS in the EGLE/MPART feeds are labelled by abbreviation (PFOS, PFOA, PFHxS,
PFNA, PFBS, PFHxA, GenX, …), which the app's PubChem cache (`chemical_reference`,
keyed by the names that appear in the pesticide/TRI/water data) does not contain.
Rather than republish the database, this module lets the shared /api/chemical
endpoint resolve a PFAS abbreviation to its full identity so the existing
chemical-info popup can show what it is — a normal code push, no DB rebuild.

ACCURACY
--------
* Every CAS number and PubChem CID was verified against PubChem's PUG REST API
  (name/CAS -> CID). The CID makes the popup's "Full profile on PubChem" link work.
* Regulatory limits are the U.S. EPA **final PFAS National Primary Drinking Water
  Regulation (April 2024)** individual MCLs — PFOA 4 ppt, PFOS 4 ppt, PFHxS 10 ppt,
  PFNA 10 ppt, HFPO-DA/GenX 10 ppt — plus the Hazard Index that covers mixtures of
  PFHxS, PFNA, HFPO-DA and PFBS. Michigan's 2020 state MCLs are included as
  secondary context. These are **drinking-water** standards; the caller labels
  them as such (a surface-water sample is not "in violation" of a drinking-water
  MCL — the limit is shown for context only). ppt = parts per trillion = ng/L.
* IARC (Dec 2023): PFOA is Group 1 (carcinogenic to humans); PFOS is Group 2B
  (possibly carcinogenic to humans).
"""
from __future__ import annotations

import re

# Each entry: abbrev, full name, CAS, PubChem CID, optional formula, a short
# sourced description, and `regulatory` (epa_mcl_ppt / hazard_index / mi_mcl_ppt).
# `aliases` are extra spellings seen in feeds. EPA year = 2024 rule; MI year = 2020.
_PRIMARY = [
    {
        "abbrev": "PFOA", "name": "Perfluorooctanoic acid", "cas": "335-67-1",
        "cid": 9554, "formula": "C8HF15O2",
        "aliases": ["perfluorooctanoate", "C8", "PFOA"],
        "description": (
            "Perfluorooctanoic acid (PFOA) is a synthetic per-/polyfluoroalkyl "
            "substance (PFAS) — a “forever chemical” — historically used to make "
            "fluoropolymers such as Teflon. It is extremely persistent in the "
            "environment and bioaccumulates in people and wildlife. IARC classifies "
            "PFOA as carcinogenic to humans (Group 1). EPA set an enforceable "
            "drinking-water limit of 4 ppt for PFOA in 2024."),
        "regulatory": {"epa_mcl_ppt": 4, "hazard_index": False, "mi_mcl_ppt": 8},
    },
    {
        "abbrev": "PFOS", "name": "Perfluorooctanesulfonic acid", "cas": "1763-23-1",
        "cid": 74483, "formula": "C8HF17O3S",
        "aliases": ["perfluorooctane sulfonate", "perfluorooctanesulfonate", "PFOS"],
        "description": (
            "Perfluorooctanesulfonic acid (PFOS) is a PFAS “forever chemical” once "
            "widely used in stain- and water-repellents (e.g. Scotchgard) and in "
            "aqueous film-forming firefighting foam (AFFF). It is highly persistent "
            "and strongly bioaccumulative — the PFAS most often driving fish and "
            "game consumption advisories. IARC classifies PFOS as possibly "
            "carcinogenic to humans (Group 2B). EPA set an enforceable drinking-"
            "water limit of 4 ppt for PFOS in 2024."),
        "regulatory": {"epa_mcl_ppt": 4, "hazard_index": False, "mi_mcl_ppt": 16},
    },
    {
        "abbrev": "PFHxS", "name": "Perfluorohexanesulfonic acid", "cas": "355-46-4",
        "cid": 67734, "formula": "C6HF13O3S",
        "aliases": ["perfluorohexane sulfonate", "perfluorohexanesulfonate", "PFHxS"],
        "description": (
            "Perfluorohexanesulfonic acid (PFHxS) is a persistent PFAS “forever "
            "chemical” common in AFFF firefighting foam and consumer products; it "
            "bioaccumulates. EPA set a drinking-water limit of 10 ppt for PFHxS in "
            "2024, and it is also one of the four PFAS covered by EPA's Hazard Index "
            "for mixtures."),
        "regulatory": {"epa_mcl_ppt": 10, "hazard_index": True, "mi_mcl_ppt": 51},
    },
    {
        "abbrev": "PFNA", "name": "Perfluorononanoic acid", "cas": "375-95-1",
        "cid": 67821, "formula": "C9HF17O2",
        "aliases": ["perfluorononanoate", "PFNA"],
        "description": (
            "Perfluorononanoic acid (PFNA) is a long-chain PFAS “forever chemical” "
            "that is persistent and bioaccumulative. EPA set a drinking-water limit "
            "of 10 ppt for PFNA in 2024, and it is one of the four PFAS covered by "
            "EPA's Hazard Index for mixtures."),
        "regulatory": {"epa_mcl_ppt": 10, "hazard_index": True, "mi_mcl_ppt": 6},
    },
    {
        "abbrev": "PFBS", "name": "Perfluorobutanesulfonic acid", "cas": "375-73-5",
        "cid": 67815, "formula": "C4HF9O3S",
        "aliases": ["perfluorobutane sulfonate", "perfluorobutanesulfonate", "PFBS"],
        "description": (
            "Perfluorobutanesulfonic acid (PFBS) is a shorter-chain PFAS “forever "
            "chemical” introduced as a replacement for PFOS; it is persistent and "
            "mobile in water. It has no individual EPA drinking-water limit, but is "
            "one of the four PFAS covered by EPA's 2024 Hazard Index for mixtures."),
        "regulatory": {"epa_mcl_ppt": None, "hazard_index": True, "mi_mcl_ppt": 420},
    },
    {
        "abbrev": "PFHxA", "name": "Perfluorohexanoic acid", "cas": "307-24-4",
        "cid": 67542, "formula": "C6HF11O2",
        "aliases": ["perfluorohexanoate", "PFHxA"],
        "description": (
            "Perfluorohexanoic acid (PFHxA) is a shorter-chain PFAS “forever "
            "chemical,” persistent and mobile in water. It is not regulated by the "
            "2024 federal PFAS drinking-water rule; Michigan sets a state drinking-"
            "water limit of 400,000 ppt."),
        "regulatory": {"epa_mcl_ppt": None, "hazard_index": False, "mi_mcl_ppt": 400000},
    },
    {
        "abbrev": "GenX", "name": "Hexafluoropropylene oxide dimer acid (HFPO-DA)",
        "cas": "13252-13-6", "cid": 114481, "formula": "C6HF11O3",
        "aliases": ["HFPO-DA", "HFPO DA", "HFPODA", "GenX",
                    "hexafluoropropylene oxide dimer acid",
                    "perfluoro-2-propoxypropanoic acid", "2058-94-8"],
        "description": (
            "GenX is the trade name for hexafluoropropylene oxide dimer acid "
            "(HFPO-DA) and its ammonium salt — the fluorochemical DuPont/Chemours "
            "introduced as a replacement for PFOA. Despite being a “short-chain” "
            "alternative it is still a persistent PFAS “forever chemical.” EPA set a "
            "drinking-water limit of 10 ppt for GenX (HFPO-DA) in 2024, and it is "
            "one of the four PFAS covered by EPA's Hazard Index for mixtures."),
        "regulatory": {"epa_mcl_ppt": 10, "hazard_index": True, "mi_mcl_ppt": 370},
    },
]

# Additional PFAS that appear in EGLE fish / public-water sampling. Full identity
# so PubChem resolves them; none carry an individual 2024 EPA MCL.
_SECONDARY_DESC = (
    "A per-/polyfluoroalkyl substance (PFAS) — a persistent “forever chemical” "
    "that resists breakdown and can bioaccumulate. It is not assigned an "
    "individual limit under the 2024 U.S. EPA PFAS drinking-water rule.")
_SECONDARY = [
    ("PFBA", "Perfluorobutanoic acid", "375-22-4", 9777),
    ("PFPeA", "Perfluoropentanoic acid", "2706-90-3", 75921),
    ("PFHpA", "Perfluoroheptanoic acid", "375-85-9", 67818),
    ("PFDA", "Perfluorodecanoic acid", "335-76-2", 9555),
    ("PFUnA", "Perfluoroundecanoic acid", "2058-94-8", 77222),
    ("PFDoA", "Perfluorododecanoic acid", "307-55-1", 67545),
    ("PFTrDA", "Perfluorotridecanoic acid", "72629-94-8", 3018355),
    ("PFTeDA", "Perfluorotetradecanoic acid", "376-06-7", 67822),
    ("PFHpS", "Perfluoroheptanesulfonic acid", "375-92-8", 67820),
    ("PFDS", "Perfluorodecanesulfonic acid", "335-77-3", 67636),
    ("PFOSA", "Perfluorooctanesulfonamide", "754-91-6", 69785),
    ("NMeFOSAA", "N-Methyl perfluorooctanesulfonamidoacetic acid", "2355-31-9", 22286931),
    ("NEtFOSAA", "N-Ethyl perfluorooctanesulfonamidoacetic acid", "2991-50-6", 18134),
    ("6:2 FTS", "6:2 Fluorotelomer sulfonic acid", "27619-97-2", 119688),
    ("8:2 FTS", "8:2 Fluorotelomer sulfonic acid", "39108-34-4", 3016044),
]

# Build the full compound table + a normalized alias -> compound index.
PFAS_COMPOUNDS: list[dict] = list(_PRIMARY)
for abbrev, name, cas, cid in _SECONDARY:
    PFAS_COMPOUNDS.append({
        "abbrev": abbrev, "name": name, "cas": cas, "cid": cid,
        "aliases": [abbrev, name],
        "description": f"{name} ({abbrev}) is {_SECONDARY_DESC}",
        "regulatory": {"epa_mcl_ppt": None, "hazard_index": False, "mi_mcl_ppt": None},
    })


def _norm(s: str) -> str:
    """Normalize a name/abbrev/CAS for matching: drop spaces, hyphens, commas and
    lower the case (keeps digits and ':' so '6:2 FTS' still matches)."""
    return re.sub(r"[\s,\-]", "", (s or "")).lower()


_INDEX: dict[str, dict] = {}
for _c in PFAS_COMPOUNDS:
    for _key in [_c["abbrev"], _c["name"], _c["cas"], *_c.get("aliases", [])]:
        _INDEX.setdefault(_norm(_key), _c)


def lookup(name: str) -> dict | None:
    """Resolve a name / abbreviation / CAS to its PFAS reference, or None.

    Returns a copy with a display string (e.g. 'PFOS — Perfluorooctanesulfonic
    acid') so callers don't title-case an abbreviation into 'Pfos'."""
    c = _INDEX.get(_norm(name))
    if not c:
        return None
    out = dict(c)
    abbr, full = c["abbrev"], c["name"]
    out["display"] = full if _norm(abbr) == _norm(full) else f"{abbr} — {full}"
    return out
