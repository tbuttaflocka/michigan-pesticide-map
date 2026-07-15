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
    'MCL':
      'Maximum Contaminant Level — the legal limit for a chemical in public drinking ' +
      'water, set by the EPA. A result above the MCL exceeds the safety threshold.',
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
