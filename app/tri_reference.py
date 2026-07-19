"""
Reference lookups for the TRI drill-down (facility company summaries + chemical
info popups).

These are small, hand-curated references for the operators and chemicals that
recur in Michigan's TRI data, so a click on a facility or chemical name in the
county panel can show a plain-language summary. Nothing here is invented: the
operator blurbs describe what the company/plant does, and the chemical entries
carry sourced EPA/IARC hazard classifications. When a facility or chemical is
not in the lookup, the callers fall back to a *factual* summary generated from
the data we actually have (industry sector + reported chemicals / CAS) rather
than fabricating detail.
"""
from __future__ import annotations


# --------------------------------------------------------------------------- #
# Major recurring Michigan operators. Keys are UPPERCASE substrings matched     #
# against a facility's parent company + facility name.                          #
# --------------------------------------------------------------------------- #

OPERATOR_PROFILES: dict[str, str] = {
    "US ECOLOGY": (
        "US Ecology's Wayne Disposal site (Belleville) is one of the region's "
        "largest hazardous- and industrial-waste landfills. Most of its reported "
        "total is on-site land disposal of waste received from other sites."),
    "WAYNE DISPOSAL": (
        "Wayne Disposal (Belleville) is a large hazardous- and industrial-waste "
        "landfill operated by US Ecology; most of its reported total is on-site "
        "land disposal of received waste."),
    "EAGLE MINE": (
        "Eagle Mine is a nickel and copper mine and mill in Michigan's Upper "
        "Peninsula. Most reported releases are mine tailings and process "
        "residues managed on-site."),
    "JBS": (
        "JBS is one of the world's largest meat processors; its Plainwell plant "
        "is a beef/animal-processing facility."),
    "CMS ENERGY": (
        "CMS Energy (Consumers Energy) is a Michigan electric and gas utility. "
        "The J.H. Campbell plant is a large coal-fired power station."),
    "CONSUMERS ENERGY": (
        "Consumers Energy is a Michigan electric and gas utility; the listed "
        "sites are power-generation stations."),
    "DTE": (
        "DTE Energy is Michigan's largest electric utility; the listed sites are "
        "coal/gas power plants and a coke battery serving steelmaking."),
    "GENERAL MOTORS": (
        "General Motors is a Detroit-based global automaker; its Michigan plants "
        "assemble trucks and vehicles and build powertrains and stamped parts."),
    "FORD MOTOR": (
        "Ford Motor Company is a Dearborn-headquartered global automaker. Its "
        "Michigan sites stamp, weld, paint, and assemble vehicles and components."),
    "FCA US": (
        "FCA US (now part of Stellantis) is a Detroit-area automaker; its "
        "Michigan assembly and stamping plants build trucks and vehicles."),
    "STELLANTIS": (
        "Stellantis (which includes the former FCA/Chrysler) is an automaker; "
        "its Michigan plants assemble and stamp vehicles and parts."),
    "DOW": (
        "Dow is a Midland, Michigan-headquartered chemical manufacturer making "
        "plastics, industrial chemicals, silicones, and coatings."),
    "KOPPERS": (
        "Koppers makes carbon compounds and performance chemicals; its Michigan "
        "site handles coal-tar and treated-wood chemistry."),
    "BILLERUD": (
        "Billerud (formerly Verso) runs pulp and paper mills in Michigan's Upper "
        "Peninsula."),
    "PACKAGING CORP": (
        "Packaging Corporation of America runs containerboard and paper mills."),
    "INTERTAPE POLYMER": (
        "Intertape Polymer Group manufactures tapes, films, and packaging "
        "products."),
    "REPUBLIC SERVICES": (
        "Republic Services operates landfills and waste-management sites; "
        "reported releases are largely landfill disposal."),
    "HOLCIM": (
        "Holcim is a cement manufacturer; its kilns emit combustion by-products "
        "and process releases."),
    "VOTORANTIM": (
        "Votorantim Cimentos (St Marys Cement) is a cement manufacturer; kilns "
        "emit combustion by-products and process releases."),
    "MICHIGAN SUGAR": (
        "Michigan Sugar Company processes sugar beets into sugar at plants "
        "across the Saginaw Valley."),
    "PFIZER": (
        "Pfizer is a pharmaceutical manufacturer; its Michigan (Kalamazoo/"
        "Portage) site produces drug substances and finished products."),
    "MARATHON": (
        "Marathon Petroleum operates the Detroit refinery, turning crude oil "
        "into fuels and petroleum products."),
    "CLEVELAND-CLIFFS": (
        "Cleveland-Cliffs is an integrated steelmaker; blast furnaces and coke/"
        "finishing operations drive its reported releases."),
    "ARAUCO": (
        "Arauco manufactures wood-based panels (particleboard/MDF); releases "
        "include wood-processing chemicals."),
    "GERDAU": (
        "Gerdau is a steel producer; its mill melts scrap and rolls steel "
        "products."),
    "NEXTEER": (
        "Nexteer Automotive manufactures steering and driveline components in "
        "the Saginaw area."),
    "GraphicPkg".upper(): (
        "Graphic Packaging makes paperboard and packaging products at its mill "
        "and converting sites."),
}


