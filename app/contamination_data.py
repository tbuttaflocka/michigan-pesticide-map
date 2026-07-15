"""
Curated Michigan industrial-contamination dataset for the contamination overlay.

Two roles:
  * MICHIGAN_INDUSTRIAL_CONTAMINATION + PFAS_SITES — hand-compiled records for
    the most significant corporate polluters / contamination sites, with rich
    narrative, contaminant lists, responsible-party attribution, impact areas,
    and affected waterways. Many of these are NOT on the federal NPL (Dow,
    Wolverine, GM, PFAS airports/bases) so they wouldn't appear in the EPA feed.
  * The loader also pulls the full EPA NPL list live (~90 Michigan sites) and
    merges it in, so hardcoded detail augments the authoritative EPA record and
    unique non-NPL sites are added on top.

CATEGORY_META and STATUS_COLORS drive the map marker glyphs/colors.
"""
from __future__ import annotations


# category -> (marker glyph, human label). Glyphs are plain unicode so no icon
# font is required.
CATEGORY_META = {
    "chemical_manufacturing": ("☣", "Chemical manufacturing"),   # ☣ biohazard
    "pesticide_manufacturing": ("☣", "Pesticide manufacturing"),
    "pfas_manufacturing":     ("\U0001F4A7", "PFAS source"),          # 💧
    "steel_manufacturing":    ("\U0001F3ED", "Steel manufacturing"),  # 🏭
    "auto_manufacturing":     ("\U0001F3ED", "Auto manufacturing"),
    "industrial_manufacturing": ("\U0001F3ED", "Industrial manufacturing"),
    "paper_manufacturing":    ("\U0001F3ED", "Paper manufacturing"),
    "mining":                 ("⛏", "Mining / tailings"),        # ⛏
    "military":               ("★", "Military / AFFF"),          # ★
    "waste_disposal":         ("☠", "Waste disposal"),           # ☠
    "pfas":                   ("\U0001F4A7", "PFAS site"),
    "landfill":               ("☠", "Landfill"),
    "other":                  ("⚠", "Other"),                    # ⚠
}

# Normalized status -> (color, label). Used for marker fill + legend.
STATUS_COLORS = {
    "npl":      ("#f85149", "Active NPL (Superfund)"),
    "proposed": ("#f0b429", "Proposed for NPL"),
    "deleted":  ("#3fb950", "Deleted from NPL (cleaned up)"),
    "state":    ("#e8873c", "State cleanup / PFAS investigation"),
    "unknown":  ("#9aa4b2", "Status unknown"),
}


def normalize_status(status: str | None, npl_listed: bool) -> str:
    """Map a free-text status string to one of STATUS_COLORS keys."""
    s = (status or "").lower()
    if "delet" in s:
        return "deleted"
    if "propos" in s:
        return "proposed"
    if "npl" in s or npl_listed:
        return "npl"
    if any(k in s for k in ("pfas", "state", "investigation", "cleanup", "brownfield", "active")):
        return "state"
    return "unknown"


