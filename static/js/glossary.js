// Plain-language glossary + statistics interpreters, shared across the app so
// definitions and "what does this number mean" translations are consistent
// everywhere. Exposed as window.PMGloss. Loaded before app.js.
(function () {
  // ---------- glossary: technical term -> plain-language definition ----------
  const GLOSSARY = {
    // ---- Coal combustion residuals (coal ash) ----
    'coal combustion residuals':
      'The waste left over from burning coal to make electricity — commonly called ' +
      '"coal ash." It includes fly ash, bottom ash, boiler slag, and flue-gas ' +
      'desulfurization material, and contains toxic metals such as arsenic, lead, ' +
      'lithium, boron, and selenium. Abbreviated CCR.',
    'CCR': 'Coal combustion residuals — "coal ash," the waste from burning coal. It ' +
      'contains toxic metals (arsenic, lead, lithium, boron, and more).',
    'coal ash': 'The everyday name for coal combustion residuals (CCR) — the ash and ' +
      'other waste left from burning coal. Contains arsenic, lead, lithium and other toxics.',
    'fly ash':
      'The fine, powdery ash carried up with the flue gases when coal is burned and ' +
      'captured by pollution controls. The most voluminous type of coal ash.',
    'bottom ash':
      'The coarser, heavier ash that falls to the bottom of a coal furnace (as opposed ' +
      'to the fine fly ash carried up the stack).',
    'boiler slag':
      'A glassy, granular coal-ash material formed when molten bottom ash is cooled ' +
      'quickly with water in certain (wet-bottom) boilers.',
    'flue gas desulfurization material':
      'The residue from "scrubbers" that remove sulfur dioxide from coal-plant exhaust — ' +
      'a type of coal combustion residual (often a gypsum-like sludge).',
    'surface impoundment':
      'An "ash pond" — a diked basin where coal ash is mixed with water and stored. ' +
      'Older ones are often UNLINED, letting contaminants seep into groundwater; these ' +
      'are the higher-risk units the CCR rule most concerns.',
    'closure by removal':
      'Closing a coal-ash unit by DIGGING OUT the ash and hauling it to a lined landfill, ' +
      'then restoring the site. More protective than cap-in-place, because the ash no ' +
      'longer sits in contact with groundwater.',
    'cap-in-place':
      'Closing a coal-ash unit by leaving the ash where it is and covering it with a cap. ' +
      'Cheaper than removal, but the buried ash can keep contacting groundwater — a common ' +
      'point of dispute between utilities and watchdog groups.',
    'CCR rule':
      "EPA's 2015 federal Coal Combustion Residuals rule. It is SELF-IMPLEMENTING: each " +
      'utility must post its own groundwater monitoring, closure plans, and structural-' +
      'integrity data on its own public website (there is no central database).',
    'Legacy CCR Rule':
      "EPA's 2024 rule extending federal coal-ash requirements to previously unregulated " +
      'INACTIVE ("legacy") surface impoundments at retired plants, plus older CCR ' +
      'landfills and units that closed before the 2015 rule.',
    'legacy impoundment':
      'An inactive coal-ash pond at a retired plant that was exempt from the 2015 CCR rule ' +
      "but is now regulated under EPA's 2024 Legacy CCR Rule.",
    'age-adjusted':
      'Adjusted so places with older or younger populations can be compared fairly. ' +
      'Without this, a county full of retirees would look "sicker" just because ' +
      'older people get more diseases.',
    'incidence rate':
      'How many NEW cases are diagnosed each year, per 100,000 people. Higher = the ' +
      'disease is diagnosed more often here.',
    'mortality rate':
      'How many people DIE from a cause each year, per 100,000 people.',
    'rate per 100,000':
      'A way to compare places of different sizes: the number of cases you would see ' +
      'if the county had exactly 100,000 people.',
    'rate per 10,000':
      'A way to compare places of different sizes: the number of cases per 10,000 people.',
    'EPest estimate':
      'A USGS ESTIMATE of how much of a pesticide was used, modeled from crop acreage ' +
      'and proprietary sales data — not a direct measurement. Reported as a low–high range.',
    'EPest':
      'The USGS pesticide-use estimates this app maps. They cover AGRICULTURAL use only — ' +
      'modeled from crop acreage and sales data. Golf courses, lawns, parks, roadsides, and ' +
      'other non-agricultural uses are NOT included, so county totals here exclude them entirely.',
    'turfgrass management':
      'The practice of maintaining turf (grass) on golf courses, lawns, and sports fields. ' +
      'On golf courses it is unusually pesticide-intensive — especially fungicides, because ' +
      'closely-mown, heavily-watered greens face constant disease pressure.',
    'IPM':
      'Integrated Pest Management — a strategy that combines monitoring, cultural practices, ' +
      'and targeted pesticide use to control pests with less chemical than routine spraying. ' +
      'Some states require golf courses to file an IPM plan; Michigan does not.',
    'fungicide resistance':
      'When repeated use of the same fungicide breeds fungi that survive it, so it stops ' +
      'working. It drives golf-course superintendents to rotate among many fungicide classes, ' +
      'which is one reason golf turf receives such a wide variety of fungicides.',
    'non-agricultural pesticide use':
      'Pesticide use that is NOT on farm crops — golf courses, lawns, parks, roadsides, ' +
      'rights-of-way, and structures. The USGS EPest data this app maps covers agriculture ' +
      'only, so none of this use appears in the county pesticide totals.',
    'PFAS':
      'Per- and polyfluoroalkyl substances — a large family of synthetic "forever chemicals" ' +
      'used in firefighting foam, non-stick and stain-resistant coatings, and many industrial ' +
      'processes. They resist breaking down, build up in water, soil, fish, and people, and are ' +
      'linked to cancer, immune, thyroid, and developmental effects. Michigan runs the most ' +
      'aggressive state PFAS response program in the country (MPART).',
    'PFOA':
      'Perfluorooctanoic acid — one of the most-studied PFAS, formerly used to make Teflon and ' +
      'other coatings. EPA set an enforceable drinking-water limit of 4 parts per trillion in 2024.',
    'PFOS':
      'Perfluorooctanesulfonic acid — a PFAS formerly used in Scotchgard and firefighting foam. ' +
      'It bioaccumulates strongly in fish and is the main driver of Michigan fish-consumption ' +
      'advisories. EPA set an enforceable drinking-water limit of 4 parts per trillion in 2024.',
    'AFFF':
      'Aqueous Film-Forming Foam — a firefighting foam containing PFAS, used at airports, ' +
      'military bases, and fire-training sites. It is a major source of PFAS groundwater ' +
      'contamination at many Michigan Areas of Interest.',
    'parts per trillion':
      'A concentration unit (ppt) — one part in a trillion, roughly a single drop in 20 Olympic ' +
      'swimming pools. PFAS are toxic at extraordinarily low levels; EPA\'s drinking-water limit ' +
      'for PFOA and PFOS is just 4 ppt. Water results are often reported in ng/L, which equals ppt.',
    'Area of Interest':
      'An "AOI" is an area EGLE is investigating for PFAS where the SOURCE has not yet been ' +
      'determined. It flags a place where residential wells may be affected while the ' +
      'investigation is ongoing — distinct from a confirmed PFAS Site with an identified source.',
    'MPART':
      'The Michigan PFAS Action Response Team — the multi-agency state body (led by EGLE) that ' +
      'investigates PFAS contamination, samples water and fish, and publishes the live data ' +
      'behind this layer. Michigan\'s program is the most aggressive of any U.S. state.',
    'AOI':
      'Area of Interest — an area EGLE is investigating for PFAS where the SOURCE has not yet ' +
      'been confirmed. It flags a place where nearby residential wells may be affected while the ' +
      'investigation continues, distinct from a confirmed PFAS Site with an identified source.',
    'forever chemicals':
      'The nickname for PFAS — synthetic chemicals whose carbon–fluorine bonds are so strong they ' +
      'essentially don\'t break down in the environment or the body, so they persist for years and ' +
      'build up (bioaccumulate) over time.',
    'POTW':
      'Publicly Owned Treatment Works — a municipal wastewater (sewage) treatment plant. Some test ' +
      'for PFAS at their permitted discharge points; PFAS can pass through because these plants ' +
      'are not designed to remove it.',
    'bioaccumulation':
      'The buildup of a chemical in living tissue faster than the body can get rid of it, so ' +
      'concentrations rise up the food chain. PFOS bioaccumulates strongly in fish, which is why ' +
      'fish caught in contaminated waters can carry far higher PFAS levels than the water itself.',
    'UST':
      'Underground Storage Tank — a tank (usually fuel) buried at gas stations, ' +
      'fleet garages, farms, and businesses. Michigan has tens of thousands. Aging ' +
      'tanks and piping can leak petroleum into soil and groundwater, which is why ' +
      'they are the most common near-home contamination source.',
    'LUST':
      'Leaking Underground Storage Tank — a UST with a confirmed release of ' +
      'petroleum or other regulated substance. In Michigan these are handled under ' +
      'Part 213 and require corrective action (cleanup) until the release is closed.',
    'Part 211':
      'The Michigan law (administered by LARA) under which underground storage ' +
      'tanks are registered and LICENSED. A Part 211 tank is a legally operating ' +
      'tank — a working gas station\'s tanks — and is NOT, by itself, a contaminated ' +
      'site. It only becomes a Part 213 concern if it leaks.',
    'Part 213':
      'The Michigan law (administered by EGLE) governing LEAKING underground ' +
      'storage tanks — sites with a confirmed release that require investigation ' +
      'and corrective action. A Part 213 "open release" is active contamination ' +
      'still being cleaned up; a "closed" release has met cleanup criteria.',
    'corrective action':
      'The investigation and cleanup a responsible party must carry out after a ' +
      'confirmed release — characterizing the contamination, removing or treating ' +
      'it, and monitoring — until the site meets closure criteria.',
    'release closure':
      'The point at which EGLE agrees a leaking-tank release has been addressed to ' +
      'meet the applicable cleanup criteria and no further corrective action is ' +
      'required. A "closed" release has been remediated; an "open" one has not. ' +
      'Closure does not always mean every trace was removed — some sites close with ' +
      'residual contamination left in place under land-use restrictions.',
    'BTEX':
      'Benzene, toluene, ethylbenzene, and xylenes — four light petroleum chemicals ' +
      'that are the standard markers of a fuel release. Benzene is the biggest health ' +
      'concern (a known human carcinogen). Because they dissolve and move in ' +
      'groundwater, BTEX is what testing usually looks for after a tank leak.',
    'MTBE':
      'Methyl tert-butyl ether — a gasoline additive used from the late 1970s into ' +
      'the early 2000s to boost octane and cut emissions. It is extremely mobile in ' +
      'groundwater (it travels farther and faster than most fuel chemicals) and can ' +
      'be tasted or smelled at very low concentrations, so it often shows up first in ' +
      'a contaminated well.',
    'vapor intrusion':
      'When contamination in soil or groundwater gives off vapors that seep up through ' +
      'the ground and into the basements and crawlspaces of buildings, affecting the ' +
      'indoor air people breathe. It matters because it can happen even when a home is ' +
      'on municipal water and no one ever contacts the soil — which is why being close ' +
      'to a petroleum release is a concern beyond just drinking water.',
    'PAH':
      'Polycyclic aromatic hydrocarbons — a family of chemicals formed when fuel and ' +
      'other organic material burn or, in this context, present in heavier petroleum. ' +
      'Naphthalene is the most common one seen at fuel-tank releases. Several PAHs are ' +
      'considered probable human carcinogens.',
    'RIDE':
      'EGLE\'s Remediation Information Data Exchange — the state\'s public mapping ' +
      'system for contaminated sites, including leaking-tank releases, with per-site ' +
      'status, classification, and corrective-action detail.',
    'air toxics':
      'Hazardous air pollutants — chemicals in outdoor air known or suspected to ' +
      'cause cancer or other serious health effects (e.g. benzene, formaldehyde, ' +
      '1,3-butadiene, ethylene oxide). EPA models where they come from (industry, ' +
      'traffic, fires, natural sources) and the health risk they pose.',
    'hazard air pollutants (HAPs)':
      'The ~188 pollutants Congress listed in the Clean Air Act as hazardous — the ' +
      '"air toxics." They come from industry, vehicles, small area sources, and ' +
      'natural processes, and are regulated separately from the common "criteria" ' +
      'pollutants like ozone and soot.',
    'cancer risk in-a-million':
      'A way to express modeled cancer risk: how many extra cancer cases would be ' +
      'expected among a million people who breathed that air continuously outdoors ' +
      'for a 70-year lifetime. "20 in a million" means 20 extra cases per million ' +
      'people over a lifetime — a modeled estimate, not a count of real cases.',
    'hazard index':
      'A measure of NON-cancer risk: the modeled concentration of a pollutant ' +
      'divided by EPA\'s reference level for it, summed across pollutants that ' +
      'affect the same organ system (e.g. the respiratory tract). A hazard index ' +
      'at or below 1 is EPA\'s screening threshold below which noncancer effects ' +
      'are considered negligible; above 1 warrants a closer, case-by-case look. ' +
      'It is a modeled screening estimate, not a measurement.',
    'census block vs tract':
      'Two Census geographies. A census TRACT is a small statistical area of ' +
      'roughly 1,200–8,000 people (Michigan has ~2,800); a census BLOCK is much ' +
      'smaller still. This layer shades tracts — finer than counties, coarse enough ' +
      'to render and to match how EPA says the data should be used.',
    'screening assessment':
      'A modeled, nationwide first-cut that estimates risk from emissions ' +
      'inventories and dispersion models to FLAG places worth a closer look. It is ' +
      'not measured air and is not meant to determine risk at a specific home, ' +
      'school, or address — only to compare areas and guide further study.',
    'NATA':
      'EPA\'s National Air Toxics Assessment — the periodic nationwide screening ' +
      'study of air toxics health risk that this layer draws on. It was renamed ' +
      'AirToxScreen starting with the 2017 data year; the methods and caveats are ' +
      'the same — modeled estimates, not measurements. This layer shows the 2019 ' +
      'assessment.',
    // ---- air toxics SOURCE categories (EPA AirToxScreen/NATA definitions) ----
    'point source':
      'A specific, identifiable facility with permitted emission points — a factory, ' +
      'power plant, refinery, or incinerator — whose exact location EPA can pin to ' +
      'coordinates. In the air toxics model this is the "industry" category.',
    'nonpoint/area source':
      'Many small, diffuse sources that are each too small or too numerous to list ' +
      'individually but add up across an area: gas stations, dry cleaners, auto body ' +
      'shops, residential wood burning, consumer and personal-care products, paints, ' +
      'and solvents. EPA also calls these "area sources."',
    'on-road traffic':
      'Cars, trucks, buses, and motorcycles driven on roads and highways — the ' +
      '"on-road mobile" source category in EPA\'s air toxics model.',
    'non-road mobile':
      'Engines that are not driven on roads: construction and farm equipment, lawn ' +
      'and garden equipment, boats, trains, and aircraft. EPA\'s "non-road mobile" ' +
      'source category.',
    'fire emissions':
      'Air toxics released by wildfires and by prescribed and agricultural burning — ' +
      'the "fires" source category in the model.',
    'biogenic emissions':
      'Natural emissions from living things — mainly vegetation (trees and plants), ' +
      'plus soils and microbes. EPA\'s "biogenic" category; these are natural, not ' +
      'human-made.',
    'secondary formation':
      'Pollutants that are not released directly by anything, but FORM in the air ' +
      'when other emitted chemicals react with sunlight and each other (EPA calls ' +
      'this atmospheric transformation). Formaldehyde and acetaldehyde are the main ' +
      'ones. Because they form from precursor chemicals emitted by traffic, industry, ' +
      'solvents, and consumer products, a large "secondary" share still traces back ' +
      'to those sources indirectly — it just can\'t be pinned to one smokestack or ' +
      'tailpipe.',
    'background concentration':
      'Pollution already present in the air that EPA can\'t tie to any modeled local ' +
      'source — including long-range transport from outside the region, natural ' +
      'sources, and persistent chemicals lingering from past emissions. It is ' +
      'averaged over broad areas, so a large "background" share means the risk is not ' +
      'coming from nearby sources.',
    'precursor emissions':
      'The directly-emitted chemicals that later react in the air to form secondary ' +
      'pollutants. Traffic, industry, solvents, and consumer products emit precursors ' +
      'that sunlight and other reactions turn into pollutants like formaldehyde — so ' +
      '"secondary" risk ultimately traces back to these emissions.',
    'heating oil tank':
      'A tank that stored fuel oil to heat a home — buried in the yard or aboveground ' +
      'in a basement. Common in Michigan houses built before natural-gas service ' +
      'expanded (especially pre-1970s). These residential tanks generally were never ' +
      'required to be registered, so they do NOT appear in EGLE\'s storage-tank data — ' +
      'and buried ones were often abandoned in place rather than removed when a home ' +
      'switched to gas. An old tank can corrode and leak, and cleanup is usually not ' +
      'covered by homeowner\'s insurance.',
    'tank sweep':
      'A survey of a property to find a buried fuel tank, using metal detection or ' +
      'ground-penetrating radar. Environmental contractors — and some home inspectors — ' +
      'offer it as a standard service, so a buyer can check for an unregistered heating-' +
      'oil tank before purchasing a home.',
    'municipal course':
      'A golf course owned by a local government (city, county, or township) or another ' +
      'public body such as a public university. Because it is a "public body," its grounds ' +
      'records — including pesticide applications — can generally be requested under ' +
      "Michigan's Freedom of Information Act, unlike a privately-owned course.",
    'MCL':
      'Maximum Contaminant Level — the legal limit for a chemical in public drinking ' +
      'water, set by the EPA to protect HUMAN health. A result above the MCL exceeds the ' +
      'drinking-water safety threshold. This is different from an aquatic-life benchmark.',
    'spongy moth':
      'An invasive leaf-eating moth (Lymantria dispar, formerly called the "gypsy moth"). ' +
      'Its caterpillars can strip the leaves off oak and other hardwood trees in spring. ' +
      'Michigan counties and cities run suppression programs — often aerial Btk spraying — ' +
      'to knock back outbreaks.',
    'Btk':
      'Bacillus thuringiensis kurstaki — a naturally-occurring soil bacterium sprayed as a ' +
      'biological insecticide. It kills caterpillars (like spongy moth) that eat treated ' +
      'leaves but is considered low-risk to people, pets, birds, fish, and most other ' +
      'insects, so it is the usual choice for spongy-moth suppression.',
    'adulticide':
      'A pesticide that kills adult (flying) mosquitoes, as opposed to a larvicide that ' +
      'kills larvae in water. Mosquito-control programs often apply adulticides as an ' +
      'ultra-low-volume (ULV) fog of fine droplets, sometimes from aircraft.',
    'arbovirus':
      'A virus spread by biting insects — "ARthropod-BOrne virus." For Michigan mosquitoes ' +
      'the ones of concern are West Nile virus and Eastern Equine Encephalitis (EEE). In ' +
      'high-risk years the state may run aerial mosquito spraying in response.',
    'abatement district':
      'A local government body funded (usually by a county millage) to control a nuisance — ' +
      'here, a mosquito-abatement district that surveys mosquito populations and treats ' +
      'larvae and adult mosquitoes across the county.',
    'aquatic-life benchmark':
      'A threshold for ECOLOGICAL harm — the concentration above which a chemical may hurt ' +
      'fish, insects, and other aquatic organisms. Published by USGS/EPA and often MUCH ' +
      'lower than the human drinking-water limit (MCL). Exceeding an aquatic-life benchmark ' +
      'does NOT mean drinking water is unsafe, but it signals potential harm to aquatic life.',
    'HRS score':
      'Hazard Ranking System score (0–100). EPA scores contaminated sites on the risk ' +
      'they pose; a site scoring 28.5 or higher can be added to the Superfund list.',
    'NPL':
      'National Priorities List — the EPA\'s list of the most seriously contaminated ' +
      'sites in the country, eligible for long-term "Superfund" cleanup.',
    'Superfund':
      'The federal program (and its list, the NPL) for cleaning up the country\'s most ' +
      'hazardous contaminated sites.',
    'PFAS':
      '"Forever chemicals" — a family of man-made chemicals used in non-stick and ' +
      'stain-resistant products that build up in water, soil, and the body and break ' +
      'down extremely slowly.',
    'TRI':
      'Toxics Release Inventory — an EPA program under which larger industrial and ' +
      'federal facilities must report, every year, how many pounds of certain toxic ' +
      'chemicals they release to the air, water, and land. It shows what facilities are ' +
      'actively putting into the environment now, as self-reported.',
    'EPCRA':
      'The Emergency Planning and Community Right-to-Know Act — the 1986 federal law that ' +
      'created the Toxics Release Inventory and gives the public the right to know what ' +
      'toxic chemicals facilities in their community release.',
    'release pathway':
      'The route by which a chemical leaves a facility into the environment: to the AIR, ' +
      'to WATER (surface-water discharge), to LAND (on-site landfill/disposal), or by ' +
      'UNDERGROUND injection. TRI reports pounds for each pathway separately.',
    'fugitive vs stack air':
      'Two kinds of air release. STACK (or "point") emissions leave through a smokestack ' +
      'or vent; FUGITIVE emissions escape everywhere else — leaks, valves, open doors, ' +
      'evaporation. TRI adds both together as total air releases.',
    'NAICS code':
      'North American Industry Classification System code — a standardized number that ' +
      'says what kind of business a facility is (e.g. 325 = chemical manufacturing). It ' +
      'lets releases be grouped by industry.',
    'self-reported data':
      'Numbers a facility calculates and submits itself, rather than an outside measurement. ' +
      'They are required by law and audited, but can under- or over-count, and only cover ' +
      'facilities big enough to be required to report.',
    'choropleth':
      'A map where each area is shaded by a value — here, darker/brighter counties ' +
      'have more of whatever the legend describes.',
    'HUC-8 watershed':
      'A "subbasin" — a region where all the streams and rain drain to the same place. ' +
      'HUC-8 is a mid-sized watershed unit defined by the USGS.',
    'PBB':
      'Polybrominated biphenyl — a flame retardant accidentally mixed into Michigan ' +
      'livestock feed in 1973, contaminating much of the state\'s food supply.',
    'dioxin':
      'A group of highly toxic industrial by-products that persist in the environment ' +
      'and accumulate up the food chain.',
    'Type II landfill':
      'A municipal solid waste (MSW) landfill — the kind that takes everyday household ' +
      'and commercial trash. Under federal law (40 CFR Part 258) it must have liners, ' +
      'leachate collection, and groundwater monitoring throughout its life and for ' +
      'decades after it closes.',
    'Type III landfill':
      'A landfill for specific, lower-hazard waste streams rather than household ' +
      'trash — industrial process waste, construction-and-demolition debris, or coal ' +
      'ash. Regulated by Michigan under Part 115 with monitoring scaled to the waste.',
    'leachate':
      'The liquid that forms when rain and moisture percolate down through buried ' +
      'waste, picking up dissolved contaminants along the way. Landfills are required ' +
      'to collect and treat it so it does not reach groundwater.',
    'post-closure care':
      'The long period (typically 30 years) AFTER a landfill stops accepting waste ' +
      'during which the operator must maintain the cap, run the gas and leachate ' +
      'systems, and keep monitoring groundwater.',
    'RCRA':
      'The Resource Conservation and Recovery Act — the 1976 federal law that governs ' +
      'how solid and especially HAZARDOUS waste is handled from creation to disposal. ' +
      'Its "Subtitle C" sets the strict rules for hazardous-waste facilities.',
    'TSDF':
      'A Treatment, Storage, and Disposal Facility — a site permitted under RCRA to ' +
      'treat, store, or bury HAZARDOUS waste. A hazardous-waste landfill such as Wayne ' +
      'Disposal is the "disposal" kind.',
    'landfill gas':
      'The mix of methane and carbon dioxide produced as organic waste rots without ' +
      'oxygen inside a landfill. Methane is flammable and a potent greenhouse gas, so ' +
      'larger landfills must collect it — sometimes burning it for energy.',
    'FOIA':
      'The Freedom of Information Act — the law letting the public request government ' +
      'records. Landfill monitoring results that agencies hold but do not publish ' +
      'online can usually be obtained this way (in Michigan, from EGLE).',
    'correlation coefficient':
      'A number from −1 to +1 measuring how tightly two things move together. ' +
      '+1 = perfectly rise together, −1 = one rises as the other falls, 0 = no link.',
    'R-squared':
      'How much of the difference in the health metric between counties is "explained" ' +
      'by the pesticide/pollution measure. 0.08 means about 8% — the other 92% is due ' +
      'to other factors.',
    'p-value':
      'The chance you\'d see a pattern this strong just by luck if there were really no ' +
      'relationship. Below 0.05 is the usual cutoff for "probably not just chance."',
    'statistical significance':
      'Whether a pattern is strong enough to be unlikely to be pure chance ' +
      '(usually p < 0.05). Significant does NOT mean large or important — just "probably real."',
    'confound':
      'A hidden third factor that affects both things you\'re comparing and can create ' +
      'a misleading link — e.g. counties that farm more may also be older or poorer, ' +
      'which independently affect health.',
    'urban vs rural':
      'Urban and rural counties differ in countless ways unrelated to farming — air ' +
      'quality, age, income, smoking, industry. Comparing only rural counties removes ' +
      'some of that noise.',
    'age-adjusted rate':
      'A rate rebalanced to a standard age mix so counties with different age profiles ' +
      'can be compared fairly.',

    // ---- Fixes for previously-undefined gloss references ----
    // (All sourced from EPA pages — see the audit commit message.)
    'SDWA':
      'The Safe Drinking Water Act — the federal law that protects the public\'s ' +
      'drinking water. It lets the EPA set safety standards for the water that public ' +
      'systems deliver to the tap.',
    'CEMS':
      'Continuous Emissions Monitoring System — equipment on a smokestack that keeps ' +
      'sampling the exhaust and makes a permanent, measured record of how much pollution ' +
      '(such as sulfur dioxide, nitrogen oxides, and carbon dioxide) is going out.',
    'MATS':
      'Mercury and Air Toxics Standards — limits the EPA issued in 2011 on the mercury ' +
      'and other hazardous pollutants that coal- and oil-burning power plants may release ' +
      'into the air.',
    'CSAPR':
      'Cross-State Air Pollution Rule — EPA rules requiring power plants in eastern states ' +
      'to cut the pollution (sulfur dioxide and nitrogen oxides) that drifts across state ' +
      'lines and worsens the air downwind.',
    'Acid Rain Program':
      'A federal program that began in 1995 and requires power plants to cut the pollution ' +
      '(sulfur dioxide and nitrogen oxides) that is the main cause of acid rain.',
    'Clean Air Markets':
      'EPA\'s programs that cut air pollution from power plants — addressing acid rain, ' +
      'soot and smog, and pollution that blows across state lines — and publish the plants\' ' +
      'measured emissions.',
    'FracFocus':
      'The national public registry where oil-and-gas operators disclose the chemicals used ' +
      'in hydraulic fracturing at individual wells. It is run by the Ground Water Protection ' +
      'Council and the Interstate Oil and Gas Compact Commission (not by EPA).',
    'biogenic':
      'Emissions that come from living things rather than human activity — mainly trees, ' +
      'plants, and soil microbes. In EPA\'s air-toxics model these natural sources give off ' +
      'chemicals such as formaldehyde and acetaldehyde.',

    // ---- EPA ECHO: enforcement & compliance vocabulary ----
    // Programs the ECHO popup names (acronym keys; the visible label is the full name).
    'CAA':
      'The Clean Air Act — the federal law that regulates pollution released into the air ' +
      'from sources like factories, power plants, and vehicles, and lets the EPA set limits ' +
      'to protect public health.',
    'CWA':
      'The Clean Water Act — the federal law that controls what may be discharged into the ' +
      'nation\'s lakes, rivers, and streams and sets quality standards for surface waters.',
    'NPDES':
      'A federal permit program that controls water pollution by setting limits on what a ' +
      'facility may release from a pipe or other single outlet into lakes, rivers, and ' +
      'streams, along with rules for monitoring and reporting those releases.',
    'FRS':
      'EPA\'s Facility Registry Service — a central database that identifies facilities and ' +
      'places subject to environmental rules and gives each one a single EPA ID (a Registry ' +
      'ID) so its records across EPA programs can be linked together.',
    'DMR':
      'Discharge Monitoring Report — the form a facility fills out to report the results of ' +
      'the water-pollution monitoring its permit requires: how much of each pollutant it ' +
      'released, and whether that went over the permit\'s limits.',
    // Flags and tiers.
    'SNC':
      'Significant Noncompliance — EPA\'s label for the most serious water-pollution or ' +
      'hazardous-waste violations: big enough, or lasting long enough, to be an enforcement ' +
      'priority.',
    'Significant Noncompliance':
      'EPA\'s label for the most serious water-pollution or hazardous-waste violations — big ' +
      'enough, or lasting long enough, to be an enforcement priority. Abbreviated SNC.',
    'HPV':
      'High Priority Violator — EPA\'s label for a Clean Air Act violation serious enough to ' +
      'be an enforcement priority. A source stays a high priority violator until it is back ' +
      'in full compliance and any penalties are paid.',
    'High Priority Violator':
      'EPA\'s label for a Clean Air Act violation serious enough to be an enforcement ' +
      'priority. A source keeps this label until it is back in full compliance and any ' +
      'penalties are paid. Abbreviated HPV.',
    // Overall and per-program compliance-status values (shown verbatim from ECHO).
    'Significant Violation':
      'The most serious compliance tier in EPA\'s records — a high priority violation (air), ' +
      'significant noncompliance (water or hazardous waste), or enforcement priority ' +
      '(drinking water), depending on the program.',
    'Violation Identified':
      'EPA or a state has recorded that the facility is in violation of an environmental ' +
      'regulation.',
    'Violation':
      'A recorded violation below the most serious ("significant") tier — one that isn\'t a ' +
      'priority on its own but can become one if it is repeated.',
    'No Violation Identified':
      'No violation is recorded for this facility in EPA\'s national systems of record for ' +
      'the period shown.',
    'Significant Noncomplier':
      'EPA\'s label for the most serious hazardous-waste violators — for example, a site ' +
      'that has caused or is likely to cause exposure to hazardous waste, or that has strayed ' +
      'far from what its permit or the rules require.',
    'Enforcement Priority':
      'For a public water system: unresolved serious, repeated, or continuing violations that ' +
      'must be fixed or formally acted on within six months.',
    'Unknown':
      'No compliance determination is available in EPA\'s records for this facility.',
    'Inactive':
      'The facility is no longer active — for example, it has closed, gone out of business, ' +
      'or merged into another system.',
    'Terminated Permit':
      'The facility\'s discharge permit has been ended and is no longer in effect, so there ' +
      'is no current permit to comply with.',
    'Not Applicable':
      'A compliance status isn\'t tracked here because the permit is pending, not needed, or ' +
      'terminated, or the activity isn\'t permitted.',
    // Clean Water Act violation TYPES — reporting vs. actual discharge.
    'Failure to Report DMR - Not Received':
      'A reporting failure: a required water-monitoring report (a DMR) was not submitted. ' +
      'This is a paperwork problem — on its own it does NOT mean anything was discharged.',
    'Compliance/Permit Schedule - Reporting':
      'A reporting failure: a report that the permit\'s compliance timetable requires was not ' +
      'submitted on time. A paperwork problem, not a discharge.',
    'Effluent - Monthly Average Limit':
      'A discharge violation: the facility\'s released wastewater exceeded a permit limit ' +
      'measured as a monthly average.',
    'Effluent - Non-monthly Average Limit':
      'A discharge violation: the released wastewater exceeded a permit limit measured over ' +
      'a period other than a month (such as a daily or weekly limit).',
    'Compliance/Permit Schedule - Violations':
      'The facility missed a required step or deadline on the cleanup/compliance timetable ' +
      'built into its permit.',
    // Enforcement process terms.
    'formal action':
      'A formal enforcement action — an official legal step the government takes over a ' +
      'violation, such as an order to fix it or an assessed penalty (as opposed to an ' +
      'informal warning). The penalty figures shown come from these formal actions.',
    'quarters in noncompliance':
      'How many of the last 12 three-month periods (quarters) the facility had a recorded ' +
      'violation or was in noncompliance. 12 of 12 means every quarter for the last three years.',
    'alleged violations':
      'These are violations as determined by EPA or a state while inspecting a facility or ' +
      'reviewing the facility\'s own reports. They help track a case through the enforcement ' +
      'process and are not a final court or administrative ruling — so they are considered ' +
      'alleged.',

    // ===================== Part 2 — remaining layers =====================
    // Every definition below is drawn from the agency that owns the term
    // (EPA, EGLE/Michigan, USGS, USDA, IARC, OSHA, NIH/PubChem); sources are in
    // the commit message.

    // ---- Contamination / Superfund (EPA) ----
    'CERCLA':
      'The 1980 federal law — nicknamed Superfund — that lets the government clean up ' +
      'abandoned or uncontrolled hazardous-waste sites and spills, and make those ' +
      'responsible pay for it.',
    'Record of Decision':
      'The document that explains which cleanup approach was chosen for a contaminated ' +
      'site, and why.',
    'remedial investigation':
      'The study that maps how far contamination has spread at a site and what threat it ' +
      'poses to people and the environment, before a cleanup is picked.',
    'Five-Year Review':
      'A recheck done every five years at a cleaned-up site where contamination was left ' +
      'in place, to confirm the cleanup is still protecting people and the environment.',
    'monitored natural recovery':
      'Letting natural processes bury or break down contamination over time while the site ' +
      'is watched to confirm it is actually getting better.',
    'institutional controls':
      'Legal or administrative limits on how a property can be used — such as banning well ' +
      'water or digging — to keep people away from contamination left in the ground.',
    'consent decree':
      'A cleanup-or-penalty agreement between the government and a responsible party that a ' +
      'federal judge approves and can enforce.',
    'operations-and-maintenance phase':
      'The long-term stage after a cleanup is built, when the remedy is operated, maintained, ' +
      'and monitored to make sure it keeps working.',
    'TCE':
      'Trichloroethylene — a manufactured solvent used mainly to strip grease off metal ' +
      'parts. It can contaminate groundwater and is linked to cancer and other harm; the ' +
      'drinking-water limit is 5 parts per billion.',

    // ---- Landfills (EPA federal rules + Michigan EGLE) ----
    'Part 115':
      'Michigan\'s state solid-waste law that governs landfills — how they are licensed, ' +
      'operated, and monitored.',
    'Part 111':
      'Michigan\'s state hazardous-waste law governing how hazardous waste is handled, ' +
      'treated, stored, and disposed of.',
    'RCRA Subtitle C':
      'The part of the federal waste law that sets the strict rules for hazardous waste, ' +
      'from the moment it is produced through its disposal.',
    '40 CFR Part 258':
      'The federal rulebook of minimum safety standards for everyday-trash (municipal ' +
      'solid waste) landfills — liners, leak collection, and groundwater monitoring.',
    '40 CFR Part 257':
      'The federal rulebook of minimum safety standards for certain non-household-waste ' +
      'disposal, including coal-ash landfills and ponds.',

    // ---- Water-quality units ----
    'µg/L':
      'Micrograms per liter — a concentration in water. One microgram per liter is about ' +
      'one part per billion (a pinch of salt in a swimming pool).',
    'ng/L':
      'Nanograms per liter — a concentration a thousand times smaller than a microgram per ' +
      'liter; in water it is about one part per trillion.',
    'ppb':
      'Parts per billion — one part in a billion. In water it is about one microgram per liter.',

    // ---- Air monitors (EPA) ----
    'NAAQS':
      'National Ambient Air Quality Standards — the outdoor-air limits the EPA sets for a ' +
      'handful of common pollutants to protect health and the environment.',
    'AQS':
      'Air Quality System — the EPA\'s national database of actual air-pollution readings ' +
      'collected by monitors run by federal, state, local, and tribal agencies.',
    'CAMD':
      'The EPA\'s Clean Air Markets Division — the EPA group that runs programs cutting ' +
      'power-plant pollution and collects plants\' measured emissions.',
    'criteria pollutant':
      'One of six common air pollutants the EPA sets nationwide health limits for: ozone, ' +
      'particle pollution, carbon monoxide, sulfur dioxide, nitrogen dioxide, and lead.',
    'exceedance count':
      'How many times a monitor\'s readings went above the national outdoor-air limit ' +
      'during the year.',
    'PM2.5':
      'Fine particle pollution — airborne specks small enough (2.5 micrometers or less) to ' +
      'breathe deep into the lungs; linked to heart and lung harm and early death.',
    'SO2':
      'Sulfur dioxide — a gas given off mainly by burning fossil fuels at power plants and ' +
      'industry; it irritates the airways.',
    'O3':
      'Ground-level ozone — the main part of smog. It forms when pollution reacts in ' +
      'sunlight and it inflames the lungs, worsening asthma.',
    'NO2':
      'Nitrogen dioxide — a gas from burning fuel in vehicles, power plants, and gas ' +
      'stoves; it irritates the airways.',
    'Pb':
      'Lead — a toxic metal; even low exposure can harm children\'s brain development. The ' +
      'EPA limits it in outdoor air.',
    'CO':
      'Carbon monoxide — a colorless gas from burning fuel; at high levels it cuts the ' +
      'oxygen the blood can carry, a particular risk for people with heart disease.',

    // ---- Power plants ----
    'ORIS':
      'A unique power-plant ID number (the ORIS code) used to match a plant between the ' +
      'EPA\'s and the U.S. Energy Information Administration\'s datasets.',
    'EIA-860':
      'The U.S. Energy Information Administration\'s yearly survey that inventories the ' +
      'country\'s electric power plants and their generators (1 megawatt and larger).',
    '40 CFR Part 75':
      'The federal rule requiring power plants to continuously measure and report their ' +
      'smokestack sulfur dioxide, nitrogen oxides, and carbon dioxide.',
    'NOx':
      'Nitrogen oxides — gases formed when fuel burns at high temperature; they help form ' +
      'smog and soot.',
    'CO2':
      'Carbon dioxide — the main heat-trapping greenhouse gas released when fuel is burned.',

    // ---- Air toxics ----
    'HI':
      'Hazard index — a measure of non-cancer health risk: the modeled amount of a pollutant ' +
      'divided by the level the EPA considers safe, added up across pollutants that affect ' +
      'the same organ. At or below 1 is the EPA\'s threshold for "negligible."',
    'HAPs':
      'Hazardous air pollutants — the air pollutants known or suspected to cause cancer or ' +
      'other serious health effects (also called air toxics), regulated separately from ' +
      'common pollutants like soot and smog.',

    // ---- Oil & gas / FracFocus ----
    'UIC':
      'Underground Injection Control — the EPA program that regulates wells used to inject ' +
      'fluids underground, to keep them from contaminating underground drinking water.',
    'TENORM':
      'Natural radioactive material from rock and soil that human activity — such as ' +
      'oil-and-gas production or mining — has concentrated or brought to the surface, ' +
      'raising the chance of exposure.',
    'HVHF':
      'High-volume hydraulic fracturing — in Michigan, a well "frack" job that uses more ' +
      'than 100,000 gallons of primary carrier fluid.',
    'Class II wells':
      'Wells that inject fluids from oil-and-gas production — mostly salty brine — deep ' +
      'underground, far below drinking-water sources.',
    'CAS':
      'CAS Registry Number — a unique ID number given to each chemical, so a substance can ' +
      'be identified exactly even when it goes by many common names.',

    // ---- Areas of Concern (EPA / IJC) ----
    'AOC':
      'Area of Concern — a Great Lakes place the U.S. and Canada have flagged where past ' +
      'pollution seriously harmed the water and the ways people and wildlife can use it.',
    'BUI':
      'Beneficial Use Impairment — a specific way a polluted Great Lakes area can no longer ' +
      'be used or enjoyed normally (for example, fish unsafe to eat, or beaches closed).',
    'beneficial use impairment':
      'A specific way a polluted Great Lakes area can no longer be used or enjoyed normally ' +
      '(for example, fish unsafe to eat, or beaches closed). Abbreviated BUI.',
    'delisted':
      'Taken off the Great Lakes Areas of Concern list — which happens only after every ' +
      'beneficial use impairment at the site has been restored. It does not mean the area ' +
      'is pristine.',
    'Degradation of Benthos':
      'A beneficial use impairment: the community of bottom-dwelling creatures (insects, ' +
      'worms, clams) is thrown off compared with clean reference sites — a sign of polluted ' +
      'sediment.',
    'Eutrophication or Undesirable Algae':
      'A beneficial use impairment: too many nutrients drive algae blooms, low oxygen, and ' +
      'murky water.',
    'Degradation of Phytoplankton and Zooplankton Populations':
      'A beneficial use impairment: the tiny drifting plants and animals at the base of the ' +
      'food web are thrown off compared with clean reference sites.',

    // ---- PFAS ----
    'Part 201 cleanup criteria':
      'Michigan\'s state limits for how much of a contaminant may remain in soil or ' +
      'groundwater before a site counts as cleaned up.',
    'PFAS Hazard Index':
      'A way the EPA judges a mix of PFAS in drinking water: it adds up how close each of ' +
      'several PFAS is to its own safe level; a total above 1 exceeds the federal limit. ' +
      '(This is a drinking-water measure, different from the air-toxics hazard index.)',

    // ---- Golf / Spraying ----
    'ULV':
      'Ultra-low-volume — a spraying method that puts out a very fine mist of tiny droplets, ' +
      'using only a small amount of pesticide over a large area, to kill flying mosquitoes ' +
      'on contact.',
    'NREPA Part 83':
      'Michigan\'s state pesticide law that regulates how pesticides are sold and applied, ' +
      'and who is allowed to apply them.',

    // ---- Chemical reference / cross-layer ----
    'PubChem CID':
      'PubChem Compound ID — the ID number a chemical is given in PubChem, the free public ' +
      'chemical database run by the U.S. National Institutes of Health.',
    'IARC Group 1':
      'The World Health Organization\'s cancer-research agency classifies a substance as ' +
      'Group 1 when there is convincing evidence it causes cancer in people.',
    'IARC Group 2A':
      'The World Health Organization\'s cancer agency uses Group 2A for a substance that is ' +
      'probably able to cause cancer in people — strong evidence, but not yet conclusive ' +
      'in humans.',
    'IARC Group 2B':
      'The World Health Organization\'s cancer agency uses Group 2B for a substance that is ' +
      'possibly able to cause cancer in people — some evidence, but limited.',
    'OSHA-designated carcinogen':
      'A substance that the U.S. workplace-safety agency (OSHA), or the cancer bodies it ' +
      'relies on, lists as causing or likely causing cancer.',

    // ---- Crop map ----
    'CDL':
      'Cropland Data Layer — a yearly nationwide map, built from satellite images, that ' +
      'labels which crop was most likely growing on each patch of land.',
    'NASS':
      'The U.S. Department of Agriculture\'s National Agricultural Statistics Service — the ' +
      'agency that surveys farms and publishes crop and farming data.',
    'NAWQA':
      'The U.S. Geological Survey\'s National Water-Quality Assessment — a long-running ' +
      'program that samples the nation\'s streams, rivers, and groundwater to track water ' +
      'quality.',
  };

  function gloss(term) { return GLOSSARY[term] || term; }

  // ---------- statistics -> plain language ----------

  // R-squared strength on the fixed public scale.
  function r2Info(r2) {
    if (r2 == null) return { label: 'no data', pct: null, negligible: true };
    const pct = Math.round(r2 * 100);
    let label;
    if (r2 < 0.1) label = 'very weak';
    else if (r2 < 0.3) label = 'weak';
    else if (r2 < 0.5) label = 'moderate';
    else label = 'strong';
    return { label, pct, negligible: r2 < 0.1 };
  }

  // Strength word derived from the correlation coefficient r (via r²).
  function strengthWord(r) {
    if (r == null) return 'no';
    return r2Info(r * r).label;
  }

  function pInfo(p) {
    if (p == null) return { sig: null, text: 'There isn’t enough data to judge significance.' };
    if (p < 0.05) return {
      sig: true,
      text: 'This relationship is statistically significant — unlikely (under 5% chance) to be pure luck.',
    };
    return {
      sig: false,
      text: 'This relationship is NOT statistically significant — it could easily be chance.',
    };
  }

  function directionWord(r) {
    if (r == null) return 'flat';
    if (r > 0.03) return 'upward';
    if (r < -0.03) return 'downward';
    return 'flat';
  }

  // Full interpretation bundle for a scatter fit.
  //   fit  = {r, r2, p_value, n}
  //   yNoun = short label for the health metric, e.g. "cancer rates"
  function interpret(fit, yNoun) {
    yNoun = yNoun || 'the health metric';
    const r = fit && fit.r, r2 = fit && fit.r2, p = fit && fit.p_value, n = fit && fit.n;
    if (r == null || !n || n < 3) {
      return {
        ok: false, strength: 'no data',
        r2Sentence: 'There isn’t enough county data here to measure a relationship.',
        pSentence: '', significant: null, direction: 'flat',
      };
    }
    const info = r2Info(r2);
    const dir = directionWord(r);
    const pinf = pInfo(p);
    let r2Sentence;
    if (info.negligible) {
      // Below ~10% explained, the direction isn't meaningful — don't imply one.
      r2Sentence =
        `Very weak or no relationship — this measure explains only about ` +
        `${info.pct}% of the difference in ${yNoun} between counties, which is ` +
        `essentially no usable pattern. The other ${100 - info.pct}% is due to other factors.`;
    } else {
      const strengthTitle = info.label.charAt(0).toUpperCase() + info.label.slice(1);
      const dirClause = dir === 'upward'
        ? 'higher values line up with higher ' + yNoun
        : 'higher values line up with LOWER ' + yNoun;
      r2Sentence =
        `${strengthTitle} relationship — this measure explains about ` +
        `${info.pct}% of the difference in ${yNoun} between counties, and ${dirClause}. ` +
        `The other ${100 - info.pct}% is due to other factors.`;
    }
    return {
      ok: true,
      strength: info.label,
      negligible: info.negligible,
      r2pct: info.pct,
      direction: dir,
      significant: pinf.sig,
      r2Sentence,
      pSentence: pinf.text,
    };
  }

  // One-sentence summary for the unified explorer.
  //   xLabel "atrazine", yLabel "bladder cancer", cohort "rural"|"all"
  function summarySentence(fit, xLabel, yLabel, cohort) {
    const info = interpret(fit, yLabel + ' rates');
    const where = cohort === 'rural'
      ? 'In rural Michigan counties, ' : 'Across Michigan counties, ';
    if (!info.ok) {
      return where + `there isn’t enough data to compare ${xLabel} with ${yLabel}.`;
    }
    const dir = info.direction === 'downward' ? 'lower' : 'higher';
    const assoc = (info.negligible || info.direction === 'flat')
      ? `shows little or no association with ${yLabel} rates`
      : `shows a ${info.strength} association with ${dir} ${yLabel} rates`;
    const sig = info.significant == null ? ''
      : info.significant
        ? ' This relationship is statistically significant.'
        : ' This relationship is not statistically significant.';
    return `${where}higher ${xLabel} ${assoc}.${sig}`;
  }

  // HTML for a small "?" info icon carrying a glossary definition.
  function infoIcon(term) {
    return `<span class="info-i" data-gloss="${term}" tabindex="0" role="img" ` +
           `aria-label="definition of ${term}">?</span>`;
  }

  window.PMGloss = {
    GLOSSARY, gloss, r2Info, strengthWord, pInfo, directionWord,
    interpret, summarySentence, infoIcon,
  };
})();