def company_summary(parent_company: str | None, facility_name: str | None,
                    industry_sector: str | None, top_chem_names: list[str] | None,
                    year: int | None) -> dict:
    """Return {'text', 'sourced'} describing the operator/facility.

    Uses the curated operator blurb when the parent company or facility name
    matches a known Michigan operator; otherwise builds a factual one-liner from
    the industry sector and the chemicals the facility actually reported.
    """
    hay = f"{parent_company or ''} {facility_name or ''}".upper()
    for key, desc in OPERATOR_PROFILES.items():
        if key and key in hay:
            return {"text": desc, "sourced": True}

    sector = (industry_sector or "").strip()
    chems = [c for c in (top_chem_names or []) if c][:3]
    if sector and sector.upper() != "NA":
        art = "An" if sector[:1].upper() in "AEIOU" else "A"
        base = f"{art} {sector.lower()} facility in Michigan."
    else:
        base = "An industrial facility reporting to the EPA Toxics Release Inventory."
    chem_part = ""
    if chems:
        chem_part = f" It reported releasing {_join(chems)}" + (f" in {year}." if year else ".")
    return {"text": base + chem_part, "sourced": False}


# --------------------------------------------------------------------------- #
# Chemical reference. Keys are UPPERCASE distinctive substrings matched against  #
# the TRI chemical name (which often carries a "(except ...)" qualifier).        #
# `carcinogen` holds a sourced EPA/IARC classification string, or None.          #
# --------------------------------------------------------------------------- #

