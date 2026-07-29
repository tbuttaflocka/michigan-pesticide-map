"""Hand-researched narratives for notable Michigan PFAS sites.

WHY THIS EXISTS
---------------
The PFAS overlay is driven by the live Michigan MPART / EGLE feeds, which are the
source of truth for each site's LOCATION, status, and contact info. That live data
is deliberately terse, though — a resident clicking the Wurtsmith marker sees the
MPART fields but nothing conveying the SCALE of the contamination. This file adds
an optional curated narrative layer for the highest-profile Michigan PFAS sites,
mirroring the researched narratives already attached to major contamination sites
(Dow, Velsicol, etc. in ``contamination_narratives``).

Narratives are ATTACHED to the matching live MPART records at load time by
``app.data_loader.apply_pfas_narratives`` (name-token + county match) — never as
separate markers. The live feed stays authoritative for location/status/contact;
the narrative only adds context, and the popup keeps its prominent link to the
official MPART site-investigation page.

ACCURACY RULES honored when compiling this file (public map — no fabrication):
  * Every concentration figure and advisory is verified against a real, cited
    source (``refs``); if a figure could not be sourced it was left OUT.
  * Every reading states its MEDIUM (groundwater / surface water / drinking water
    / tissue) and the regulatory criterion that applies to THAT medium. We do NOT
    compare a groundwater reading to the 4 ppt drinking-water MCL — a different
    medium and an unfair comparison. Groundwater is compared to Michigan's Part
    201 groundwater cleanup criteria (16 ppt PFOS, 8 ppt PFOA, drinking-water
    pathway); drinking water is compared to the standard in effect when sampled.
  * Michigan set enforceable drinking-water MCLs on Aug 3, 2020 — PFOS 16, PFOA 8,
    PFNA 6, PFHxS 51, HFPO-DA/GenX 370, PFBS 420, PFHxA 400,000 ppt — which became
    the Part 201 groundwater cleanup criteria, replacing the earlier combined
    70 ppt PFOS+PFOA EPA lifetime health advisory. The federal MCL (2024) is 4 ppt
    PFOS / 4 ppt PFOA. We name whichever standard actually applied to the reading.

Each record:
  key           — internal slug
  title         — short display heading for the narrative block
  county_fips   — restrict matching to this county (avoids cross-county name clash)
  match_names   — case-insensitive substrings; the narrative attaches to every
                  live site/AOI record in that county whose name contains one
  narrative     — factual prose (history + source of contamination)
  peaks         — documented peak concentrations, each with medium + standard +
                  source stated explicitly
  advisories    — fish / deer / drinking-water advisories, each with a source
  status        — current investigation / remediation status
  refs          — [{label, url}] sources shown in the popup

To add a site: append a record with sourced figures and re-run the loader (or the
standalone enrich, if added). Michigan only.
"""
from __future__ import annotations

# --- shared standard strings (stated per medium, never mismatched) ---
_GW_CRITERIA = ("Michigan Part 201 groundwater cleanup criteria for the "
                "drinking-water pathway: 16 ppt PFOS, 8 ppt PFOA")
_HA_2016 = ("the EPA 2016 lifetime health advisory of 70 ppt combined PFOS+PFOA "
            "in drinking water then in effect (today's federal MCL is 4 ppt each; "
            "Michigan's MCLs are 16 ppt PFOS / 8 ppt PFOA)")


