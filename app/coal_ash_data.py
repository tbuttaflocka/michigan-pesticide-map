"""Curated directory of Michigan's coal combustion residuals (CCR / "coal ash") sites.

WHY THIS IS A DIRECTORY, NOT A LIVE FEED
----------------------------------------
Unlike the app's other layers, there is no central queryable database of coal-ash
monitoring results. The federal CCR rule is *self-implementing*: each utility must
post its OWN compliance data — groundwater monitoring, closure plans, structural-
integrity assessments — on its OWN public website. So this layer is a curated
directory (like the spraying-programs one): it points to each operator's official
CCR page where the required data actually lives, rather than aggregating live
results.

Because Michigan has a bounded, knowable set of sites, this list aims to be
essentially COMPLETE rather than a misleading partial curation. It mirrors EPA's
own "List of Publicly Accessible Internet Sites Hosting CCR Compliance Data,"
which enumerates 17 Michigan CCR facilities (the "~29 coal ash sites" often cited
counts individual UNITS — ponds + landfills + legacy impoundments — across these
facilities, not 29 separate plants).

ACCURACY RULES honored when compiling this list (public map — no fabrication):
  * Every facility, its operator, status, and CCR page was web-verified against a
    real source (the operator's CCR page, EPA's CCR site list, EGLE, Earthjustice/
    EIP Ashtracker, utility retirement notices, or Wikipedia for coordinates).
  * Coordinates come from Wikipedia power-plant infoboxes or from geocoding the
    facility's real street address (US Census geocoder). A handful that could only
    be pinned to the plant's town/site are flagged ``approx``.
  * Contamination is NEVER stated as established fact. Groundwater contaminant
    findings are attributed to the third parties that reported them (Earthjustice
    / Environmental Integrity Project, from utilities' own 2015-2021 CCR monitoring
    disclosures), and the utilities' dispute is stated alongside.
  * Where a field could not be verified it is left empty/None rather than guessed.

Sources are listed per-entry (``ccr_url``) and app-wide in the Data Sources modal.
"""

# ---- Marker sub-styling -------------------------------------------------------
# Color encodes CLOSURE STATUS; the marker letter encodes UNIT TYPE (P = ash pond
# / surface impoundment, L = CCR landfill, P+L = both). Unlined units are flagged
# with a warning ring in the UI (see the ``unlined`` field) — those are the
# higher-risk ones the CCR rule most concerns.
STATUS_META = {
    "active":       ("#f85149", "Active / operating"),
    "cap_in_place": ("#e3a008", "Closing — cap in place"),
    "removal":      ("#3fb950", "Closing — by removal"),
    "closed":       ("#8b949e", "Retired / closed"),
    "legacy":       ("#bc8cff", "Legacy impoundment (2024 rule)"),
}

# Unit-type marker letter.
UNIT_TYPE_LABEL = {
    "pond":    ("P",   "Ash pond / surface impoundment"),
    "landfill":("L",   "CCR landfill"),
    "mixed":   ("P+L", "Ash pond(s) + landfill"),
}

# Shared attribution string for third-party groundwater findings.
_EIP_ATTRIB = (
    "Reported by Earthjustice / the Environmental Integrity Project (Ashtracker), "
    "from the utilities' OWN 2015–2021 CCR groundwater-monitoring disclosures. "
    "Michigan utilities dispute these conclusions, arguing the reports lack context "
    "(e.g. that drinking-water sources were not shown to be affected). These are "
    "monitoring exceedances near the ash units, not a finding about any drinking well."
)

# DTE post-2017 heavy-metal data gap (attributed; with DTE's rebuttal).
_DTE_GAP = (
    "Data gap: per the Michigan Environmental Council (reported by Downtown "
    "Publications, Feb 2022), DTE has not provided groundwater HEAVY-METAL test "
    "data after 2017 for this site, contending the clay walls of its ash ponds are "
    "dense enough to hold leachate. DTE disputes this characterization, saying it "
    "samples groundwater every six months and submits results to EPA."
)
# The three retired DTE plants have no entry at all on DTE's public CCR page.
_DTE_NOPAGE = (
    "Note: this retired plant is NOT listed on DTE's public CCR compliance page "
    "(verified) — its coal-ash units are not among the compliance data DTE posts "
    "there. Any legacy impoundment here may fall under EPA's 2024 Legacy CCR Rule."
)

