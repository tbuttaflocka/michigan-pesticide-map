"""
Pesticide active-ingredient -> functional category mapping.

This is a curated reference table built from EPA labels and university
extension publications. It maps the active-ingredient names that appear
in the USGS NAWQA EPest county-level files to one of:
    herbicide   — kills weeds
    insecticide — kills insects / mites / nematodes
    fungicide   — kills fungi / oomycetes / bactericides
    growth_regulator — plant growth regulators, defoliants, ripening
    other       — fumigants, adjuvants, mineral/biological actives that
                  don't fit one bucket cleanly

If a compound isn't in this table, `categorize()` returns 'other'.
"""

HERBICIDES = {
    "2,4-D", "2,4-DB", "ACETOCHLOR", "ACIFLUORFEN", "ALACHLOR", "AMINOPYRALID",
    "ATRAZINE", "BENSULIDE", "BENTAZONE", "BROMACIL", "BROMOXYNIL",
    "CARFENTRAZONE-ETHYL", "CHLORIMURON", "CHLORSULFURON", "CLETHODIM",
    "CLOMAZONE", "CLOPYRALID", "CLORANSULAM-METHYL", "CLOTHIANIDIN-SEED",
    "CYCLOATE", "DICAMBA", "DICHLOBENIL", "DIFLUFENZOPYR", "DIMETHENAMID",
    "DIMETHENAMID-P", "DIQUAT", "DIURON", "DSMA", "EPTC", "ETHALFLURALIN",
    "ETHOFUMESATE", "FENOXAPROP", "FLUAZIFOP", "FLUFENACET", "FLUMETSULAM",
    "FLUMICLORAC", "FLUMIOXAZIN", "FLUROXYPYR", "FLUTHIACET-METHYL",
    "FOMESAFEN", "FORAMSULFURON", "GLUFOSINATE", "GLYPHOSATE", "HALOSULFURON",
    "HEXAZINONE", "IMAZAMOX", "IMAZAPIC", "IMAZAPYR", "IMAZAQUIN",
    "IMAZETHAPYR", "INDAZIFLAM", "IODOSULFURON", "ISOXAFLUTOLE", "LACTOFEN",
    "LINURON", "MCPA", "MCPB", "MESOTRIONE", "METHYL BROMIDE-HERB",
    "METOLACHLOR", "METOLACHLOR-S",
    "METRIBUZIN", "METSULFURON", "MOLINATE", "MSMA", "NAPROPAMIDE",
    "NICOSULFURON", "NORFLURAZON", "ORYZALIN", "OXADIAZON", "OXYFLUORFEN",
    "PARAQUAT", "PEBULATE", "PENDIMETHALIN", "PETROLEUM DISTILLATE",
    "PICLORAM", "PRIMISULFURON", "PROMETON", "PROMETRYN", "PRONAMIDE",
    "PROPACHLOR", "PROPANIL", "PROSULFURON", "PYRAFLUFEN ETHYL",
    "PYRASULFOTOLE", "PYRIMISULFAN", "PYRITHIOBAC-SODIUM", "PYROXASULFONE",
    "PYROXSULAM", "QUINCLORAC", "QUINOXYFEN", "QUIZALOFOP", "RIMSULFURON",
    "SAFLUFENACIL", "SETHOXYDIM", "SIDURON", "SIMAZINE", "SODIUM CHLORATE",
    "SULFENTRAZONE", "SULFOMETURON", "SULFOSULFURON", "TEMBOTRIONE",
    "TERBACIL", "THIENCARBAZONE-METHYL", "THIFENSULFURON", "TOPRAMEZONE",
    "TRALKOXYDIM", "TRIALLATE", "TRIASULFURON", "TRIBENURON METHYL",
    "TRICLOPYR", "TRIFLURALIN", "TRINEXAPAC-ETHYL",
}