PFAS_NARRATIVES: list[dict] = [
    {
        "key": "wurtsmith_oscoda",
        "title": "Former Wurtsmith Air Force Base & the Oscoda area",
        "county_fips": "26069",  # Iosco
        "match_names": ["Wurtsmith"],
        "narrative": (
            "The former Wurtsmith Air Force Base operated from 1923 until it closed "
            "in 1993. Decades of firefighting training with PFAS-containing aqueous "
            "film-forming foam (AFFF) left the base's groundwater among the most "
            "heavily PFAS-contaminated in Michigan; EGLE first confirmed PFAS in base "
            "groundwater in March 2010 while sampling a former fire-training area. "
            "PFAS has migrated from source areas into Clark's Marsh, Van Etten Lake, "
            "and the Au Sable River. The U.S. Air Force is the lead responsible party, "
            "with EGLE and MPART overseeing; investigation and interim measures "
            "(groundwater extraction and treatment) continue, and area-wide "
            "residential-well sampling has found many private wells above state "
            "criteria."
        ),
        "peaks": [
            {
                "analyte": "PFAS (PFOS-dominated)",
                "value": 213000, "unit": "ppt",
                "medium": "groundwater",
                "location": "former fire-training source areas on the base",
                "standard": _GW_CRITERIA,
                "source": "U.S. Department of Defense sampling, via EGLE / Environmental Working Group",
            },
            {
                "analyte": "wells above criteria",
                "text": "89 of 228 groundwater wells sampled in the Oscoda area "
                        "were above Michigan's PFAS criteria",
                "medium": "groundwater (area residential/monitoring wells)",
                "standard": "Michigan PFAS drinking-water criteria (PFOS 16, PFOA 8, "
                            "PFNA 6, PFHxS 51, PFBS 420, HFPO-DA 370, PFHxA 400,000 ppt)",
                "source": "EGLE / MPART, Oscoda Area residential-well sampling",
            },
        ],
        "advisories": [
            {
                "text": "Clark's Marsh area deer “Do Not Eat” advisory — a "
                        "white-tailed deer taken about two miles from Clark's Marsh "
                        "had 547 ppb PFOS in muscle tissue. MDHHS and the Michigan "
                        "DNR issued a ~5-mile advisory on Oct 19, 2018 (reduced to "
                        "about 3 miles in 2021).",
                "source": "MDHHS & Michigan DNR, 2018",
            },
            {
                "text": "“Do Not Eat” guidance for fish and wildlife from "
                        "Clark's Marsh due to very high PFOS; surface-water PFOS in "
                        "the marsh far exceeds Michigan's fish-consumption value.",
                "source": "MDHHS Eat Safe Fish / District Health Department No. 2",
            },
        ],
        "status": (
            "Active federal cleanup led by the U.S. Air Force under EGLE/MPART "
            "oversight; groundwater treatment and continued area-wide well sampling "
            "are ongoing. Bottled water / whole-house filtration has been provided "
            "to affected residents."
        ),
        "refs": [
            {"label": "MPART — Former Wurtsmith Air Force Base (Iosco County)",
             "url": "https://www.michigan.gov/pfasresponse/investigations/sites-aoi/iosco-county/wurtsmith"},
            {"label": "MPART — Oscoda Area (residential-well sampling)",
             "url": "https://www.michigan.gov/pfasresponse/investigations/sites-aoi/iosco-county/oscoda-area"},
            {"label": "MDHHS — Wurtsmith / Oscoda health assessment",
             "url": "https://www.michigan.gov/mdhhs/safety-injury-prev/environmental-health/topics/health-assessments/wurtsmith"},
            {"label": "MI DNR — Clark's Marsh deer “Do Not Eat” advisory (2018)",
             "url": "https://content.govdelivery.com/accounts/MIDNR/bulletins/2157986"},
            {"label": "National Wildlife Federation — PFAS at the former Wurtsmith AFB",
             "url": "https://www.nwf.org/-/media/PDFs/Regional/Great-Lakes/PFAS-Contamination-at-the-Former-Wurtsmith-Air-Force-Base.pdf"},
        ],
    },
    {
        "key": "wolverine_rockford",
        "title": "Wolverine World Wide tannery & House Street disposal (Kent County)",
        "county_fips": "26081",  # Kent
        "match_names": ["Rockford Tannery", "House St", "Wolverine"],
        "narrative": (
            "Wolverine World Wide used 3M Scotchgard (a PFAS product) to waterproof "
            "shoe leather at its Rockford tannery beginning in 1958, and disposed of "
            "tannery sludge and other waste in unlined trenches at the House Street "
            "Disposal Area in Belmont (Plainfield Township). In 2017, testing found "
            "PFAS had contaminated hundreds of residential drinking-water wells "
            "across Belmont, Plainfield Township, and Rockford. Contaminants include "
            "PFAS alongside heavy metals, VOCs and SVOCs from tannery operations."
        ),
        "peaks": [
            {
                "analyte": "PFAS",
                "value": 450000, "unit": "ppt",
                "medium": "groundwater (on-site monitoring wells)",
                "location": "former Rockford tannery / House Street Disposal Area, Belmont",
                "standard": _GW_CRITERIA,
                "source": "EPA / EGLE site monitoring (non-detect up to ~450,000 ppt, "
                          "highest in shallow groundwater)",
            },
        ],
        "advisories": [],
        "status": (
            "Under a February 2020 federal consent decree, Wolverine agreed to pay "
            "$69.5 million, connect more than 1,000 homes to municipal water, and "
            "consolidate House Street waste beneath four lined caps covering about "
            "27 acres. EPA and EGLE oversee the ongoing cleanup."
        ),
        "refs": [
            {"label": "EPA — Wolverine World Wide Tannery",
             "url": "https://www.epa.gov/mi/wolverine-world-wide-tannery"},
            {"label": "MPART — Rockford Tannery (Kent County)",
             "url": "https://www.michigan.gov/pfasresponse/investigations/sites-aoi/kent-county/rockford-tannery"},
            {"label": "PFAS Project Lab — Belmont / Plainfield / Rockford",
             "url": "https://pfasproject.com/belmont-plainfield-rockford-mi/"},
        ],
    },
    {
        "key": "parchment_crown_vantage",
        "title": "Parchment / Cooper Township drinking water (Crown Vantage, Kalamazoo County)",
        "county_fips": "26077",  # Kalamazoo
        "match_names": ["Crown Vantage"],
        "narrative": (
            "In July 2018, routine sampling under Michigan's statewide PFAS survey of "
            "public water supplies found the City of Parchment's municipal drinking "
            "water heavily contaminated. The supply served roughly 3,100 people in "
            "Parchment and Cooper Township. The contamination is attributed to the "
            "adjacent former paper-mill complex (the Crown Vantage property), where "
            "PFAS-treated paper waste was historically handled and disposed."
        ),
        "peaks": [
            {
                "analyte": "PFOS",
                "value": 740, "unit": "ppt",
                "medium": "public drinking water",
                "location": "City of Parchment municipal supply",
                "standard": _HA_2016,
                "source": "EGLE / MDHHS, July 2018",
            },
            {
                "analyte": "PFOA",
                "value": 670, "unit": "ppt",
                "medium": "public drinking water",
                "location": "City of Parchment municipal supply",
                "standard": _HA_2016,
                "source": "EGLE / MDHHS, July 2018 (about 1,410 ppt combined "
                          "PFOS+PFOA; ~1,600 ppt total PFAS)",
            },
        ],
        "advisories": [
            {
                "text": "A “Do Not Drink” advisory and state of emergency were "
                        "issued in July 2018; within about a month Parchment was "
                        "connected to the City of Kalamazoo's water system and the "
                        "advisory was lifted.",
                "source": "State of Michigan / EGLE, 2018",
            },
        ],
        "status": (
            "Parchment was permanently switched to Kalamazoo's water supply. A "
            "$11.9 million settlement was later reached with affected residents; the "
            "Crown Vantage source property remains under EGLE/MPART investigation."
        ),
        "refs": [
            {"label": "MPART — Parchment / Cooper Township drinking-water response",
             "url": "https://www.michigan.gov/pfasresponse/drinking-water/statewide-survey/parchment"},
            {"label": "MPART — Crown Vantage Property (Kalamazoo County)",
             "url": "https://www.michigan.gov/pfasresponse/investigations/sites-aoi/kalamazoo-county/crown-vantage-property"},
            {"label": "WaterWorld — $11.9M Parchment PFAS settlement",
             "url": "https://www.waterworld.com/residential-commercial/news/14306792/119-million-settlement-reached-in-lawsuit-for-parchment-michigan-drinking-water-contaminated-with-pfas"},
        ],
    },
]


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def narrative_for(name: str, county_fips: str | None) -> dict | None:
    """Return the curated narrative whose county + name tokens match this live
    MPART record, or None. Matching is county-scoped so a name token can't attach
    to a same-named site in the wrong county."""
    n = _norm(name)
    if not n:
        return None
    for rec in PFAS_NARRATIVES:
        if county_fips and rec.get("county_fips") and county_fips != rec["county_fips"]:
            continue
        if any(_norm(tok) in n for tok in rec.get("match_names", [])):
            return rec
    return None
