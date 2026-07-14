"""
Hardcoded Michigan CWD baseline data (compiled from Michigan DNR press
releases through February 2026) plus approximate township centroids.

The MI DNR publishes per-season CWD test results behind JavaScript-rendered
tables; this module is the static fallback the loader uses.

Coordinates for townships are approximate centroids (PLSS centers) used
purely for placing markers on the map. They are sourced from publicly
available Michigan civil-township geographic data and rounded to 2 decimals.
"""

# 18 counties with confirmed CWD in wild deer (Feb 2026).
CWD_WILD_DEER_COUNTIES = {
    "Ingham":     {"first_detected": "2015-05-26", "positives": 45, "fips": "26065",
                   "townships": ["Meridian"],
                   "notes": "First wild deer CWD case in Michigan"},
    "Clinton":    {"first_detected": "2015-01-01", "positives": 30, "fips": "26037",
                   "townships": ["Bath", "DeWitt"],
                   "notes": "Adjacent to Ingham, early core area"},
    "Eaton":      {"first_detected": "2016-01-01", "positives": 15, "fips": "26045",
                   "townships": ["Delta", "Windsor"],
                   "notes": "Southwest of Lansing"},
    "Ionia":      {"first_detected": "2017-01-01", "positives": 20, "fips": "26067",
                   "townships": ["Portland", "Boston"],
                   "notes": "Spread northward"},
    "Montcalm":   {"first_detected": "2017-01-01", "positives": 167, "fips": "26117",
                   "townships": ["Sidney", "Eureka", "Bloomer", "Pine"],
                   "notes": "HIGHEST concentration — epicenter of CWD in Michigan"},
    "Kent":       {"first_detected": "2017-01-01", "positives": 25, "fips": "26081",
                   "townships": ["Lowell", "Vergennes"],
                   "notes": "First wild case; farmed cases since 2008"},
    "Gratiot":    {"first_detected": "2017-01-01", "positives": 12, "fips": "26057",
                   "townships": ["Hamilton", "Washington"],
                   "notes": "Central Lower Peninsula"},
    "Jackson":    {"first_detected": "2018-01-01", "positives": 39, "fips": "26075",
                   "townships": ["Parma", "Sandstone"],
                   "notes": "Southern spread"},
    "Isabella":   {"first_detected": "2018-01-01", "positives": 8, "fips": "26073",
                   "townships": ["Coe", "Deerfield"],
                   "notes": "North-central spread"},
    "Dickinson":  {"first_detected": "2018-01-01", "positives": 3, "fips": "26043",
                   "townships": ["Breitung"],
                   "notes": "ONLY Upper Peninsula county with CWD"},
    "Hillsdale":  {"first_detected": "2019-01-01", "positives": 5, "fips": "26059",
                   "townships": ["Cambria"],
                   "notes": "Southern Lower Peninsula"},
    "Midland":    {"first_detected": "2020-01-01", "positives": 4, "fips": "26111",
                   "townships": ["Lee"],
                   "notes": "North-central expansion"},
    "Mecosta":    {"first_detected": "2023-07-01", "positives": 2, "fips": "26107",
                   "townships": ["Millbrook"],
                   "notes": "Adjacent to Montcalm epicenter"},
    "Ogemaw":     {"first_detected": "2023-10-31", "positives": 2, "fips": "26129",
                   "townships": ["Klacking"],
                   "notes": "Northern expansion, sick doe report"},
    "Washtenaw":  {"first_detected": "2025-03-12", "positives": 1, "fips": "26161",
                   "townships": ["Salem"],
                   "notes": "Southeastern spread, adjacent to Jackson County"},
    "Genesee":    {"first_detected": "2025-09-24", "positives": 1, "fips": "26049",
                   "townships": ["Gaines"],
                   "notes": "Southeast LP, sick doe walked up to officer"},
    "Allegan":    {"first_detected": "2025-11-13", "positives": 1, "fips": "26005",
                   "townships": ["Leighton"],
                   "notes": "SW Michigan, adjacent to Kent County"},
    "Gladwin":    {"first_detected": "2026-02-12", "positives": 1, "fips": "26051",
                   "townships": ["Clement"],
                   "notes": "Most recent detection, hunter-harvested"},
}