INSECTICIDES = {
    "ABAMECTIN", "ACEPHATE", "ACETAMIPRID", "ALDICARB", "AZADIRACHTIN",
    "AZINPHOS-METHYL", "BACILLUS THURINGIENSIS", "BACILLUS FIRMUS",
    "BIFENAZATE", "BIFENTHRIN", "BORAX", "BUPROFEZIN", "CARBARYL",
    "CARBOFURAN", "CHLORANTRANILIPROLE", "CHLOROPICRIN", "CHLORPYRIFOS",
    "CLOFENTEZINE", "CLOTHIANIDIN", "CYANTRANILIPROLE", "CYFLUMETOFEN",
    "CYFLUTHRIN", "CYHALOTHRIN-GAMMA", "CYHALOTHRIN-LAMBDA", "CYPERMETHRIN",
    "CYROMAZINE", "DELTAMETHRIN", "DIAZINON", "DICOFOL", "DICROTOPHOS",
    "DIFLUBENZURON", "DIMETHOATE", "DINOTEFURAN", "DISULFOTON", "EMAMECTIN",
    "ENDOSULFAN", "ESFENVALERATE", "ETHOPROPHOS", "ETOXAZOLE", "FENAMIPHOS",
    "FENBUTATIN-OXIDE", "FENPROPATHRIN", "FENPYROXIMATE", "FIPRONIL",
    "FLONICAMID", "FLUBENDIAMIDE", "FLUPYRADIFURONE", "FORMETANATE HCL",
    "HEXYTHIAZOX", "IMIDACLOPRID", "INDOXACARB", "KAOLIN CLAY",
    "MALATHION", "METHAMIDOPHOS", "METHIDATHION", "METHOMYL", "METHOXYFENOZIDE",
    "MEVINPHOS", "MILBEMECTIN", "NALED", "NOVALURON", "OXAMYL", "OXYDEMETON",
    "OXYDEMETON-METHYL", "PERMETHRIN", "PHORATE", "PHOSMET", "PROFENOFOS",
    "PROPARGITE", "PYMETROZINE", "PYRETHRINS", "PYRIDABEN", "PYRIPROXYFEN",
    "PYRIDALYL", "ROTENONE", "SPINETORAM", "SPINOSAD", "SPINOSYN",
    "SPIRODICLOFEN", "SPIROMESIFEN", "SPIROTETRAMAT", "SULFOXAFLOR",
    "TEBUFENOZIDE", "TEBUPIRIMPHOS", "TEFLUTHRIN", "TERBUFOS", "THIACLOPRID",
    "THIAMETHOXAM", "THIODICARB", "TOLFENPYRAD", "ZETA-CYPERMETHRIN",
}

FUNGICIDES = {
    "ACIBENZOLAR", "AZOXYSTROBIN", "BACILLUS PUMILIS", "BACILLUS SUBTILIS",
    "BENALAXYL", "BENOMYL", "BENZOVINDIFLUPYR", "BOSCALID", "CALCIUM POLYSULFIDE",
    "CAPTAN", "CARBOXIN", "CHLOROTHALONIL", "CONIOTHYRIUM MINITANS",
    "COPPER", "COPPER HYDROXIDE", "COPPER OCTANOATE", "COPPER OXYCHLORIDE",
    "COPPER OXYCHLORIDE S", "COPPER SULFATE", "CYAZOFAMID", "CYMOXANIL",
    "CYPRODINIL", "DICHLORAN", "DIFENOCONAZOLE", "DODINE", "ETHABOXAM",
    "ETRIDIAZOLE", "FAMOXADONE", "FENAMIDONE", "FENARIMOL", "FENBUCONAZOLE",
    "FENHEXAMID", "FENPROPIDIN", "FENPYRAZAMINE", "FENTIN", "FERBAM",
    "FLUAZINAM", "FLUDIOXONIL", "FLUFENOXURON", "FLUOPICOLIDE", "FLUOPYRAM",
    "FLUOXASTROBIN", "FLUSILAZOLE", "FLUTOLANIL", "FLUTRIAFOL", "FLUXAPYROXAD",
    "FOSETYL", "FOSETYL-AL", "HARPIN PROTEIN", "HYDRATED LIME",
    "HYDROGEN PEROXIDE", "HYMEXAZOL", "IPCONAZOLE", "IPRODIONE",
    "ISOFETAMID", "KRESOXIM-METHYL", "MANCOZEB", "MANDIPROPAMID", "MANEB",
    "MEFENOXAM", "METALAXYL", "METCONAZOLE", "METIRAM", "MILDEX",
    "MYCLOBUTANIL", "OXYTETRACYCLINE", "PCNB", "PENCYCURON", "PENFLUFEN",
    "PENTHIOPYRAD", "PHOSPHORIC ACID", "PICOXYSTROBIN", "POLYOXIN-D",
    "PROCHLORAZ", "PROPAMOCARB HCL", "PROPICONAZOLE", "PROTHIOCONAZOLE",
    "PYRACLOSTROBIN", "PYRIMETHANIL", "PYRIOFENONE", "QUINOXYFEN-FUNG",
    "QUINTOZENE", "SILTHIOFAM", "SOLATENOL", "STREPTOMYCIN", "SULFUR",
    "TEBUCONAZOLE", "TETRACONAZOLE", "THIABENDAZOLE", "THIOPHANATE-METHYL",
    "THIRAM", "TOLCLOFOS-METHYL", "TRIADIMEFON", "TRIADIMENOL", "TRIFLOXYSTROBIN",
    "TRIFLUMIZOLE", "TRITICONAZOLE", "VINCLOZOLIN", "ZIRAM", "ZOXAMIDE",
}