CHEMICAL_PROFILES: dict[str, dict] = {
    "ASBESTOS": {
        "what": "A group of naturally occurring fibrous silicate minerals.",
        "uses": "Once widely used in insulation, fireproofing, brake linings and "
                "building materials; now heavily restricted.",
        "health": "Inhaled fibers scar the lungs and cause mesothelioma and lung "
                  "cancer, often decades after exposure.",
        "carcinogen": "IARC Group 1 — a known human carcinogen.",
        "pathways": "Almost entirely on-site land disposal of asbestos-containing waste.",
    },
    "NICKEL COMPOUNDS": {
        "what": "Compounds of the metal nickel.",
        "uses": "Stainless steel, electroplating, batteries and alloys.",
        "health": "Can damage the lungs and nasal passages and cause allergic skin reactions.",
        "carcinogen": "Nickel compounds are IARC Group 1 (known human carcinogen).",
        "pathways": "Air emissions and land disposal from metal processing and mining.",
    },
    "NITRATE COMPOUNDS": {
        "what": "Water-soluble nitrogen compounds.",
        "uses": "A by-product of many industrial, food and agricultural processes.",
        "health": "In drinking water can cause 'blue-baby syndrome' in infants and "
                  "fuels algal blooms in lakes and streams.",
        "carcinogen": None,
        "pathways": "Discharged to surface water.",
    },
    "BARIUM": {
        "what": "Compounds of the metal barium.",
        "uses": "Drilling muds, pigments, glass and specialty chemicals.",
        "health": "Soluble barium can affect the heart and muscles; most industrial "
                  "forms are insoluble and far less toxic.",
        "carcinogen": None,
        "pathways": "Land disposal and water discharge.",
    },
    "AMMONIA": {
        "what": "A pungent nitrogen-hydrogen gas or solution (NH3).",
        "uses": "Fertilizer, refrigerant and a chemical feedstock.",
        "health": "A corrosive irritant to the eyes, skin and airways at high levels.",
        "carcinogen": None,
        "pathways": "Air emissions and water discharge.",
    },
    "COPPER COMPOUNDS": {
        "what": "Compounds of the metal copper.",
        "uses": "Wiring, plumbing, alloys and wood preservatives.",
        "health": "High exposure irritates the gut; highly toxic to fish and aquatic life.",
        "carcinogen": None,
        "pathways": "Water discharge and land disposal.",
    },
    "LEAD COMPOUNDS": {
        "what": "Compounds of the heavy metal lead.",
        "uses": "Batteries, solder, radiation shielding, and older paints and gasoline.",
        "health": "A potent neurotoxin — it harms brain development in children and "
                  "the nervous system, kidneys and blood in adults. No level is "
                  "considered safe.",
        "carcinogen": "Inorganic lead compounds are IARC Group 2A (probable human carcinogen).",
        "pathways": "Air emissions, land disposal and water.",
    },
    "METHANOL": {
        "what": "A simple alcohol, also called wood alcohol.",
        "uses": "A solvent, antifreeze and feedstock for other chemicals.",
        "health": "Toxic if swallowed (can cause blindness); vapors irritate the airways.",
        "carcinogen": None,
        "pathways": "Mostly air emissions.",
    },
    "SULFURIC ACID": {
        "what": "A strong mineral acid, released as an acid mist/aerosol.",
        "uses": "Batteries, fertilizer, metal processing and chemical manufacturing.",
        "health": "Corrosive; the mists burn the airways and eyes.",
        "carcinogen": "Occupational exposure to strong-inorganic-acid mists containing "
                      "sulfuric acid is IARC Group 1.",
        "pathways": "Air (acid aerosols).",
    },
    "TOLUENE": {
        "what": "A clear aromatic solvent.",
        "uses": "Paints, coatings, adhesives and gasoline.",
        "health": "Affects the nervous system (headaches, dizziness); high exposure "
                  "can harm development.",
        "carcinogen": None,
        "pathways": "Air emissions.",
    },
    "GLYCOL ETHERS": {
        "what": "A family of solvents.",
        "uses": "Paints, cleaners, inks and coatings.",
        "health": "Some members cause reproductive and blood effects.",
        "carcinogen": None,
        "pathways": "Air and water.",
    },
    "BERYLLIUM": {
        "what": "Compounds of the light metal beryllium.",
        "uses": "Aerospace alloys, electronics and specialty ceramics.",
        "health": "Inhaling dust or fumes can cause chronic beryllium disease, a "
                  "serious scarring lung condition.",
        "carcinogen": "IARC Group 1 — a known human carcinogen.",
        "pathways": "Air emissions and land disposal.",
    },
    "XYLENE": {
        "what": "An aromatic solvent (mixed isomers).",
        "uses": "Paints, coatings, cleaners and fuels.",
        "health": "Nervous-system effects and irritation.",
        "carcinogen": None,
        "pathways": "Air emissions.",
    },
    "POLYCHLORINATED BIPHENYLS": {
        "what": "PCBs — a group of persistent chlorinated industrial chemicals.",
        "uses": "Formerly used in electrical transformers, capacitors and coolants; "
                "banned in the US in 1979 but they persist in old equipment and sediments.",
        "health": "They build up in the food chain and the body and are linked to "
                  "cancer and immune, reproductive and developmental harm.",
        "carcinogen": "IARC Group 1 — a known human carcinogen.",
        "pathways": "Land disposal and water/sediment.",
    },
    "MANGANESE": {
        "what": "Compounds of the metal manganese.",
        "uses": "Steelmaking, batteries and pigments.",
        "health": "Overexposure by inhalation can cause a Parkinson's-like neurological condition.",
        "carcinogen": None,
        "pathways": "Air emissions and land disposal.",
    },
    "CHROMIUM": {
        "what": "Compounds of the metal chromium.",
        "uses": "Stainless steel, chrome plating, pigments and leather tanning.",
        "health": "Trivalent chromium is a low-toxicity nutrient; hexavalent chromium "
                  "is highly toxic and a known lung carcinogen.",
        "carcinogen": "Hexavalent chromium compounds are IARC Group 1; other chromium "
                      "forms are not classifiable.",
        "pathways": "Air, water and land.",
    },
    "ZINC COMPOUNDS": {
        "what": "Compounds of the metal zinc.",
        "uses": "Galvanizing, rubber, paints and alloys.",
        "health": "An essential nutrient in trace amounts; high levels are toxic to aquatic life.",
        "carcinogen": None,
        "pathways": "Water discharge and land disposal.",
    },
    "STYRENE": {
        "what": "A liquid used to make plastics and rubber.",
        "uses": "Polystyrene, fiberglass resins and synthetic rubber.",
        "health": "An irritant that affects the nervous system at high exposure.",
        "carcinogen": "IARC Group 2A — probably carcinogenic to humans.",
        "pathways": "Air emissions.",
    },
    "HYDROCHLORIC ACID": {
        "what": "A strong mineral acid, released as an acid aerosol.",
        "uses": "Metal cleaning/pickling and chemical production.",
        "health": "Corrosive; the mists irritate and burn the airways.",
        "carcinogen": None,
        "pathways": "Air (acid aerosols).",
    },
    "ISOPROPYLIDENEDIPHENOL": {
        "what": "Bisphenol A (BPA), a chemical building block.",
        "uses": "Making polycarbonate plastics and epoxy resins.",
        "health": "An endocrine (hormone) disruptor of particular concern in "
                  "food-contact uses.",
        "carcinogen": None,
        "pathways": "Water and air.",
    },
    "BENZENE": {
        "what": "A volatile aromatic hydrocarbon.",
        "uses": "A feedstock for plastics and resins; present in gasoline.",
        "health": "Damages bone marrow and blood and causes leukemia.",
        "carcinogen": "IARC Group 1 — a known human carcinogen.",
        "pathways": "Air emissions.",
    },
    "HEXANE": {
        "what": "A volatile hydrocarbon solvent.",
        "uses": "Extraction solvent (e.g. vegetable oils), glues and cleaners.",
        "health": "Chronic exposure can cause nerve damage in the hands and feet "
                  "(peripheral neuropathy).",
        "carcinogen": None,
        "pathways": "Air emissions.",
    },
    "COBALT": {
        "what": "Compounds of the metal cobalt.",
        "uses": "Alloys, magnets, batteries and pigments.",
        "health": "Inhalation can cause lung and heart effects.",
        "carcinogen": "Cobalt and certain cobalt compounds are IARC Group 2B "
                      "(possibly carcinogenic).",
        "pathways": "Air emissions and land disposal.",
    },
    "BUTYL ALCOHOL": {
        "what": "A solvent alcohol (1-butanol).",
        "uses": "Coatings, plasticizers and as a chemical intermediate.",
        "health": "Irritating to the eyes and airways with mild nervous-system effects.",
        "carcinogen": None,
        "pathways": "Air emissions.",
    },
}

# Longest keys first so a specific match ("COPPER COMPOUNDS") wins over a broad one.
_CHEM_KEYS = sorted(CHEMICAL_PROFILES, key=len, reverse=True)


def chemical_profile(name: str, cas: str | None, is_carcinogen: bool) -> dict:
    """Return {'what','uses','health','carcinogen','pathways','sourced'} for a
    chemical. Falls back to a minimal factual entry (carrying the TRI carcinogen
    flag) when the chemical isn't in the curated reference."""
    norm = (name or "").upper()
    for key in _CHEM_KEYS:
        if key in norm:
            p = dict(CHEMICAL_PROFILES[key])
            p["sourced"] = True
            return p
    # Fallback — no curated text, but keep it honest and useful.
    carc = None
    if is_carcinogen:
        carc = ("Listed as a carcinogen under EPA's Toxics Release Inventory "
                "(an OSHA-designated carcinogen); see EPA/IARC for the specific class.")
    return {
        "what": f"{name} is a chemical tracked by the EPA Toxics Release Inventory.",
        "uses": None,
        "health": None,
        "carcinogen": carc,
        "pathways": None,
        "sourced": False,
    }


def _join(items: list[str]) -> str:
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"