# Approximate township centroids (lat, lon) — used for marker placement only.
TOWNSHIP_COORDS = {
    "Meridian":   (42.74, -84.41),
    "Bath":       (42.84, -84.43),
    "DeWitt":     (42.87, -84.59),
    "Delta":      (42.72, -84.66),
    "Windsor":    (42.66, -84.74),
    "Portland":   (42.87, -84.91),
    "Boston":     (42.95, -85.00),
    "Sidney":     (43.21, -85.04),
    "Eureka":     (43.20, -84.93),
    "Bloomer":    (43.30, -84.94),
    "Pine":       (43.36, -85.18),
    "Lowell":     (42.93, -85.34),
    "Vergennes":  (42.98, -85.32),
    "Hamilton":   (43.27, -84.43),
    "Washington": (43.17, -84.55),
    "Parma":      (42.27, -84.66),
    "Sandstone":  (42.27, -84.55),
    "Coe":        (43.62, -84.69),
    "Deerfield":  (43.71, -84.94),
    "Breitung":   (45.85, -88.07),
    "Cambria":    (41.92, -84.81),
    "Lee":        (43.71, -84.43),
    "Millbrook":  (43.50, -85.07),
    "Klacking":   (44.41, -84.04),
    "Salem":      (42.43, -83.66),
    "Gaines":     (42.86, -83.86),
    "Leighton":   (42.73, -85.61),
    "Clement":    (44.07, -84.36),
}

# Statewide surveillance figures.
SURVEILLANCE_STATS = {
    "total_tested": 148_800,
    "total_positives_wild": 378,
    "positivity_rate": 0.00254,
    "surveillance_start_year": 2002,
    "first_detection_year": 2015,
    "positive_counties": 18,
    "total_counties": 83,
}

# Farmed cervid CWD facilities (MDARD).
CWD_FARMED_DEER = {
    "Kent":     {"facilities": 2, "first_detected": "2008-01-01", "fips": "26081",
                 "notes": "First CWD in Michigan (captive)"},
    "Mecosta":  {"facilities": 4, "first_detected": "2017-01-01", "fips": "26107",
                 "notes": "Multiple facilities affected"},
    "Montcalm": {"facilities": 3, "first_detected": "2017-01-01", "fips": "26117",
                 "notes": "Linked to wild deer epicenter"},
    "Newaygo":  {"facilities": 2, "first_detected": "2023-01-01", "fips": "26123",
                 "notes": "No wild deer positives in county"},
    "Lake":     {"facilities": 1, "first_detected": None,          "fips": "26085",
                 "notes": "Referenced in 2025 article"},
    "Osceola":  {"facilities": 1, "first_detected": "2025-03-11", "fips": "26133",
                 "notes": "Most recent farmed CWD"},
}

# DNR focused-surveillance county groupings, by year.
SURVEILLANCE_YEARS = {
    2021: ["Allegan", "Barry", "Berrien", "Branch", "Calhoun", "Cass",
           "Kalamazoo", "St. Joseph", "Van Buren",
           "Gladwin", "Roscommon"],
    2022: ["Genesee", "Lapeer", "Lenawee", "Livingston", "Monroe",
           "Oakland", "Shiawassee", "St. Clair", "Washtenaw"],
    2023: ["Alcona", "Alpena", "Antrim", "Arenac", "Bay", "Benzie",
           "Charlevoix", "Clare", "Crawford", "Emmet", "Grand Traverse",
           "Iosco", "Kalkaska", "Lake", "Leelanau", "Manistee", "Mason",
           "Missaukee", "Newaygo", "Oceana", "Osceola", "Oscoda", "Otsego",
           "Presque Isle", "Roscommon", "Wexford"],
    2024: ["Cheboygan", "Chippewa", "Delta", "Gogebic", "Iron",
           "Luce", "Mackinac", "Marquette", "Menominee", "Montmorency",
           "Schoolcraft"],
    2025: ["Baraga", "Chippewa", "Dickinson", "Houghton", "Iosco",
           "Keweenaw", "Luce", "Mackinac", "Ogemaw", "Ontonagon",
           "Schoolcraft"],
}