MICHIGAN_INDUSTRIAL_CONTAMINATION = {
    "dow_chemical_midland": {
        "company": "Dow Chemical Company (now Dow Inc.)",
        "site_name": "Dow Chemical Midland Plant / Tittabawassee River",
        "lat": 43.6156, "lng": -84.2472,
        "county": "Midland", "county_fips": "26111", "city": "Midland",
        "epa_id": "MID000724724", "status": "Active cleanup",
        "years_active": "1897-present",
        "contaminants": ["Dioxins (2,3,7,8-TCDD)", "Furans", "Chlorinated phenols",
                         "Herbicides (2,4-D, 2,4,5-T)", "Agent Orange precursors",
                         "Heavy metals", "PFAS"],
        "description": "Herbert Dow founded Dow Chemical in 1897. The 1,900-acre facility has manufactured over 1,000 different chemicals. Dioxins and furans were byproducts of chlorine-based manufacturing starting in the early 1900s. Past waste disposal contaminated the Tittabawassee River, Saginaw River, and Saginaw Bay over 50+ miles downstream. Dow produced precursors to Agent Orange (2,4,5-T) during the Vietnam War era. In 2020, Midland Dam failures flooded the area, mobilizing contaminated sediment.",
        "impact_area_miles": 50,
        "affected_waterways": ["Tittabawassee River", "Saginaw River", "Saginaw Bay"],
        "affected_counties": ["Midland", "Saginaw", "Bay"],
        "npl_listed": False, "category": "chemical_manufacturing",
    },
    "velsicol_st_louis": {
        "company": "Velsicol Chemical Corp. (formerly Michigan Chemical Corp.)",
        "site_name": "Velsicol Chemical Corp. Superfund Site",
        "lat": 43.4083, "lng": -84.6042,
        "county": "Gratiot", "county_fips": "26057", "city": "St. Louis",
        "epa_id": "MID000722470", "status": "Active NPL - cleanup ongoing since 1982",
        "years_active": "1936-1978",
        "contaminants": ["PBB (polybrominated biphenyls)", "DDT", "DBCP",
                         "Hexabromobenzene", "Carbon tetrachloride", "TCE",
                         "Chlorobenzene", "p-CBSA", "PFAS"],
        "description": "The worst chemical contamination disaster in Michigan history. In 1973, Velsicol accidentally shipped 10-20 bags of PBB flame retardant (FireMaster) instead of cattle feed supplement (NutriMaster) to Michigan Farm Bureau. 30,000 cattle, 4,500 pigs, 1,500 sheep, and 1.5 million chickens were destroyed. Up to 9 MILLION Michiganders consumed contaminated meat and dairy for a year before the error was discovered. The company also manufactured DDT, contaminating the Pine River and groundwater. The entire plant was buried on-site under a clay cap. PFAS also found in 69 of 74 monitoring wells tested in 2023. Multi-generational health effects (thyroid disease, cancer, reproductive issues) still being studied.",
        "impact_area_miles": 30,
        "affected_waterways": ["Pine River"],
        "affected_counties": ["Gratiot", "Isabella", "Midland"],
        "npl_listed": True, "npl_date": "1982-09-08",
        "category": "chemical_manufacturing",
    },
    "velsicol_burn_pit": {
        "company": "Velsicol Chemical Corp.",
        "site_name": "Velsicol Burn Pit Superfund Site",
        "lat": 43.3878, "lng": -84.6167,
        "county": "Gratiot", "county_fips": "26057", "city": "St. Louis",
        "epa_id": "MID098636498", "status": "Active NPL",
        "years_active": "1936-1978",
        "contaminants": ["PBB", "DDT", "Chlorinated organics", "Heavy metals"],
        "description": "A satellite Superfund site associated with the Velsicol/Michigan Chemical "
                       "plant in St. Louis (see the main Velsicol Chemical site). Located southwest "
                       "of the main plant, this area was used as an open burn pit for chemical-waste "
                       "disposal, leaving soil and groundwater contaminated with PBB, DDT, "
                       "chlorinated organics, and heavy metals from the same manufacturing "
                       "operations behind Michigan's 1973 PBB contamination disaster. It is "
                       "remediated as a distinct NPL site alongside the main plant and Pine River "
                       "cleanups.",
        "npl_listed": True, "category": "chemical_manufacturing",
    },
    "hooker_chemical_montague": {
        "company": "Hooker Chemical Company / Occidental Chemical Corp.",
        "site_name": "Hooker Chemical/Occidental Chemical Corp. (OCC)",
        "lat": 43.4164, "lng": -86.3589,
        "county": "Muskegon", "county_fips": "26121", "city": "Montague",
        "epa_id": "MID000722843", "status": "Active NPL",
        "years_active": "1952-1982",
        "contaminants": ["C-56 (hexachlorocyclopentadiene)", "Mirex", "Chloroform",
                         "Carbon tetrachloride", "TCE", "PCE",
                         "Hexachlorobenzene", "Hexachlorobutadiene"],
        "description": "Same company behind the Love Canal disaster in New York. Hooker produced C-56, a toxic precursor to pesticides including mirex and kepone. Waste disposal practices contaminated groundwater and White Lake. Contaminants include some of the most persistent chlorinated compounds known. All manufacturing ceased 1982.",
        "affected_waterways": ["White Lake"],
        "npl_listed": True, "category": "chemical_manufacturing",
    },
    "mclouth_steel_trenton": {
        "company": "McLouth Steel Corp.",
        "site_name": "McLouth Steel Corp. Superfund Site",
        "lat": 42.1453, "lng": -83.1808,
        "county": "Wayne", "county_fips": "26163", "city": "Trenton",
        "epa_id": "MID006014872", "status": "Active NPL - listed 2019",
        "years_active": "1950-1995",
        "contaminants": ["PCBs", "Dioxins", "Cyanide", "Chromium", "Lead",
                         "Calcium hydroxide (caustic lime)", "VOCs", "Heavy metals"],
        "description": "273-acre former steel mill on the Detroit River in Trenton. Operated 1950-1995. Bankrupted 1995, abandoned. Contaminants include PCBs, dioxins, cyanide, heavy metals. Buried caustic lime causes chemical burns. Contaminants discharge into the Detroit River and Humbug Marsh Federal Wildlife Refuge. $20M+ in cleanup so far, still ongoing. Fish kills from toxic groundwater reaching Huntington Creek documented in 2023.",
        "affected_waterways": ["Detroit River", "Huntington Creek", "Humbug Marsh"],
        "npl_listed": True, "npl_date": "2019-05-01",
        "category": "steel_manufacturing",
    },
    "mclouth_steel_gibraltar": {
        "company": "DSC McLouth Steel",
        "site_name": "DSC McLouth Steel Gibraltar Plant Superfund Site",
        "lat": 42.1011, "lng": -83.1850,
        "county": "Wayne", "county_fips": "26163", "city": "Gibraltar",
        "epa_id": "MID985574640", "status": "Active NPL - listed 2015",
        "years_active": "1950s-1996",
        "contaminants": ["Leachate", "Heavy metals", "VOCs", "PFAS"],
        "description": "620-acre steel finishing facility. Three landfills and lagoon system. Mismanagement of leachate treatment contaminated adjacent creeks leading to the Detroit River and Humbug Marsh Wildlife Refuge.",
        "affected_waterways": ["Detroit River", "Humbug Marsh"],
        "npl_listed": True, "category": "steel_manufacturing",
    },
    "wolverine_worldwide_rockford": {
        "company": "Wolverine World Wide, Inc.",
        "site_name": "Wolverine Worldwide Tannery / Hush Puppies PFAS Site",
        "lat": 43.1200, "lng": -85.5600,
        "county": "Kent", "county_fips": "26081", "city": "Rockford",
        "status": "Active PFAS investigation", "years_active": "1908-2009",
        "contaminants": ["PFAS (PFOS, PFOA)", "3M Scotchgard chemicals",
                         "Chrome tanning chemicals"],
        "description": "Wolverine used 3M's Scotchgard (containing PFAS) to waterproof Hush Puppies shoes at its tannery in Rockford since the 1950s. Waste from the tanning process was dumped at multiple disposal sites around Kent County, contaminating drinking water wells with PFAS at levels far exceeding safety standards. Over 11,000 Michigan sites now identified with PFAS contamination, many traced back to Wolverine's disposal practices. Michigan AG filed lawsuit against Wolverine. Contamination spread via the Rogue River.",
        "affected_waterways": ["Rogue River", "groundwater"],
        "affected_counties": ["Kent"],
        "npl_listed": False, "category": "pfas_manufacturing",
    },
    "gelman_sciences_ann_arbor": {
        "company": "Gelman Sciences Inc. (now Pall Corporation)",
        "site_name": "Gelman Sciences Inc. Superfund Site",
        "lat": 42.2631, "lng": -83.8006,
        "county": "Washtenaw", "county_fips": "26161", "city": "Ann Arbor",
        "epa_id": "MIN000510552", "status": "Active NPL - listed March 2026",
        "years_active": "1963-1986",
        "contaminants": ["1,4-Dioxane"],
        "description": "Manufactured medical filters from 1963-1986, discharging wastewater containing 1,4-dioxane into surrounding ponds. Created a massive groundwater contamination plume threatening the Huron River and drinking water wells. City of Ann Arbor closed its Montgomery Wellfield in 2001 due to 1,4-dioxane contamination. Added to NPL in March 2026 - one of Michigan's most recently listed sites. Community fought for decades for Superfund designation.",
        "affected_waterways": ["Huron River", "groundwater"],
        "npl_listed": True, "npl_date": "2026-03-12",
        "category": "industrial_manufacturing",
    },
    "torch_lake_copper": {
        "company": "Multiple mining companies (Quincy Mining Co., Calumet & Hecla, etc.)",
        "site_name": "Torch Lake Superfund Site",
        "lat": 47.1667, "lng": -88.4333,
        "county": "Houghton", "county_fips": "26061", "city": "Lake Linden",
        "epa_id": "MID980901946", "status": "Active NPL - cleanup ongoing",
        "years_active": "1868-1968",
        "contaminants": ["Copper", "Heavy metals (arsenic, chromium, cobalt, lead, nickel, manganese)",
                         "Stamp sands", "Slag", "Ammonia"],
        "description": "A century of copper mining (1868-1968) filled Torch Lake with an estimated 200 MILLION TONS of mill tailings (stamp sands), filling 50% of the lake's volume. Six large-volume stamp mills crushed rock along the western shore. Contaminated sediments contain elevated heavy metals. Fish consumption advisories still in effect. Includes 13 separate remediation sites across the Keweenaw Peninsula. One of Michigan's largest and oldest contamination sites.",
        "affected_waterways": ["Torch Lake", "Portage Lake", "Lake Superior"],
        "affected_counties": ["Houghton", "Keweenaw"],
        "npl_listed": True, "npl_date": "1986-06-10", "category": "mining",
    },
    "gm_central_foundry_saginaw": {
        "company": "General Motors Corp.",
        "site_name": "GM Central Foundry Division",
        "lat": 43.4119, "lng": -83.9531,
        "county": "Saginaw", "county_fips": "26145", "city": "Saginaw",
        "status": "Active cleanup", "years_active": "1918-1990s",
        "contaminants": ["PCBs", "TCE", "Heavy metals", "VOCs"],
        "description": "General Motors' Central Foundry Division ran a large gray-iron casting "
                       "foundry in Saginaw from about 1918 into the 1990s, producing engine blocks "
                       "and other cast-metal automotive components. Metal casting, machining, and "
                       "degreasing generated foundry sands, sludges, and spent chlorinated solvents; "
                       "on-site disposal and releases contaminated soil and groundwater with PCBs, "
                       "trichloroethylene (TCE) and other VOCs, and heavy metals. Cleanup has been "
                       "conducted under state and federal oversight as the plant was demolished.",
        "npl_listed": False, "category": "auto_manufacturing",
    },
    "gm_buick_complex_flint": {
        "company": "General Motors Corp.",
        "site_name": "GM Buick City Complex / Flint Industrial Sites",
        "lat": 43.0317, "lng": -83.6882,
        "county": "Genesee", "county_fips": "26049", "city": "Flint",
        "status": "Brownfield redevelopment", "years_active": "1904-1999",
        "contaminants": ["PCBs", "TCE", "Lead", "Heavy metals", "Petroleum"],
        "description": "GM's massive Buick City complex and surrounding industrial sites in Flint left widespread soil and groundwater contamination. Combined with the 2014 Flint Water Crisis (lead contamination of municipal water supply when the city switched water sources), Flint represents one of Michigan's most heavily impacted communities.",
        "affected_waterways": ["Flint River"],
        "npl_listed": False, "category": "auto_manufacturing",
    },
    "kalamazoo_river_pcbs": {
        "company": "Allied Paper Inc. / Georgia-Pacific Corp. / NCR Corp.",
        "site_name": "Allied Paper/Portage Creek/Kalamazoo River Superfund Site",
        "lat": 42.2953, "lng": -85.5731,
        "county": "Kalamazoo", "county_fips": "26077", "city": "Kalamazoo",
        "epa_id": "MID006007306", "status": "Active NPL",
        "years_active": "1957-1971",
        "contaminants": ["PCBs (polychlorinated biphenyls)"],
        "description": "PCB-containing carbonless copy paper manufacturing contaminated Portage Creek and 80 miles of the Kalamazoo River. One of the largest PCB-contaminated river systems in the US. Fish consumption advisories cover the entire Kalamazoo River. Cleanup has been ongoing for 30+ years. Contamination extends from Kalamazoo through Allegan County to Lake Michigan.",
        "impact_area_miles": 80,
        "affected_waterways": ["Kalamazoo River", "Portage Creek", "Lake Michigan"],
        "affected_counties": ["Kalamazoo", "Allegan"],
        "npl_listed": True, "npl_date": "1990-08-30",
        "category": "paper_manufacturing",
    },
    "wurtsmith_afb_oscoda": {
        "company": "US Air Force / Department of Defense",
        "site_name": "Wurtsmith Air Force Base",
        "lat": 44.4517, "lng": -83.3944,
        "county": "Iosco", "county_fips": "26069", "city": "Oscoda",
        "epa_id": "MI2570024453", "status": "Active NPL",
        "years_active": "1923-1993",
        "contaminants": ["PFAS (PFOS, PFOA - up to 213,000 ppt)", "AFFF firefighting foam",
                         "TCE", "Fuel hydrocarbons", "Heavy metals"],
        "description": "Former Strategic Air Command base. Firefighting training exercises used AFFF foam containing PFAS for decades. PFAS concentrations near the base reached 213,000 ppt - over 53,000 times the EPA safe limit of 4 ppt. Contaminated groundwater, Van Etten Lake, the Au Sable River, and private wells. Base closed 1993 but contamination continues to spread. One of the most PFAS-contaminated sites in Michigan.",
        "affected_waterways": ["Van Etten Lake", "Au Sable River"],
        "npl_listed": True, "category": "military",
    },
    "liquid_disposal_utica": {
        "company": "Liquid Disposal Inc.",
        "site_name": "Liquid Disposal Inc. Superfund Site",
        "lat": 42.6397, "lng": -83.0464,
        "county": "Macomb", "county_fips": "26099", "city": "Utica",
        "epa_id": "MID048890418", "status": "Active NPL",
        "years_active": "1960s-1980s",
        "contaminants": ["VOCs", "Heavy metals", "Cyanide", "PCBs", "Pesticides"],
        "description": "Michigan's HIGHEST hazard-ranked Superfund site (HRS score 63.28/100). Operated as a hazardous waste disposal facility accepting industrial waste from across southeast Michigan. Contaminated groundwater and nearby Clinton River.",
        "affected_waterways": ["Clinton River"],
        "npl_listed": True, "hrs_score": 63.28, "category": "waste_disposal",
    },
    "ott_story_cordova": {
        "company": "Cordova Chemical Company / Story Chemical Company",
        "site_name": "Ott/Story/Cordova Chemical Co. Superfund Site",
        "lat": 43.3808, "lng": -86.2450,
        "county": "Muskegon", "county_fips": "26121", "city": "Dalton Township",
        "epa_id": "MID006013924", "status": "Active NPL",
        "years_active": "1957-1986",
        "contaminants": ["DDT", "Dioxins", "Benzene", "Chloroaniline",
                         "Dichlorobenzidine", "Hexachlorobenzene", "Toluene",
                         "Vinyl chloride", "1,1-Dichloroethene"],
        "description": "Chemical manufacturing and pesticide formulation facility. Produced DDT and other chlorinated pesticides. One of the most contaminated sites in Muskegon County. Manufacturing waste disposed in unlined lagoons contaminated soil and groundwater. Note: This site directly connects agricultural pesticides to industrial manufacturing contamination.",
        "npl_listed": True, "category": "chemical_manufacturing",
    },
    "anderson_development_adrian": {
        "company": "Anderson Development Company",
        "site_name": "Anderson Development Co. Superfund Site",
        "lat": 41.8975, "lng": -84.0372,
        "county": "Lenawee", "county_fips": "26091", "city": "Adrian",
        "epa_id": "MID006019814", "status": "Deleted from NPL (cleaned up 1993)",
        "years_active": "1970-1979",
        "contaminants": ["MBOCA (4,4'-methylene-bis(2-chloroaniline))",
                         "Chlorinated aromatic amines", "VOCs"],
        "description": "Anderson Development Company produced specialty organic chemicals in "
                       "Adrian from 1970-1979, including MBOCA "
                       "(4,4'-methylene-bis(2-chloroaniline)) — a chlorinated aromatic-amine curing "
                       "agent classed as a suspected human carcinogen — along with other volatile "
                       "organic compounds. Process wastewater and a former treatment lagoon "
                       "contaminated soil, surface water, and air on and around the site. Cleanup "
                       "was completed and the site was deleted from the NPL in 1996; the "
                       "manufacturing facility remains active.",
        "npl_listed": False, "npl_status": "Deleted", "category": "chemical_manufacturing",
    },
    "bendix_st_joseph": {
        "company": "Bendix Corp. / Allied Automotive / Robert Bosch LLC",
        "site_name": "Bendix Corp./Allied Automotive Superfund Site",
        "lat": 42.0986, "lng": -86.4808,
        "county": "Berrien", "county_fips": "26021", "city": "St. Joseph",
        "epa_id": "MID006030829", "status": "Active NPL - treatment ongoing",
        "years_active": "1950s-present",
        "contaminants": ["VOCs", "Chlorinated solvents", "Heavy metals"],
        "description": "Bendix Corporation (later Allied Automotive, now Robert Bosch) has "
                       "manufactured automotive brake components at the St. Joseph site since the "
                       "1950s. During the 1950s-60s, chemical wastes and spent chlorinated solvents "
                       "were disposed in unlined on-site lagoons, allowing volatile organic "
                       "compounds and heavy metals to migrate into groundwater both on-site and "
                       "off-site toward the St. Joseph River/Lake Michigan area. The site is on the "
                       "NPL; a groundwater extraction-and-treatment system operates to contain and "
                       "clean up the plume.",
        "npl_listed": True, "npl_date": "1990", "category": "auto_manufacturing",
    },
    "muskegon_chemical": {
        "company": "Muskegon Chemical Co.",
        "site_name": "Muskegon Chemical Co. Superfund Site",
        "lat": 43.2300, "lng": -86.2500,
        "county": "Muskegon", "county_fips": "26121", "city": "Muskegon",
        "status": "Active NPL",
        "contaminants": ["Chlorinated solvents", "Heavy metals", "Pesticide precursors"],
        "description": "Chemical-manufacturing and solvent-handling operation in the "
                       "Muskegon area. Site operations and waste disposal released chlorinated "
                       "solvents, heavy metals, and pesticide-related compounds that contaminated "
                       "soil and the shallow groundwater aquifer. The site sits within Muskegon "
                       "County's industrial corridor near the Muskegon Lake watershed and has been "
                       "addressed as a Superfund cleanup.",
        "npl_listed": True, "category": "chemical_manufacturing",
    },
    "parsons_chemical_grand_ledge": {
        "company": "Parsons Chemical Works Inc.",
        "site_name": "Parsons Chemical Works Superfund Site",
        "lat": 42.7531, "lng": -84.7464,
        "county": "Eaton", "county_fips": "26045", "city": "Grand Ledge",
        "epa_id": "MID006014211", "status": "Active NPL",
        "years_active": "1945-1979",
        "contaminants": ["Pesticides (DDT, chlordane, aldrin, dieldrin)",
                         "Arsenic", "Heavy metals", "VOCs"],
        "description": "Pesticide formulation and distribution facility from 1945-1979. Manufactured and packaged DDT, chlordane, aldrin, dieldrin, and other pesticides. Contamination of soil and groundwater with pesticide residues and arsenic. DIRECTLY relevant to the pesticide heat map - this is where some of the pesticides applied to Michigan farms were manufactured.",
        "npl_listed": True, "category": "pesticide_manufacturing",
    },
    "organic_chemicals_grandville": {
        "company": "Organic Chemicals Inc.",
        "site_name": "Organic Chemicals Inc. Superfund Site",
        "lat": 42.9097, "lng": -85.7631,
        "county": "Kent", "county_fips": "26081", "city": "Grandville",
        "status": "Active NPL",
        "contaminants": ["VOCs", "Heavy metals", "Organic solvents"],
        "description": "Former solvent-reclamation and chemical-handling facility in Grandville. "
                       "Handling, spills, and disposal of industrial solvents released volatile "
                       "organic compounds and heavy metals into soil and the underlying groundwater, "
                       "producing a contaminant plume in a mixed industrial/residential area of Kent "
                       "County. Listed as a federal Superfund (NPL) site with groundwater remediation "
                       "conducted under EPA oversight.",
        "npl_listed": True, "category": "chemical_manufacturing",
    },
    "spartan_chemical_wyoming": {
        "company": "Spartan Chemical Co.",
        "site_name": "Spartan Chemical Co. Superfund Site",
        "lat": 42.8947, "lng": -85.7064,
        "county": "Kent", "county_fips": "26081", "city": "Wyoming",
        "contaminants": ["Benzene", "Chloroethane", "CFCs", "Chromium", "Copper",
                         "Cyanide", "Dichloroethane", "Lead", "TCE", "Toluene"],
        "years_active": "1952-1991",
        "description": "A 5-acre bulk-chemical transfer and repackaging plant that operated "
                       "1952-1991, handling aromatic solvents, chlorinated solvents, lacquer "
                       "thinners, and ethers. Before 1963 the company discharged wastewater "
                       "directly into the ground. In 1981 nearby residential wells were found "
                       "contaminated with VOCs and had to be abandoned, and residents were "
                       "connected to municipal water. The site was proposed for the NPL in "
                       "December 1982 and finalized in September 1983. A 2015 soil excavation "
                       "found discolored soil with high metals and VOC levels, and EGLE performed "
                       "remedial excavation in 2023; PFAS (PFOS/PFOA) has also been detected "
                       "on-site. The site lies in a densely populated industrial/residential area.",
        "npl_listed": True, "npl_date": "1983-09-08",
        "category": "chemical_manufacturing",
    },
    "motor_wheel_lansing": {
        "company": "Motor Wheel Inc.",
        "site_name": "Motor Wheel Inc. Superfund Site",
        "lat": 42.7325, "lng": -84.5556,
        "county": "Ingham", "county_fips": "26065", "city": "Lansing",
        "contaminants": ["VOCs", "Heavy metals", "Petroleum"],
        "description": "Motor Wheel Inc. manufactured automotive wheels and brake components in "
                       "Lansing. The associated disposal area received foundry sands, industrial "
                       "sludges, and spent solvents over decades of operation, contaminating soil "
                       "and groundwater in Ingham County with volatile organic compounds, heavy "
                       "metals, and petroleum hydrocarbons. The site was addressed under the "
                       "Superfund program with waste containment/capping and groundwater controls.",
        "npl_listed": True, "category": "auto_manufacturing",
    },
    "basf_wyandotte": {
        "company": "BASF (formerly Wyandotte Chemicals Corp.)",
        "site_name": "BASF Northworks Wyandotte",
        "lat": 42.2042, "lng": -83.1519,
        "county": "Wayne", "county_fips": "26163", "city": "Wyandotte",
        "status": "PFAS investigation",
        "contaminants": ["PFAS", "Mercury", "Chlorinated solvents", "Heavy metals"],
        "description": "The Wyandotte complex on the Detroit River has been a major "
                       "chemical-manufacturing center for over a century, operated by Wyandotte "
                       "Chemicals Corporation and later by BASF. Long-running production of alkalis, "
                       "chlorine-based and specialty chemicals left legacy contamination — including "
                       "mercury, chlorinated solvents, and heavy metals — in soil, river sediment, "
                       "and groundwater along the Detroit River. PFAS has been identified more "
                       "recently through Michigan's MPART investigation. Cleanup and monitoring are "
                       "conducted under state oversight.",
        "affected_waterways": ["Detroit River"],
        "npl_listed": False, "category": "chemical_manufacturing",
    },
    "roto_finish_kalamazoo": {
        "company": "Roto-Finish Co. Inc.",
        "site_name": "Roto-Finish Co. Superfund Site",
        "lat": 42.2917, "lng": -85.5872,
        "county": "Kalamazoo", "county_fips": "26077", "city": "Kalamazoo",
        "contaminants": ["Benzene", "Chlorobenzene", "Dichloroethane",
                         "Ethylbenzene", "Methylene chloride", "TCE", "Xylenes"],
        "description": "Manufacturer of vibratory finishing and deburring equipment. Plant "
                       "operations contaminated soil and groundwater with a wide range of volatile "
                       "organic compounds, including benzene, chlorobenzene, chloroethane, "
                       "dichloroethanes, ethylbenzene, methylene chloride, trichloroethylene (TCE), "
                       "toluene, and xylenes. The site is on the National Priorities List, with "
                       "groundwater contamination in the Kalamazoo area addressed under EPA oversight.",
        "npl_listed": True, "category": "industrial_manufacturing",
    },
    "rockwell_allegan": {
        "company": "Rockwell International Corp.",
        "site_name": "Rockwell International Corp. Superfund Site (Allegan)",
        "lat": 42.5292, "lng": -85.8553,
        "county": "Allegan", "county_fips": "26005", "city": "Allegan",
        "contaminants": ["TCE", "DCE", "Vinyl chloride", "Heavy metals"],
        "description": "Former Rockwell International manufacturing plant in Allegan. Industrial "
                       "operations used chlorinated degreasing solvents, principally "
                       "trichloroethylene (TCE); releases to soil allowed TCE and its anaerobic "
                       "breakdown products — 1,2-dichloroethene (DCE) and vinyl chloride — to "
                       "migrate into the underlying groundwater, forming a contaminant plume "
                       "addressed under the federal Superfund program with groundwater treatment.",
        "npl_listed": True, "category": "industrial_manufacturing",
    },
    "packaging_corp_filer_city": {
        "company": "Packaging Corp. of America",
        "site_name": "Packaging Corp. of America Superfund Site",
        "lat": 44.2172, "lng": -86.3222,
        "county": "Manistee", "county_fips": "26101", "city": "Filer City",
        "contaminants": ["Heavy metals", "VOCs"],
        "description": "Packaging Corporation of America operated a paper mill at Filer City in "
                       "Manistee County. Mill wastes and on-site disposal (landfill and lagoon/ "
                       "settling areas) contaminated soil and groundwater with heavy metals and "
                       "volatile organic compounds near Manistee Lake. The site was addressed "
                       "under the Superfund program.",
        "npl_listed": True, "category": "paper_manufacturing",
    },
}


