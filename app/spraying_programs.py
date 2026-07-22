"""Curated directory of Michigan's organized, publicly-documented pest-control
spraying programs.

This is an informational DIRECTORY — who runs what, where, and the official page
where residents get the CURRENT schedule — not a live feed of specific spray
dates (no central Michigan source publishes those, and scraping them would be
unreliable). Each entry links to its official program page.

Accuracy rules honored when compiling this list:
  * Every entry has a real, verifiable official page (the ``url`` field).
  * MICHIGAN ONLY. Spongy-moth and mosquito programs exist in many states; none
    of those are included here.
  * Where a specific detail (exact administrator or pesticide) could not be
    verified from the official source, that field is left empty rather than
    guessed. Accurate-and-incomplete beats padded-with-guesses.

It is NOT a complete list of all spraying in Michigan — private agricultural
spraying and many ad-hoc local treatments are not organized programs with a
public page and are not included. See the caveat shown on the map layer.

Coordinates: county-wide programs are placed at (approximately) the county
center; city/township programs at the municipality; statewide programs at the
administering agency's Lansing headquarters (the popup states "Statewide").
"""

# type key -> (glyph, marker color, human label)
TYPE_META = {
    "spongy_moth":        ("🌲", "#5dbb63", "Spongy moth suppression"),
    "mosquito":           ("🦟", "#3aa5b8", "Mosquito abatement"),
    "arbovirus_response": ("🚁", "#e8873c", "Arbovirus (EEE / West Nile) aerial response"),
    "other":              ("ℹ", "#9aa4b2", "Statewide information / regulatory"),
}