GROWTH_REGULATORS = {
    "1-METHYLCYCLOPROPENE", "1-NAPHTHALENEACETAMIDE", "6-BENZYLADENINE",
    "ABA", "AVIGLYCINE", "CYTOKININ", "ETHEPHON", "FORCHLORFENURON",
    "GIBBERELLIC ACID", "MALEIC HYDRAZIDE", "MEPIQUAT", "NAPHTHYLACETIC ACID",
    "PROHEXADIONE", "PROHEXADIONE-CALCIUM", "THIDIAZURON", "UNICONAZOLE",
}

OTHER_OR_FUMIGANT = {
    "1,3-DICHLOROPROPENE", "CHLOROPICRIN-FUM", "DAZOMET", "DIMETHYL DISULFIDE",
    "METAM", "METAM-POTASSIUM", "METAM-SODIUM", "METHYL BROMIDE",
    "METHYL ISOTHIOCYANATE", "PETROLEUM OIL", "TETRABOROHYDRATE",
}

# ---- corrections: compounds that were falling through to "Other" ----
# Each was VERIFIED as the class below against a real source — Wikipedia, the
# BCPC Compendium of Pesticide Common Names, the University of Hertfordshire
# Pesticide Properties DataBase (PPDB), EPA/EFSA/OEHHA assessments, or the USGS
# NAWQA compound listing / peer-reviewed refs. Compounds whose class could not be
# confidently verified (biologicals, oils, adjuvants/synergists, minerals,
# molluscicides, nematicides, antibiotics, biostimulants, dual-use PGRs) are
# deliberately LEFT in "Other" rather than guessed. Spellings match the USGS
# EPest data. Applied in place so _ALL_BUCKETS / _KNOWN_BASES pick them up.
HERBICIDES.update({
    "CYANAZINE", "CHLORIDAZON", "BUTYLATE", "SULFOSATE", "DESMEDIPHAM",
    "PHENMEDIPHAM", "CHLORAMBEN", "NAPTALAM", "DIETHATYL", "DINOSEB",
    "BENFLURALIN", "DICHLORPROP", "DCPA", "DALAPON", "TRIDIPHANE", "TERBUTRYN",
    "AMETRYN", "TEBUTHIURON", "FLUOMETURON", "TRIFLUSULFURON", "ISOPROPALIN",
    "ISOXABEN", "PROPYZAMIDE", "MECOPROP", "DICLOFOP", "PYRIDATE", "TRI-ALLATE",
    "MESOSULFURON", "AMITROLE", "ENDOTHAL", "BICYCLOPYRONE", "DIPHENAMID",
    "FLUCARBAZONE", "IMAZAMETHABENZ", "PINOXADEN", "FLORASULAM", "IMAZOSULFURON",
    "BENSULFURON", "HALAUXIFEN",
})
INSECTICIDES.update({
    "FONOFOS", "PARATHION", "METHYL PARATHION", "CHLORETHOXYFOS", "PHOSPHAMIDON",
    "DEMETON", "LINDANE", "METHOXYCHLOR", "FENVALERATE", "ALPHA CYPERMETHRIN",
    "AMITRAZ", "CHLORFENAPYR", "TRIMETHACARB", "CRYOLITE", "BENDIOCARB",
    "FORMETANATE", "FENBUTATIN OXIDE", "FENOXYCARB", "TRIAZAMATE", "ACEQUINOCYL",
    "DIENOCHLOR",
})
FUNGICIDES.update({
    "DIMETHOMORPH", "TRIFORINE", "CYPROCONAZOLE", "AMETOCTRADIN", "ANILAZINE",
    "CHINOMETHIONAT", "OXATHIAPIPROLIN", "CYFLUFENAMID", "DINOCAP", "ZINEB",
    "CAPTAFOL", "SEDAXANE", "IMAZALIL", "DICLORAN",
    # copper fungicides, consistent with COPPER / COPPER SULFATE already classed here
    "CUPROUS OXIDE", "COPPER SULF TRIBASIC",
})
GROWTH_REGULATORS.update({
    "1-METHYL CYCLOPROPENE", "NAPHTHYLACETAMIDE", "INDOLYL-BUTYRIC ACID",
})