PFAS_SITES = {
    "camp_grayling": {
        "company": "Michigan National Guard",
        "site_name": "Camp Grayling Military Installation",
        "lat": 44.6833, "lng": -84.7167,
        "county": "Crawford", "county_fips": "26039",
        "contaminants": ["PFAS", "AFFF"],
        "description": "Camp Grayling, the National Guard's largest training installation, used "
                       "aqueous film-forming foam (AFFF) containing PFAS during fire-training "
                       "exercises. PFAS (PFOS/PFOA) has been detected in on-site groundwater and has "
                       "migrated toward lakes and streams in the Grayling area, a region of sandy "
                       "soils and shallow water table that overlies drinking-water aquifers. "
                       "Michigan's MPART program is investigating the plume and sampling nearby "
                       "residential wells.",
        "status": "PFAS investigation", "npl_listed": False, "category": "military",
    },
    "selfridge_angb": {
        "company": "US Air National Guard",
        "site_name": "Selfridge Air National Guard Base",
        "lat": 42.6133, "lng": -82.8356,
        "county": "Macomb", "county_fips": "26099", "city": "Harrison Township",
        "contaminants": ["PFAS", "AFFF", "TCE"],
        "description": "Selfridge Air National Guard Base used AFFF firefighting foam containing "
                       "PFAS in training and emergency response. PFAS (PFOS/PFOA) has contaminated "
                       "groundwater beneath the base on the shore of Lake St. Clair, and the "
                       "Department of Defense and Michigan's MPART are investigating migration and "
                       "potential impacts to surface water and drinking-water sources. The base also "
                       "carries legacy chlorinated-solvent (TCE) contamination.",
        "status": "PFAS investigation", "npl_listed": False, "category": "military",
    },
    "us_ecology_romulus": {
        "company": "US Ecology Inc.",
        "site_name": "US Ecology Romulus",
        "lat": 42.2200, "lng": -83.3700,
        "county": "Wayne", "county_fips": "26163", "city": "Romulus",
        "contaminants": ["PFAS", "Hazardous waste"],
        "description": "US Ecology's Romulus facility is a commercial hazardous-waste treatment, "
                       "storage, and disposal operation near Detroit Metropolitan Airport. Because "
                       "it received diverse industrial wastes, PFAS has been detected in groundwater "
                       "at and around the site, and it is part of Michigan's MPART PFAS "
                       "investigations of the Romulus / lower Rouge River area, where shallow "
                       "groundwater discharges toward local drains and surface water.",
        "status": "PFAS investigation", "npl_listed": False, "category": "waste_disposal",
    },
    "dtw_airport": {
        "company": "Wayne County Airport Authority",
        "site_name": "Detroit Metropolitan Wayne County Airport",
        "lat": 42.2125, "lng": -83.3533,
        "county": "Wayne", "county_fips": "26163", "city": "Romulus",
        "contaminants": ["PFAS", "AFFF"],
        "description": "Detroit Metropolitan Wayne County Airport, Michigan's busiest airport, used "
                       "AFFF firefighting foam containing PFAS for aircraft-fire training and "
                       "emergency response, as required for commercial airports. PFAS has been "
                       "detected in airport-area groundwater and in stormwater/drainage that feeds "
                       "local surface waters, and it is one of numerous Michigan airport PFAS sites "
                       "under MPART investigation.",
        "status": "PFAS investigation", "npl_listed": False, "category": "pfas",
    },
    "gerald_ford_airport": {
        "company": "Gerald R. Ford International Airport",
        "site_name": "Gerald R. Ford International Airport PFAS Site",
        "lat": 42.8808, "lng": -85.5228,
        "county": "Kent", "county_fips": "26081", "city": "Grand Rapids",
        "contaminants": ["PFAS", "AFFF"],
        "description": "Gerald R. Ford International Airport in the Grand Rapids area used AFFF "
                       "firefighting foam containing PFAS. PFAS discharges reached the airport's "
                       "stormwater and retention system and contaminated groundwater and nearby "
                       "surface water in Kent County. The airport authority installed treatment "
                       "(including a granular activated-carbon system) and continues monitoring "
                       "under MPART oversight.",
        "status": "PFAS investigation", "npl_listed": False, "category": "pfas",
    },
}
