// Plain-language glossary + statistics interpreters, shared across the app so
// definitions and "what does this number mean" translations are consistent
// everywhere. Exposed as window.PMGloss. Loaded before app.js.
(function () {
  // ---------- glossary: technical term -> plain-language definition ----------
  const GLOSSARY = {
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
    'bioaccumulation':
      'The buildup of a chemical in living tissue faster than the body can get rid of it, so ' +
      'concentrations rise up the food chain. PFOS bioaccumulates strongly in fish, which is why ' +
      'fish caught in contaminated waters can carry far higher PFAS levels than the water itself.',
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