# High-profile compounds surfaced in the UI's quick-filter
FEATURED_COMPOUNDS = [
    "GLYPHOSATE",
    "ATRAZINE",
    "2,4-D",
    "METOLACHLOR",
    "CHLORPYRIFOS",
    "DICAMBA",
    "ACETOCHLOR",
    "IMIDACLOPRID",
    "MESOTRIONE",
]


_ALL_BUCKETS = (
    ("herbicide",        HERBICIDES),
    ("insecticide",      INSECTICIDES),
    ("fungicide",        FUNGICIDES),
    ("growth_regulator", GROWTH_REGULATORS),
    ("other",            OTHER_OR_FUMIGANT),
)
_KNOWN_BASES = HERBICIDES | INSECTICIDES | FUNGICIDES | GROWTH_REGULATORS | OTHER_OR_FUMIGANT


def _strip_isomer_suffix(name: str) -> str:
    """Strip a single recognized isomer/stereo suffix (e.g. -S, -P) when the
    base name without it is a known active ingredient."""
    for suf in ("-S", "-P", "-D", "-AL", "-METHYL", "-ETHYL", "-SODIUM", "-POTASSIUM", "-HCL"):
        if name.endswith(suf) and name[: -len(suf)] in _KNOWN_BASES:
            return name[: -len(suf)]
    return name


# ---- sub-types WITHIN the "Other" bucket (for the trend "Other" breakdown) ----
# "Other" in USGS EPest is a catch-all for pesticide types outside the primary
# three (herbicide / insecticide / fungicide). These curated sub-type sets let the
# UI label the biggest drivers — above all soil FUMIGANTS, which are applied at
# very high rates and produce large poundage from relatively little acreage, so
# they often dominate a county's "Other" share (e.g. metam-sodium on potatoes). A
# compound that can't be classified confidently is left UNLABELLED, not guessed.
FUMIGANTS = {
    "1,3-DICHLOROPROPENE", "DICHLOROPROPENE", "CHLOROPICRIN", "CHLOROPICRIN-FUM",
    "DAZOMET", "DIMETHYL DISULFIDE", "DIMETHLYDISULFIDE", "METAM", "METAM-POTASSIUM",
    "METAM POTASSIUM", "METAM-SODIUM", "METHYL BROMIDE", "METHYL ISOTHIOCYANATE",
    "SODIUM TETRATHIOCARBONATE", "TETRATHIOCARBONATE",
}
# Dedicated soil nematicides that fall in "Other" (most others — fenamiphos,
# oxamyl, aldicarb, ethoprophos — are classed as insecticides, not "Other").
NEMATICIDES = {"FLUENSULFONE", "FOSTHIAZATE"}
# Plant growth regulators reuse GROWTH_REGULATORS (they fold into "Other").
_SUBTYPE_BUCKETS = (
    ("fumigant", FUMIGANTS),
    ("nematicide", NEMATICIDES),
    ("plant growth regulator", GROWTH_REGULATORS),
)


def subtype(compound: str) -> str | None:
    """Sub-type label for a compound within the 'Other' bucket, or None when it
    can't be confidently classified (the UI then shows it without a sub-type
    label rather than guessing). Mirrors categorize()'s name normalization."""
    if not compound:
        return None
    name = compound.strip().upper()
    for sep in (" & ", "/", " AND "):
        if sep in name:
            for part in name.split(sep):
                st = subtype(part.strip())
                if st:
                    return st
            return None
    base = _strip_isomer_suffix(name)
    for label, bucket in _SUBTYPE_BUCKETS:
        if name in bucket or base in bucket:
            return label
    return None


def categorize(compound: str) -> str:
    """Return the functional category for a compound name.

    Handles the combined names introduced in the USGS 2013-2019 releases —
    e.g. "METOLACHLOR & METOLACHLOR-S" — by categorizing each constituent
    and returning the shared bucket.
    """
    if not compound:
        return "other"
    name = compound.strip().upper()

    # Combined names: "A & B" or "A/B" — categorize both halves.
    parts = []
    for sep in (" & ", "/", " AND "):
        if sep in name:
            parts = [p.strip() for p in name.split(sep)]
            break
    if parts:
        cats = {categorize(p) for p in parts if p}
        # Drop "other" if any part is more specific; otherwise return any.
        cats.discard("other")
        if len(cats) == 1:
            return next(iter(cats))
        if cats:
            return next(iter(cats))
        return "other"

    base = _strip_isomer_suffix(name)
    for label, bucket in _ALL_BUCKETS:
        if name in bucket or base in bucket:
            return label
    return "other"