# Each program: id, name, type, area, scope (county|city|township|statewide),
# administrator, pesticides (clickable in the popup), season, description, url,
# source, lat, lon. Empty administrator/pesticides == "not verified", omitted.
SPRAYING_PROGRAMS = [
    # ---------------- Spongy moth (formerly gypsy moth) suppression --------- #
    {
        "id": "midland-spongy-moth",
        "name": "Midland County Spongy Moth Suppression Program",
        "type": "spongy_moth",
        "area": "Midland County",
        "scope": "county",
        "administrator": "Aquatic Consulting Services II LLC (county millage-funded)",
        "pesticides": ["Btk"],
        "season": "Spring — aerial treatment, typically late May",
        "description": "County millage-funded program begun in 1986 after severe "
                       "defoliation of the county's forest cover. Monitors egg-mass "
                       "densities and aerially treats residential areas to suppress "
                       "spongy moth caterpillars.",
        "url": "https://midlandcountymi.gov/spongymoth",
        "source": "Midland County, MI",
        "lat": 43.65, "lon": -84.38,
    },
    {
        "id": "macomb-spongy-moth",
        "name": "Macomb County Spongy Moth Suppression Program",
        "type": "spongy_moth",
        "area": "Macomb County",
        "scope": "county",
        "administrator": "MSU Extension — Macomb County",
        "pesticides": ["Btk"],
        "season": "Spring — treatment timed to early caterpillar stage",
        "description": "Established in 1993 and administered by MSU Extension. Runs "
                       "egg-mass surveys to identify qualifying areas (aiming to "
                       "prevent more than ~40% defoliation) and treats eligible "
                       "rural and urban properties. Spongy moth hotline: 586-469-6432.",
        "url": "https://www.macombgov.org/departments/msu-extension-services/program-areas/natural-resources/lymantria-dispar",
        "source": "Macomb County / MSU Extension",
        "lat": 42.70, "lon": -82.92,
    },
    {
        "id": "kentwood-spongy-moth",
        "name": "City of Kentwood Spongy Moth Spraying Program",
        "type": "spongy_moth",
        "area": "City of Kentwood (Kent County)",
        "scope": "city",
        "administrator": "Hamilton Helicopters, Inc. (city-contracted)",
        "pesticides": ["Btk"],
        "season": "May or June — aerial, weather-dependent",
        "description": "The City of Kentwood contracts Hamilton Helicopters for an "
                       "aerial spongy moth treatment in May or June using a Bt product "
                       "(Foray 76B). Affected properties are notified by direct mail.",
        "url": "https://www.kentwood.us/living_in/gypsy_moth_spraying_program.php",
        "source": "City of Kentwood, MI",
        "lat": 42.8695, "lon": -85.6447,
    },
    {
        "id": "shelby-twp-spongy-moth",
        "name": "Shelby Township Spongy Moth Suppression",
        "type": "spongy_moth",
        "area": "Shelby Township (Macomb County)",
        "scope": "township",
        "administrator": "",
        "pesticides": ["Btk"],
        "season": "Spring — aerial treatment",
        "description": "Shelby Township runs its own spongy moth suppression, "
                       "surveying egg masses and aerially treating qualifying areas "
                       "within the township. See the official page for current-year "
                       "treatment status and notices.",
        "url": "https://www.shelbytwp.org/government/departments/supervisor-s-office/spongy-moth-suppression",
        "source": "Shelby Township, MI",
        "lat": 42.6706, "lon": -83.0330,
    },
    {
        "id": "walker-spongy-moth",
        "name": "City of Walker Spongy Moth Program",
        "type": "spongy_moth",
        "area": "City of Walker (Kent County)",
        "scope": "city",
        "administrator": "",
        "pesticides": ["Btk"],
        "season": "Spring — aerial treatment",
        "description": "The City of Walker provides spongy moth information and, in "
                       "high-population years, aerial Bt treatment of affected areas. "
                       "Check the official page for the current year's plan.",
        "url": "https://www.walkermi.gov/352/Spongy-Moth",
        "source": "City of Walker, MI",
        "lat": 42.9887, "lon": -85.7686,
    },
    {
        "id": "deep-river-spongy-moth",
        "name": "Deep River Township Spongy Moth Suppression",
        "type": "spongy_moth",
        "area": "Deep River Township (Arenac County)",
        "scope": "township",
        "administrator": "",
        "pesticides": ["Btk"],
        "season": "Spring — aerial treatment",
        "description": "Deep River Township maintains a spongy (formerly gypsy) moth "
                       "suppression program with aerial Bt treatment of qualifying "
                       "areas. See the official page for eligibility and current "
                       "notices.",
        "url": "https://deeprivertwp.org/gypsy-spongy-moth-suppression/",
        "source": "Deep River Township, MI",
        "lat": 44.03, "lon": -83.90,
    },
    # ---------------- County mosquito-abatement districts ------------------- #
    {
        "id": "saginaw-mosquito",
        "name": "Saginaw County Mosquito Abatement Commission",
        "type": "mosquito",
        "area": "Saginaw County",
        "scope": "county",
        "administrator": "Saginaw County Mosquito Abatement Commission",
        "pesticides": ["permethrin"],
        "season": "Spring–summer — larval control plus adult (ULV) treatment",
        "description": "Funded county-wide mosquito control operating since 1977, "
                       "serving all of Saginaw County. Combines larval control with "
                       "adult (adulticide) treatment; its principal adulticide is a "
                       "4% permethrin ULV formulation. Residents may request or "
                       "decline treatment: (989) 755-5751.",
        "url": "https://www.saginawmosquito.com/",
        "source": "Saginaw County Mosquito Abatement Commission",
        "lat": 43.33, "lon": -84.05,
    },
    {
        "id": "bay-mosquito",
        "name": "Bay County Mosquito Control",
        "type": "mosquito",
        "area": "Bay County",
        "scope": "county",
        "administrator": "Bay County Mosquito Control",
        "pesticides": [],
        "season": "Spring–summer — surveillance-driven larval & adult treatment",
        "description": "County mosquito-control program whose biology department "
                       "times treatment from larval and adult mosquito surveys, "
                       "including an aerial spring treatment. See the official page "
                       "(and its product labels) for current treatments and notices.",
        "url": "https://www.baycountymi.gov/health_community/mosquito_control/index.php",
        "source": "Bay County, MI",
        "lat": 43.68, "lon": -83.92,
    },
    {
        "id": "midland-mosquito",
        "name": "Midland County Mosquito Control",
        "type": "mosquito",
        "area": "Midland County",
        "scope": "county",
        "administrator": "Midland County Mosquito Control",
        "pesticides": [],
        "season": "Spring–summer — aerial larval treatment of standing water",
        "description": "County mosquito-control program that includes aerial "
                       "treatment of standing water to control mosquito larvae "
                       "county-wide, plus surveillance and response. Residents can "
                       "sign up for treatment notifications on the official page.",
        "url": "https://midlandcountymi.gov/mosquito-control",
        "source": "Midland County, MI",
        "lat": 43.6156, "lon": -84.2472,
    },
    {
        "id": "tuscola-mosquito",
        "name": "Tuscola County Mosquito Abatement",
        "type": "mosquito",
        "area": "Tuscola County",
        "scope": "county",
        "administrator": "Tuscola County Mosquito Abatement",
        "pesticides": [],
        "season": "Spring–summer — larval control plus adult (ULV) treatment",
        "description": "One of Michigan's formal, comprehensive county mosquito-"
                       "control programs (with Saginaw, Bay, and Midland). Combines "
                       "larval control with adult treatment. Office: (989) 672-3748. "
                       "See the official page for annual program plans and notices.",
        "url": "https://www.tuscolacounty.org/mosquito/",
        "source": "Tuscola County, MI",
        "lat": 43.49, "lon": -83.44,
    },
    # ---------------- State arbovirus (EEE / West Nile) response ------------- #
    {
        "id": "mdhhs-arbovirus",
        "name": "MDHHS Arbovirus (EEE / West Nile) Aerial Treatment Response",
        "type": "arbovirus_response",
        "area": "Statewide — outbreak-year target counties",
        "scope": "statewide",
        "administrator": "Michigan Dept. of Health & Human Services (MDHHS), with local health departments",
        "pesticides": [],
        "season": "Late summer / fall of outbreak years only",
        "description": "In years with elevated Eastern Equine Encephalitis (EEE) or "
                       "West Nile virus risk, MDHHS and local health departments may "
                       "conduct aerial ULV adulticide treatment over targeted high-"
                       "risk counties (e.g. the 2019–2020 EEE responses). This is an "
                       "outbreak-driven emergency response, not an annual program. "
                       "Current-year information: Michigan.gov/EEE.",
        "url": "https://www.michigan.gov/emergingdiseases/home/eastern-equine-encephalitis",
        "source": "MDHHS Emerging Diseases",
        "lat": 42.7335, "lon": -84.5467,
    },
    # ---------------- State regulatory / context ---------------------------- #
    {
        "id": "mdard-spongy-moth-info",
        "name": "Michigan Spongy Moth Information (MDARD / DNR)",
        "type": "other",
        "area": "Statewide — regulatory & guidance",
        "scope": "statewide",
        "administrator": "Michigan Dept. of Agriculture & Rural Development (MDARD) / Michigan DNR",
        "pesticides": [],
        "season": "n/a — information and regulatory context",
        "description": "Statewide context for spongy moth: MDARD and the Michigan "
                       "Invasive Species Program track populations, publish annual "
                       "outlooks, and set regulatory treatment guidance. Local "
                       "suppression spraying is run by counties and municipalities "
                       "(the other entries on this layer), not the state.",
        "url": "https://www.michigan.gov/invasives/id-report/insects/spongy-moth",
        "source": "MDARD / Michigan Invasive Species Program",
        "lat": 42.7089, "lon": -84.5622,
    },
]


def programs_payload() -> dict:
    """Directory + type legend, in the JSON shape the frontend consumes."""
    types = [{"key": k, "glyph": g, "color": c, "label": lbl}
             for k, (g, c, lbl) in TYPE_META.items()]
    out = []
    for p in SPRAYING_PROGRAMS:
        glyph, color, label = TYPE_META.get(p["type"], TYPE_META["other"])
        out.append({
            **p,
            "type_label": label,
            "glyph": glyph,
            "color": color,
        })
    return {"count": len(out), "types": types, "programs": out}