# CCR page URLs (each verified to resolve).
_DTE_CCR = ("https://www.dteenergy.com/us/en/residential/community-and-news/environment/"
            "Coal-Combustion-Residual-Rule-Compliance-Data-and-Information.html")
_CE_CCR = ("https://www.consumersenergy.com/about-us/sustainability/environment/"
           "waste-management/coal-combustion-residuals")
_MERG_CCR = "https://merg-ccrrule.com"
_LBWL_CCR = "https://www.lbwl.com/ccr-rule-compliance-data-and-information"
_HOLLAND_CCR = "https://hollandbpw.com/en/about-us/publications"
_GHBLP_CCR = "https://ghblp.org/environmental-compliance-reports/coal-combustion-residuals-compliance/"
_MBLP_CCR = "https://mblp.org/public-notices/"
_WE_CCR = "https://www.we-energies.com/environment/coal-combustion"
_HARBORBEACH_CCR = "https://www.ccrsites.com/harbor-beach"
_MORROW_CCR = "https://www.morrowacquisitioncompany.com/"

# Each site: id, name, operator, lat, lon, county, city, unit_kind (pond|landfill|
# mixed), units (human list), unlined (bool — has a confirmed unlined unit),
# status (key into STATUS_META), plant_status, closure, contaminants (clickable),
# contaminant_source, data_gap (str|None), ccr_url, ccr_host, notes, source, approx.
COAL_ASH_SITES = [
    # ============================ DTE Electric ============================= #
    {
        "id": "dte-monroe",
        "name": "Monroe Power Plant",
        "operator": "DTE Energy (DTE Electric)",
        "lat": 41.88917, "lon": -83.34556, "county": "Monroe", "city": "Monroe",
        "unit_kind": "mixed",
        "units": ["Bottom ash impoundment (closure in progress)",
                  "Fly ash impoundment (post-closure)", "On-site CCR landfill"],
        "unlined": False,
        "status": "cap_in_place",
        "plant_status": "Operating — DTE plans to retire two units in 2028 and the "
                        "remaining two by 2032. Michigan's single largest coal-ash "
                        "producer: about 56% of the state's ~1.44 million tons of "
                        "coal ash generated each year.",
        "closure": "Impoundments closing (closure/post-closure); groundwater "
                   "monitoring reports posted 2022–2025.",
        "contaminants": ["boron", "lithium", "sulfate", "chloride", "calcium"],
        "contaminant_source": _EIP_ATTRIB + " At Monroe, EIP reported lithium and "
                              "sulfate at about three times EPA's safe level, plus "
                              "boron, chloride and calcium exceedances.",
        "data_gap": _DTE_GAP,
        "ccr_url": _DTE_CCR, "ccr_host": "DTE Energy",
        "notes": "", "source": "DTE Energy CCR page; EPA CCR site list; Earthjustice/EIP",
        "approx": False,
    },
    {
        "id": "dte-belle-river",
        "name": "Belle River Power Plant",
        "operator": "DTE Energy (DTE Electric)",
        "lat": 42.77389, "lon": -82.49500, "county": "St. Clair", "city": "East China",
        "unit_kind": "mixed",
        "units": ["Bottom ash impoundment (retrofit completed; closure in progress)",
                  "Range Road Landfill (active CCR landfill)"],
        "unlined": False,
        "status": "active",
        "plant_status": "Operating; DTE plans full conversion to natural gas by 2026.",
        "closure": "Bottom ash impoundment retrofit done, closure underway; Range "
                   "Road Landfill active. Groundwater monitoring reports posted 2017–2025.",
        "contaminants": ["boron", "cobalt", "lithium", "molybdenum"],
        "contaminant_source": _EIP_ATTRIB,
        "data_gap": _DTE_GAP,
        "ccr_url": _DTE_CCR, "ccr_host": "DTE Energy",
        "notes": "", "source": "DTE Energy CCR page; EPA CCR site list; Earthjustice/EIP",
        "approx": False,
    },
    {
        "id": "dte-st-clair",
        "name": "St. Clair Power Plant",
        "operator": "DTE Energy (DTE Electric)",
        "lat": 42.76444, "lon": -82.47250, "county": "St. Clair", "city": "East China",
        "unit_kind": "pond",
        "units": ["2 ash ponds / surface impoundments (per EPA CCR site list)"],
        "unlined": False,
        "status": "closed",
        "plant_status": "Retired — final coal units shut down May 2022.",
        "closure": "Closure status of impoundments not published on DTE's CCR page.",
        "contaminants": ["boron", "lithium"],
        "contaminant_source": _EIP_ATTRIB,
        "data_gap": _DTE_GAP + " " + _DTE_NOPAGE,
        "ccr_url": _DTE_CCR, "ccr_host": "DTE Energy",
        "notes": "", "source": "EPA CCR site list; Earthjustice/EIP; retirement notices",
        "approx": False,
    },
    {
        "id": "dte-trenton-channel",
        "name": "Trenton Channel Power Plant",
        "operator": "DTE Energy (DTE Electric)",
        "lat": 42.12222, "lon": -83.18139, "county": "Wayne", "city": "Trenton",
        "unit_kind": "landfill",
        "units": ["CCR landfill / impoundment(s) (per EPA CCR site list)"],
        "unlined": False,
        "status": "closed",
        "plant_status": "Retired 2022 and demolished; DTE is building a battery-"
                        "storage facility on the site.",
        "closure": "Closure status of coal-ash units not published on DTE's CCR page.",
        "contaminants": ["arsenic", "boron", "lithium", "radium", "sulfate"],
        "contaminant_source": _EIP_ATTRIB + " Earthjustice's table flags arsenic "
                              "(~38×), radium-226/228 (~9×), sulfate (~7×) and "
                              "lithium (~6×) among the highest exceedances in the state.",
        "data_gap": _DTE_GAP + " " + _DTE_NOPAGE,
        "ccr_url": _DTE_CCR, "ccr_host": "DTE Energy",
        "notes": "", "source": "EPA CCR site list; Earthjustice/EIP; retirement notices",
        "approx": False,
    },
    {
        "id": "dte-river-rouge",
        "name": "River Rouge Power Plant",
        "operator": "DTE Energy (DTE Electric)",
        "lat": 42.27400, "lon": -83.11240, "county": "Wayne", "city": "River Rouge",
        "unit_kind": "pond",
        "units": ["Ash pond / surface impoundment (per EPA CCR site list)"],
        "unlined": False,
        "status": "closed",
        "plant_status": "Retired 2021.",
        "closure": "Closure status of impoundment not published on DTE's CCR page.",
        "contaminants": ["arsenic", "boron", "lithium", "molybdenum"],
        "contaminant_source": _EIP_ATTRIB,
        "data_gap": _DTE_NOPAGE,
        "ccr_url": _DTE_CCR, "ccr_host": "DTE Energy",
        "notes": "", "source": "EPA CCR site list; Earthjustice/EIP; retirement notices",
        "approx": False,
    },
    # ========================== Consumers Energy ========================== #
    {
        "id": "ce-campbell",
        "name": "J.H. Campbell Generating Plant",
        "operator": "Consumers Energy",
        "lat": 42.91208, "lon": -86.20231, "county": "Ottawa", "city": "West Olive",
        "unit_kind": "mixed",
        "units": ["Pond A (UNLINED — closure by removal, begun 2018)",
                  "Bottom Ash Ponds 1–2 (closure by removal, certified 2023)",
                  "Bottom Ash Pond 3 (closure by removal, certified 2023)",
                  "Dry Ash Landfill (double-lined, active) + Cells 5 & 6"],
        "unlined": True,
        "status": "removal",
        "plant_status": "Its coal units were scheduled to retire in May 2025 but were "
                        "kept running past that date under a U.S. DOE emergency order.",
        "closure": "Ash ponds being closed BY REMOVAL; ash now goes to an on-site "
                   "double-lined landfill. A separate project (Ashcor, 2025) plans "
                   "to excavate and repurpose decades of impounded ash.",
        "contaminants": ["antimony", "arsenic", "cobalt", "lithium", "molybdenum",
                         "selenium", "thallium"],
        "contaminant_source": _EIP_ATTRIB + " Earthjustice's table flags arsenic "
                              "(~29×) among the exceedances.",
        "data_gap": None,
        "ccr_url": _CE_CCR, "ccr_host": "Consumers Energy",
        "notes": "", "source": "Consumers Energy CCR page; EPA CCR site list; Earthjustice/EIP",
        "approx": False,
    },
    {
        "id": "ce-karn",
        "name": "Dan E. Karn Generating Plant",
        "operator": "Consumers Energy",
        "lat": 43.64457, "lon": -83.84007, "county": "Bay", "city": "Essexville",
        "unit_kind": "pond",
        "units": ["Bottom Ash Pond (closure by removal; remedy selected 2025)",
                  "Karn Lined Impoundment (closure by removal, certified 2025)"],
        "unlined": False,
        "status": "removal",
        "plant_status": "Coal units retired in 2023.",
        "closure": "Closure by removal.",
        "contaminants": ["arsenic", "boron", "cobalt", "lead", "molybdenum", "sulfate"],
        "contaminant_source": _EIP_ATTRIB + " EIP's 2019 report specifically cited "
                              "cobalt, molybdenum and sulfate at Karn; Earthjustice's "
                              "table also flags arsenic (~45×) and lead.",
        "data_gap": None,
        "ccr_url": _CE_CCR, "ccr_host": "Consumers Energy",
        "notes": "Part of the Karn/Weadock generating complex in Essexville.",
        "source": "Consumers Energy CCR page; EPA CCR site list; Earthjustice/EIP",
        "approx": False,
    },
    {
        "id": "ce-weadock",
        "name": "J.C. Weadock Generating Plant",
        "operator": "Consumers Energy",
        "lat": 43.64209, "lon": -83.83819, "county": "Bay", "city": "Essexville",
        "unit_kind": "mixed",
        "units": ["Bottom Ash Pond (closure by removal, certified 2023)",
                  "Dry Ash Landfill (double-lined, active)"],
        "unlined": False,
        "status": "removal",
        "plant_status": "Retired April 2016.",
        "closure": "Closure by removal; active double-lined landfill.",
        "contaminants": ["arsenic", "beryllium", "boron", "cobalt", "lithium",
                         "molybdenum", "sulfate", "thallium"],
        "contaminant_source": _EIP_ATTRIB + " EIP's 2019 report specifically cited "
                              "arsenic, beryllium, cobalt, lithium and sulfate at Weadock.",
        "data_gap": None,
        "ccr_url": _CE_CCR, "ccr_host": "Consumers Energy",
        "notes": "Part of the Karn/Weadock generating complex in Essexville.",
        "source": "Consumers Energy CCR page; EPA CCR site list; Earthjustice/EIP",
        "approx": False,
    },
    {
        "id": "ce-whiting",
        "name": "J.R. Whiting Generating Plant",
        "operator": "Consumers Energy",
        "lat": 41.79452, "lon": -83.45149, "county": "Monroe", "city": "Erie",
        "unit_kind": "pond",
        "units": ["Ponds 1 & 2 (closed; construction completed 2020)",
                  "Pond 6 (closed December 2017)"],
        "unlined": False,
        "status": "closed",
        "plant_status": "Retired April 2016 and since demolished.",
        "closure": "Impoundments closed.",
        "contaminants": ["cobalt", "lithium", "thallium"],
        "contaminant_source": _EIP_ATTRIB,
        "data_gap": None,
        "ccr_url": _CE_CCR, "ccr_host": "Consumers Energy",
        "notes": "", "source": "Consumers Energy CCR page; EPA CCR site list; Earthjustice/EIP",
        "approx": False,
    },
    {
        "id": "ce-cobb",
        "name": "B.C. Cobb Generating Facility",
        "operator": "Consumers Energy (ash ponds now Charah Solutions / MERG)",
        "lat": 43.25501, "lon": -86.23839, "county": "Muskegon", "city": "Muskegon",
        "unit_kind": "pond",
        "units": ["Ash Ponds 0–8 (closure by removal)"],
        "unlined": False,
        "status": "removal",
        "plant_status": "Retired 2016.",
        "closure": "Ash ponds closing BY REMOVAL. Ownership of the ponds was "
                   "transferred to Charah Solutions' subsidiary MERG (Muskegon "
                   "Environmental Redevelopment Group, LLC), which maintains the "
                   "current CCR documents on its own site; Consumers keeps archives.",
        "contaminants": ["arsenic", "boron", "lithium", "molybdenum", "radium"],
        "contaminant_source": _EIP_ATTRIB,
        "data_gap": None,
        "ccr_url": _MERG_CCR, "ccr_host": "Charah / MERG (merg-ccrrule.com)",
        "notes": "Excavated ash is hauled to Consumers' licensed J.C. Weadock "
                 "landfill in Essexville.",
        "source": "Consumers Energy CCR page; MERG CCR site; EPA CCR site list; Earthjustice/EIP",
        "approx": False,
    },
    # ===================== Municipal / public utilities ==================== #
    {
        "id": "lbwl-erickson",
        "name": "Erickson Power Station",
        "operator": "Lansing Board of Water & Light (LBWL)",
        "lat": 42.69109, "lon": -84.66198, "county": "Eaton", "city": "Delta Township (Lansing)",
        "unit_kind": "pond",
        "units": ["3 lined surface impoundments — Forebay, Retention Basin, Clear Water Pond"],
        "unlined": False,
        "status": "removal",
        "plant_status": "Retired November 2022 (replaced by the gas-fired Delta Energy Park).",
        "closure": "Closure BY REMOVAL — dewatered and ash/liner excavated in 2023, "
                   "hauled to the Granger landfill; now in CCR assessment monitoring.",
        "contaminants": ["boron", "lithium", "molybdenum", "sulfate", "calcium"],
        "contaminant_source": "From LBWL's OWN CCR assessment-monitoring: groundwater "
                              "exceedances of boron, lithium, molybdenum, sulfate, "
                              "calcium and total dissolved solids have been reported "
                              "in the glacial aquifer near the impoundments; residents "
                              "have raised concerns (WKAR/WILX, 2026).",
        "data_gap": None,
        "ccr_url": _LBWL_CCR, "ccr_host": "Lansing Board of Water & Light",
        "notes": "", "source": "LBWL CCR page; EPA CCR site list",
        "approx": False,
    },
    {
        "id": "holland-deyoung",
        "name": "James De Young Generating Station",
        "operator": "Holland Board of Public Works",
        "lat": 42.7889, "lon": -86.1089, "county": "Ottawa", "city": "Holland",
        "unit_kind": "pond",
        "units": ["Ash ponds / surface impoundments (per EPA CCR site list)"],
        "unlined": False,
        "status": "closed",
        "plant_status": "Coal generation retired (mid-2010s); site on Lake Macatawa.",
        "closure": "See the utility's CCR/compliance publications for closure status.",
        "contaminants": [],
        "contaminant_source": "",
        "data_gap": None,
        "ccr_url": _HOLLAND_CCR, "ccr_host": "Holland Board of Public Works",
        "notes": "", "source": "EPA CCR site list; Holland BPW publications",
        "approx": True,
    },
    {
        "id": "ghblp-sims",
        "name": "J.B. Sims Generating Station",
        "operator": "Grand Haven Board of Light & Power",
        "lat": 43.0636, "lon": -86.2447, "county": "Ottawa", "city": "Grand Haven (Harbor Island)",
        "unit_kind": "pond",
        "units": ["Units 1/2 inactive ash impoundment (UNLINED)",
                  "Unit 3 East & West ash impoundments (lined)"],
        "unlined": True,
        "status": "closed",
        "plant_status": "Boiler operations ceased February 2020; impoundments stopped "
                        "receiving ash August 2020.",
        "closure": "Closure ongoing; the strategy has been complicated by PFAS found "
                   "in 2021. The City of Grand Haven now manages the site through its "
                   "'Renew Harbor Island' program.",
        "contaminants": [],
        "contaminant_source": "",
        "data_gap": None,
        "ccr_url": _GHBLP_CCR, "ccr_host": "Grand Haven Board of Light & Power",
        "notes": "Post-2022 records are on the City of Grand Haven 'Renew Harbor "
                 "Island' site (renewharborisland.org).",
        "source": "GHBLP CCR page; EPA CCR site list; MI PFAS response",
        "approx": True,
    },
    {
        "id": "mblp-shiras",
        "name": "Shiras Steam Plant",
        "operator": "Marquette Board of Light & Power",
        "lat": 46.5375, "lon": -87.3886, "county": "Marquette", "city": "Marquette",
        "unit_kind": "pond",
        "units": ["Ash pond / surface impoundment (per EPA CCR site list)"],
        "unlined": False,
        "status": "closed",
        "plant_status": "Retired; demolition began 2020.",
        "closure": "See the utility's CCR/compliance notices for closure status.",
        "contaminants": [],
        "contaminant_source": "",
        "data_gap": None,
        "ccr_url": _MBLP_CCR, "ccr_host": "Marquette Board of Light & Power",
        "notes": "", "source": "EPA CCR site list; MBLP public notices",
        "approx": True,
    },
    # ======================== Industrial / other =========================== #
    {
        "id": "we-presque-isle",
        "name": "Presque Isle Power Plant",
        "operator": "We Energies (Wisconsin Electric)",
        "lat": 46.57694, "lon": -87.39299, "county": "Marquette", "city": "Marquette",
        "unit_kind": "landfill",
        "units": ["CCR landfill (per EPA CCR site list)"],
        "unlined": False,
        "status": "closed",
        "plant_status": "Coal units retired 2019.",
        "closure": "See We Energies' CCR page for closure/monitoring status.",
        "contaminants": ["lead", "selenium"],
        "contaminant_source": "Reported at unsafe levels via Ashtracker (Earthjustice/"
                              "EIP), from CCR monitoring data; the operator may dispute "
                              "the interpretation.",
        "data_gap": None,
        "ccr_url": _WE_CCR, "ccr_host": "We Energies",
        "notes": "", "source": "EPA CCR site list; We Energies CCR page; Ashtracker",
        "approx": False,
    },
    {
        "id": "harbor-beach-legacy",
        "name": "Harbor Beach Power Plant (legacy impoundment)",
        "operator": "Harbor Beach Development LLC (former DTE plant)",
        "lat": 43.85172, "lon": -82.65170, "county": "Huron", "city": "Harbor Beach",
        "unit_kind": "pond",
        "units": ["1 legacy CCR surface impoundment"],
        "unlined": False,
        "status": "legacy",
        "plant_status": "Retired coal plant; the site's impoundment is regulated as a "
                        "LEGACY CCR surface impoundment under EPA's 2024 rule.",
        "closure": "Now covered by the 2024 Legacy CCR Rule (previously exempt).",
        "contaminants": [],
        "contaminant_source": "",
        "data_gap": None,
        "ccr_url": _HARBORBEACH_CCR, "ccr_host": "Harbor Beach Development (ccrsites.com)",
        "notes": "", "source": "EPA CCR site list (legacy impoundment)",
        "approx": False,
    },
    {
        "id": "morrow-legacy",
        "name": "Morrow (legacy impoundment)",
        "operator": "Morrow Acquisition Co.",
        "lat": 42.2895, "lon": -85.4720, "county": "Kalamazoo", "city": "Comstock Township",
        "unit_kind": "pond",
        "units": ["1 legacy CCR surface impoundment"],
        "unlined": False,
        "status": "legacy",
        "plant_status": "Former coal site; impoundment regulated as a LEGACY CCR "
                        "surface impoundment under EPA's 2024 rule.",
        "closure": "Now covered by the 2024 Legacy CCR Rule (previously exempt).",
        "contaminants": [],
        "contaminant_source": "",
        "data_gap": None,
        "ccr_url": _MORROW_CCR, "ccr_host": "Morrow Acquisition Co.",
        "notes": "Location approximate (Comstock Township / Morrow Lake area).",
        "source": "EPA CCR site list (legacy impoundment)",
        "approx": True,
    },
]


def sites_payload() -> dict:
    """Directory + legends, in the JSON shape the frontend consumes."""
    statuses = [{"key": k, "color": c, "label": lbl}
                for k, (c, lbl) in STATUS_META.items()]
    unit_types = [{"key": k, "letter": ltr, "label": lbl}
                  for k, (ltr, lbl) in UNIT_TYPE_LABEL.items()]
    out = []
    for s in COAL_ASH_SITES:
        color, status_label = STATUS_META.get(s["status"], STATUS_META["closed"])
        letter, unit_label = UNIT_TYPE_LABEL.get(s["unit_kind"], UNIT_TYPE_LABEL["pond"])
        out.append({
            **s,
            "color": color,
            "status_label": status_label,
            "unit_letter": letter,
            "unit_type_label": unit_label,
        })
    return {"count": len(out), "statuses": statuses, "unit_types": unit_types,
            "sites": out}
