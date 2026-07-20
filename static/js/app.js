// Main app — Michigan Pesticide Heat Map.
(function () {
  const $ = (id) => document.getElementById(id);
  const fmtLbs = window.PMCharts.fmtLbs;
  // Phone / portrait-tablet layout (matches the CSS mobile breakpoint).
  const isMobile = () => window.matchMedia('(max-width: 768px)').matches;

  // ---------- state ----------
  const state = {
    meta: null,
    geojson: null,
    year: null,
    years: [],
    category: 'all',
    compound: '',
    estimate: 'avg',
    normalize: 'total',
    choropleth: null,
    geoLayer: null,
    map: null,
    // Which layer colors the county fills. Exactly one at a time (radio group):
    activeChoropleth: 'pesticide',
    countyByFips: new Map(),
    breaks: [],
    pestStats: null,
    palette: [],
    playInterval: null,
    charts: {},
    explore: { vars: null, wired: false, chart: null },
    trend: { sw: null, cty: null },
    water: {
      sitesLayer: null, heatLayer: null, wsLayer: null,
      showSites: false, showHeat: false, showWatersheds: false,
      compound: '',          // current dropdown selection (override)
      matchMain: false,      // mirror main-map compound filter
      compounds: [],         // dropdown options
    },
    resp: {
      enabled: false,              // checkbox state
      metric: 'combined',          // dropdown selection
      meta: null,                  // {label, units, county_level, icd10, ...}
      byFips: new Map(),
      breaks: [],
      countyLevel: false,
      hoverLabel: '',
      scatterPest: 'total',
      scatterResp: 'asthma_ed',
      excludeWayne: false,
      rankings: [],
      sortKey: 'rank_pest',
      sortDir: 'asc',
    },
    cancer: {
      enabled: false,              // map-overlay checkbox
      type: 'nhl',                 // selected cancer type (choropleth + card default)
      dataType: 'incidence',       // 'incidence' | 'mortality'
      byFips: new Map(),
      breaks: [],
      countyLevel: false,
      meta: null,
      hoverLabel: '',
      // correlation tab
      scatterCancer: 'nhl',
      scatterPest: 'all',
      scatterDtype: 'incidence',
      excludeUrban: false,
      ruralOnly: false,
      controlSmoking: false,
      types: [],                   // meta.cancer_types
    },
    contam: {
      loaded: false,
      sites: [],                   // all sites from /api/contamination/sites
      showSites: false,
      showZones: false,
      showDensity: false,
      filters: { npl: true, pfas: true, state: true, deleted: false },
      markers: null,               // L.featureGroup
      zones: null,                 // L.layerGroup
      density: null,               // L.geoJSON
      densityByFips: new Map(),
    },
    tri: {
      loaded: false,
      facilities: [],              // /api/tri/sites facilities
      showSites: false,
      markers: null,               // L.markerClusterGroup / layerGroup
      latestYear: null,
      maxTotal: 1,
      metric: 'total',             // choropleth pathway sub-option
      densityByFips: new Map(),    // per-metric county values (cache keyed by metric)
      _densityMetric: null,        // which metric densityByFips currently holds
      _densityMax: 1,
      trendSw: null,
      trendCty: null,
    },
    wind: {
      showRoses: false,
      showDrift: false,
      driftZoneOnClick: false,
      roseLayer: null,             // L.layerGroup of wind-rose divIcons
      driftLayer: null,            // L.layerGroup of drift arrows
      zoneLayer: null,             // L.layerGroup for the clicked-county fan
      stations: null,              // cached /api/wind/stations payload
    },
  };

  // ---------- color palette (dark-friendly) ----------
  // green -> amber -> red, matching theme accents
  const PALETTE = ['#0d2818', '#194d2c', '#2d7339', '#5b9f3b', '#a3c93b',
                   '#e8c440', '#e89a3c', '#d96b35', '#bf3b2c', '#8b1f1f'];
  state.palette = PALETTE;

  // ---------- helpers ----------
  function show(el)   { el.classList.remove('hidden'); }
  function hide(el)   { el.classList.add('hidden'); }

  async function api(path, params) {
    const url = new URL(path, window.location.origin);
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        if (v !== null && v !== undefined && v !== '') url.searchParams.set(k, v);
      }
    }
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${r.status} ${r.statusText} for ${url}`);
    return r.json();
  }

  function loading(on) {
    on ? show($('loading')) : hide($('loading'));
  }

  // Compute jenks-ish quantile breaks from a sorted positive array.
  function computeBreaks(values, n) {
    const v = values.filter((x) => x > 0).sort((a, b) => a - b);
    if (v.length === 0) return [];
    const breaks = [];
    for (let i = 1; i < n; i++) {
      const q = v[Math.floor((i / n) * v.length)];
      breaks.push(q);
    }
    return breaks;
  }

  function bucketIndex(v, breaks) {
    if (v <= 0 || v == null) return -1;
    for (let i = 0; i < breaks.length; i++) {
      if (v <= breaks[i]) return i;
    }
    return breaks.length;
  }

  function colorFor(v, breaks, palette) {
    const i = bucketIndex(v, breaks);
    if (i < 0) return '#26303f';   // no data / zero
    return palette[Math.min(i, palette.length - 1)];
  }

  // ---------- map setup ----------
  function initMap() {
    state.map = L.map('map', {
      zoomControl: true,
      attributionControl: true,
      minZoom: 5,
      maxZoom: 11,
    }).setView([44.7, -85.2], 6);

    L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
      {
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
          '&copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 19,
      },
    ).addTo(state.map);

    // Clicking empty map (not a county polygon) returns to the statewide view.
    // County-polygon clicks stamp state._skipMapClick so the accompanying map
    // 'click' event doesn't undo the selection that click just made.
    state.map.on('click', () => {
      if (state._skipMapClick && Date.now() - state._skipMapClick < 150) return;
      if (state.selectedFips) closeCountyPanel();
    });

    // Watershed polygons sit just above the county choropleth (overlayPane
    // z400) so their fill is visible and they receive hover/click, but below
    // the marker panes so point overlays stay clickable on top.
    state.map.createPane('watersheds');
    state.map.getPane('watersheds').style.zIndex = 410;

    // Dedicated pane for water-monitoring markers, above the choropleth
    // (overlayPane z400) and default markerPane (z600) so county polygons can
    // never intercept clicks meant for the site markers.
    state.map.createPane('water');
    state.map.getPane('water').style.zIndex = 620;

    // Floating "Currently showing: <layer>" badge over the map.
    const badge = L.control({ position: 'topright' });
    badge.onAdd = () => {
      const d = L.DomUtil.create('div', 'active-layer-badge');
      d.id = 'active-layer-badge';
      return d;
    };
    badge.addTo(state.map);
  }

  // Fill color for a county under whichever choropleth is currently active.
  // Only one choropleth ever paints the base layer, so scales never blend.
  const NO_DATA = '#26303f';
  function fillColorForActive(fips) {
    switch (state.activeChoropleth) {
      case 'resp': {
        const c = state.resp.byFips.get(fips);
        if (!c || c.value == null) return NO_DATA;
        return state.resp.countyLevel
          ? (respColor(c.value, state.resp.breaks) || NO_DATA)
          : RESP_PALETTE[5];
      }
      case 'cancer': {
        const c = state.cancer.byFips.get(fips);
        if (!c || c.value == null) return NO_DATA;
        return state.cancer.countyLevel
          ? (cancerColor(c.value, state.cancer.breaks) || NO_DATA)
          : CANCER_PALETTE[5];
      }
      case 'contam_density': {
        const c = state.contam.densityByFips.get(fips);
        const v = c ? c.value : 0;
        if (!v) return NO_DATA;
        const max = state.contam._densityMax || 1;
        const idx = Math.min(CONTAM_PALETTE.length - 1,
          Math.floor(Math.sqrt(v / max) * CONTAM_PALETTE.length));
        return CONTAM_PALETTE[idx];
      }
      case 'tri': {
        const c = state.tri.densityByFips.get(fips);
        const v = c ? c.value : 0;
        if (!v) return NO_DATA;
        const max = state.tri._densityMax || 1;
        const idx = Math.min(TRI_PALETTE.length - 1,
          Math.floor(Math.sqrt(v / max) * TRI_PALETTE.length));
        return TRI_PALETTE[idx];
      }
      default: {   // pesticide
        const c = state.countyByFips.get(fips);
        return colorFor(c ? c.value : 0, state.breaks, state.palette);
      }
    }
  }

  function styleFor(feature) {
    // "None" = no choropleth: transparent fills so the base map + point overlays
    // read cleanly, with only a faint neutral county outline.
    if (state.activeChoropleth === 'none') {
      return { fillColor: NO_DATA, fillOpacity: 0, color: '#2a3344', weight: 0.5 };
    }
    return {
      fillColor: fillColorForActive(feature.id),
      fillOpacity: 0.82,
      color: '#0d1117',
      weight: 0.7,
    };
  }

  function highlightStyle() {
    // Under "None", highlight the outline only — don't paint a fill that would
    // cover the point overlays the user is trying to see.
    if (state.activeChoropleth === 'none') {
      return { weight: 2.0, color: '#f0b429', fillOpacity: 0 };
    }
    return { weight: 2.2, color: '#f0b429', fillOpacity: 0.92 };
  }

  // ---------- persistent selected-county outline ----------
  // Distinct from the hover highlight: a brighter, thicker gold border that
  // stays until another county is clicked (or the same one clicked again).
  const SELECTED_STYLE = { color: '#ffd23f', weight: 4, opacity: 1, dashArray: null };

  function layerForFips(fips) {
    let found = null;
    if (state.geoLayer) {
      state.geoLayer.eachLayer((l) => {
        if (l.feature && l.feature.id === fips) found = l;
      });
    }
    return found;
  }

  // Reset to the base choropleth style, then draw the bold selection border on
  // top and raise it so the outline is always visible above the fill.
  function applySelectedBorder(layer) {
    if (!layer || !state.geoLayer) return;
    state.geoLayer.resetStyle(layer);
    layer.setStyle(SELECTED_STYLE);
    layer.bringToFront();
  }

  // Re-apply the selection after any full restyle (setStyle wipes it).
  function restyleSelection() {
    if (state.selectedFips) applySelectedBorder(layerForFips(state.selectedFips));
  }

  function selectCounty(fips) {
    const prev = state.selectedFips;
    if (prev && prev !== fips) {
      const pl = layerForFips(prev);
      if (pl) state.geoLayer.resetStyle(pl);
    }
    state.selectedFips = fips;
    applySelectedBorder(layerForFips(fips));
  }

  function clearSelectedCounty() {
    const prev = state.selectedFips;
    state.selectedFips = null;
    if (prev) {
      const pl = layerForFips(prev);
      if (pl) state.geoLayer.resetStyle(pl);
    }
  }

  // Make the county panel the primary sidebar view (replacing the statewide
  // panel) and bring it clearly into view, so clicking a county immediately
  // shows that county — no scrolling to find it.
  function showCountyPanel() {
    hide($('statewide-panel'));
    show($('county-panel'));
    const p = $('county-panel');
    if (isMobile()) {
      // Phone: the county detail slides up as a bottom sheet over the map.
      document.body.classList.remove('m-layers-open');
      document.body.classList.add('m-detail-open');
      p.scrollTop = 0;
    } else if (window.innerWidth <= 900) {
      // Small stacked window: the right sidebar is below the map — scroll to it.
      try { p.scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch (e) {}
    } else {
      const sb = p.closest('.sidebar');
      if (sb) sb.scrollTop = 0;   // county panel is now first in the sidebar
    }
    // Brief header flash so it's obvious where attention should go.
    p.classList.remove('flash');
    void p.offsetWidth;           // reflow to restart the animation
    p.classList.add('flash');
  }

  // Return to the statewide overview and clear the county selection.
  function closeCountyPanel() {
    hide($('county-panel'));
    show($('statewide-panel'));
    document.body.classList.remove('m-detail-open');   // close the mobile sheet
    clearSelectedCounty();
    clearDriftZone();
  }

  // Clicking the map polygon toggles selection; search/list clicks call
  // openCounty directly (which also selects).
  function onCountyClick(fips) {
    // Mark the moment so the map-background 'click' that also fires for this
    // same tap doesn't immediately deselect the county (see initMap).
    state._skipMapClick = Date.now();
    if (state.selectedFips === fips) {
      closeCountyPanel();          // clicking the selected county again → back to statewide
    } else {
      openCounty(fips);
    }
  }

  function renderChoropleth() {
    if (!state.geojson) return;
    if (state.geoLayer) state.geoLayer.remove();
    state.geoLayer = L.geoJSON(state.geojson, {
      style: styleFor,
      onEachFeature: (feature, layer) => {
        layer.on('mouseover', (e) => {
          // Don't hover-highlight the selected county — keep its bold outline.
          if (feature.id !== state.selectedFips) {
            e.target.setStyle(highlightStyle());
            e.target.bringToFront();
          }
          showTooltip(feature, e.originalEvent);
        });
        layer.on('mousemove', (e) => showTooltip(feature, e.originalEvent));
        layer.on('mouseout', (e) => {
          if (feature.id === state.selectedFips) applySelectedBorder(e.target);
          else state.geoLayer.resetStyle(e.target);
          hide($('tooltip'));
        });
        layer.on('click', () => onCountyClick(feature.id));
      },
    }).addTo(state.map);
    state.map.fitBounds(state.geoLayer.getBounds(), { padding: [10, 10] });
    restyleSelection();
  }

  // Tooltip shows only the metric for the active choropleth, so the county
  // name is always followed by exactly one relevant value.
  function tooltipBody(fips) {
    switch (state.activeChoropleth) {
      case 'none':
        return '';   // county name only — coloring is off
      case 'resp': {
        const c = state.resp.byFips.get(fips);
        const base = (state.resp.meta && !state.resp.countyLevel) ? ' · MI baseline' : '';
        return (c && c.value != null)
          ? `<div><span class="muted">${state.resp.hoverLabel}:</span> <span class="r-v">${c.value.toFixed(1)}</span>${base}</div>`
          : '<div class="muted">No data</div>';
      }
      case 'cancer': {
        const c = state.cancer.byFips.get(fips);
        const base = (state.cancer.meta && state.cancer.meta.is_baseline) ? ' · MI baseline' : '';
        if (c && c.value != null) {
          return `<div><span class="muted">${state.cancer.hoverLabel}:</span> <span class="v">${c.value.toFixed(1)}</span>${base}</div>`;
        }
        return `<div class="muted">${c && c.suppressed ? 'Suppressed (&lt;16 cases)' : 'No data'}</div>`;
      }
      case 'contam_density': {
        const c = state.contam.densityByFips.get(fips);
        return (c && c.value)
          ? `<div><span class="muted">Contamination sites:</span> <span class="v">${c.value}</span></div>`
          : '<div class="muted">No mapped sites</div>';
      }
      case 'tri': {
        const c = state.tri.densityByFips.get(fips);
        if (!c || !c.value) return '<div class="muted">No TRI releases reported</div>';
        return `<div><span class="muted">${triMetricLabel(state.tri.metric)}:</span> <span class="v">${fmtLbs(c.value)}</span></div>
             <div><span class="muted">Facilities:</span> <span class="v">${c.facilities || 0}</span></div>`;
      }
      default: {   // pesticide
        const c = state.countyByFips.get(fips);
        const valLabel = state.normalize === 'per_sq_mile' ? 'lbs / mi²'
          : state.normalize === 'per_acre' ? 'lbs / cropland acre' : 'Value';
        if (!c) return '<div class="muted">No pesticide data</div>';
        const acreLine = (state.normalize === 'per_acre' && c.cropland_acres)
          ? `<div><span class="muted">Cropland:</span> <span class="v">${Math.round(c.cropland_acres).toLocaleString()} ac</span></div>` : '';
        return `<div><span class="muted">${valLabel}:</span> <span class="v">${fmtLbs(c.value)}</span></div>
             <div><span class="muted">Total:</span> <span class="v">${fmtLbs(c.total_lbs)}</span></div>
             ${acreLine}
             <div><span class="muted">Compounds:</span> <span class="v">${c.compound_count}</span></div>`;
      }
    }
  }

  function showTooltip(feature, evt) {
    const tt = $('tooltip');
    tt.innerHTML = `<strong>${feature.properties.name} County</strong>${tooltipBody(feature.id)}`;
    tt.style.left = (evt.pageX + 14) + 'px';
    tt.style.top  = (evt.pageY + 12) + 'px';
    show(tt);
  }

  // ---------- legend ----------
  // Labels shown in the "Currently showing" indicator + legend heading.
  function activeChoroplethLabel() {
    switch (state.activeChoropleth) {
      case 'none':   return 'None (no county coloring)';
      case 'resp':   return `Respiratory — ${respMetricLabel(state.resp.metric)}`;
      case 'cancer': return `Cancer — ${cancerTypeLabel(state.cancer.type)} (${state.cancer.dataType})`;
      case 'contam_density': return 'Contamination site density';
      case 'tri':    return `TRI toxic releases — ${triMetricLabel(state.tri.metric).toLowerCase()}`;
      default:       return `Pesticide — ${pestFilterLabel()}`;
    }
  }

  // Plain-language label for the current TRI choropleth pathway sub-option.
  function triMetricLabel(m) {
    return ({
      total: 'Total releases', air: 'Air releases', water: 'Water releases',
      land: 'Land releases', pfas: 'PFAS releases',
    })[m] || 'Total releases';
  }

  function pestFilterLabel() {
    if (state.compound) return state.compound;
    const cat = { all: 'all compounds', herbicide: 'herbicides', insecticide: 'insecticides',
      fungicide: 'fungicides', growth_regulator: 'growth regulators', other: 'other / fumigants' };
    return cat[state.category] || 'all compounds';
  }
  function respMetricLabel(k) {
    const sel = $('resp-metric');
    const o = sel && sel.querySelector(`option[value="${k}"]`);
    return o ? o.textContent : k;
  }
  function cancerTypeLabel(k) {
    const t = (state.cancer.types || []).find((x) => x.key === k);
    return t ? t.label : k;
  }

  // A simple low→high swatch strip (used by layers whose units aren't lbs).
  function paletteStrip(el, palette) {
    for (let i = 0; i < palette.length; i++) {
      const div = document.createElement('div');
      div.className = 'bucket plain';
      div.style.background = palette[i];
      el.appendChild(div);
    }
  }

  function renderLegend() {
    const el = $('legend');
    const note = $('legend-units');
    el.innerHTML = '';
    switch (state.activeChoropleth) {
      case 'none':
        note.textContent = 'County coloring off — showing point overlays only';
        break;
      case 'pesticide': {
        const max = state.pestStats ? state.pestStats.max : 0;
        if (!state.breaks.length) {
          el.innerHTML = '<div class="muted small">No data for this year/filter</div>';
        } else {
          const edges = [0, ...state.breaks, max];
          for (let i = 0; i < state.palette.length; i++) {
            const lo = edges[i], hi = edges[i + 1];
            const div = document.createElement('div');
            div.className = 'bucket';
            div.style.background = state.palette[i];
            div.textContent = fmtLbs(hi).replace(' lbs', '');
            div.title = `${fmtLbs(lo)} – ${fmtLbs(hi)}`;
            el.appendChild(div);
          }
        }
        note.textContent = state.normalize === 'per_sq_mile'
          ? 'lbs per square mile (lower → higher)'
          : state.normalize === 'per_acre'
          ? 'lbs per cropland acre — urban counties blank (lower → higher)'
          : 'lbs applied (lower → higher)';
        break;
      }
      case 'resp':
        paletteStrip(el, RESP_PALETTE);
        note.textContent = state.resp.meta
          ? `${state.resp.hoverLabel} · ${state.resp.meta.units} (lower → higher)`
          : 'respiratory rate (lower → higher)';
        break;
      case 'cancer':
        paletteStrip(el, CANCER_PALETTE);
        note.textContent = state.cancer.meta
          ? `${state.cancer.meta.label} · ${state.cancer.meta.units} (lower → higher)`
          : 'cancer rate (lower → higher)';
        break;
      case 'contam_density':
        paletteStrip(el, CONTAM_PALETTE);
        note.textContent = 'contamination sites per county (lower → higher)';
        break;
      case 'tri':
        paletteStrip(el, TRI_PALETTE);
        note.textContent = `${triMetricLabel(state.tri.metric).toLowerCase()} · lbs/yr` +
          (state.tri.latestYear ? ` (${state.tri.latestYear})` : '') + ' (lower → higher)';
        break;
    }
    renderMarkerKeys();
  }

  // Small key entries for whatever point/marker overlays are stacked on top.
  const MARKER_KEYS = [
    { on: () => state.water.showSites,       c: '#f0b429', t: 'Water monitoring sites' },
    { on: () => state.water.showHeat,        c: '#f85149', t: 'Water detection heatmap' },
    { on: () => state.water.showWatersheds,  c: '#8db0ff', t: 'HUC-8 watersheds' },
    { on: () => state.contam.showSites,      c: '#f85149', t: 'Contamination sites' },
    { on: () => state.contam.showZones,      c: '#e8873c', t: 'Contamination impact zones' },
    { on: () => state.tri.showSites,         c: '#d9772f', t: 'TRI facilities (size/red = more released)' },
    { on: () => state.wind.showRoses,        c: '#3fb950', t: 'Wind roses (Apr–Sep)' },
    { on: () => state.wind.showDrift,        c: '#e8873c', t: 'Drift arrows (downwind)' },
  ];
  function renderMarkerKeys() {
    let mk = $('legend-markers');
    if (!mk) {
      mk = document.createElement('div');
      mk.id = 'legend-markers';
      mk.className = 'legend-markers';
      $('legend-units').after(mk);
    }
    const active = MARKER_KEYS.filter((k) => k.on());
    let html = active.length
      ? '<div class="mk-title">Overlays on top</div>' + active.map((k) =>
          `<div class="mk"><span class="mk-dot" style="background:${k.c}"></span>${k.t}</div>`).join('')
      : '';
    // Watershed color-scale legend (the layer is a choropleth by detections).
    if (state.water.showWatersheds) {
      html += '<div class="mk-title" style="margin-top:8px">Watersheds · pesticide detections</div>' +
        '<div class="ws-legend">' +
        '<span class="ws-sw" style="background:rgba(110,118,129,0.35)"></span>none' +
        '<span class="ws-sw" style="background:rgba(56,142,201,0.45)"></span>low' +
        '<span class="ws-sw" style="background:rgba(56,142,201,0.8)"></span>high' +
        '<span class="ws-sw" style="background:rgba(248,81,73,0.72)"></span>MCL exc.' +
        '</div>';
    }
    mk.innerHTML = html;
  }

  // "Currently showing" indicator — in the layer panel and floating over the map.
  function updateActiveIndicator() {
    const label = activeChoroplethLabel();
    const panel = $('active-layer-name');
    if (panel) panel.textContent = label;
    const badge = $('active-layer-badge');
    if (badge) badge.innerHTML = `<span class="alb-k">Currently showing</span> ${label}`;
    // On mobile the "Layers & filters" button doubles as the current-layer
    // indicator, so keep its label in sync.
    const fabLabel = $('m-fab-label');
    if (fabLabel) fabLabel.textContent = label;
  }

  // ---------- active choropleth switching (mutually exclusive) ----------
  async function setActiveChoropleth(which) {
    if (!which) return;
    state.activeChoropleth = which;
    // Keep the legacy per-layer flags in sync (county cards + meta text use them).
    state.resp.enabled       = (which === 'resp');
    state.cancer.enabled     = (which === 'cancer');
    state.contam.showDensity = (which === 'contam_density');

    // Show the TRI pathway sub-options only while the TRI choropleth is active.
    const triSub = $('tri-suboptions');
    if (triSub) triSub.classList.toggle('hidden', which !== 'tri');

    loading(true);
    try {
      if (which === 'resp')  await loadRespData();  else updateRespMeta(null);
      if (which === 'cancer') await loadCancerData(); else updateCancerMeta(null);
      if (which === 'contam_density') await loadContamDensity();
      if (which === 'tri') await loadTriDensity(state.tri.metric);
    } catch (e) {
      console.error(e);
    } finally {
      loading(false);
    }

    if (state.geoLayer) state.geoLayer.setStyle(styleFor);
    restyleSelection();   // setStyle wiped the selection border — re-apply it
    renderLegend();
    updateActiveIndicator();

    // Reflect state in the radio group (covers programmatic calls).
    const radio = document.querySelector(`input[name="choropleth"][value="${which}"]`);
    if (radio) radio.checked = true;
  }

  // ---------- choropleth refresh ----------
  async function refreshChoropleth() {
    loading(true);
    try {
      const data = await api('/api/choropleth', {
        year: state.year, category: state.category, compound: state.compound,
        estimate: state.estimate, normalize: state.normalize,
      });
      state.countyByFips.clear();
      const values = [];
      for (const c of data.counties) {
        state.countyByFips.set(c.fips, c);
        if (c.value > 0) values.push(c.value);
      }
      state.breaks = computeBreaks(values, state.palette.length);
      state.pestStats = data.stats;
      if (state.geoLayer) state.geoLayer.setStyle(styleFor);
      restyleSelection();
      renderLegend();
      updateActiveIndicator();
    } catch (e) {
      console.error(e);
    } finally {
      loading(false);
    }
  }

  // ---------- Water-quality overlay ----------
  const WQ_COLOR = {
    exceeds_mcl:     '#f85149',
    detected:        '#f0b429',
    tested_no_detect:'#3fb950',
    no_data:         '#6e7681',
  };

  function activeWaterCompound() {
    if (state.water.matchMain && state.compound) return state.compound.toUpperCase();
    return state.water.compound || '';
  }

  // Michigan has thousands of WQP sites, many stacked on the same river reach.
  // Cluster them so dense areas collapse into a count badge and expand into
  // individually-clickable markers as you zoom in / click the cluster.
  function newWaterSiteLayer() {
    if (typeof L.markerClusterGroup === 'function') {
      return L.markerClusterGroup({
        clusterPane: 'water',
        maxClusterRadius: 50,
        chunkedLoading: true,
        showCoverageOnHover: false,
        // Keep clustering active at every zoom so co-located sites collapse into
        // a cluster that *spiderfies* (fans out) on click — otherwise stacked
        // markers on the same river reach would still hide each other and only
        // the top one would be clickable.
        spiderfyOnMaxZoom: true,
        removeOutsideVisibleBounds: true,
      });
    }
    return L.layerGroup();   // graceful fallback if the plugin failed to load
  }

  async function refreshWaterSites() {
    if (state.water.sitesLayer) state.water.sitesLayer.remove();
    state.water.sitesLayer = null;
    if (!state.water.showSites) return;
    const compound = activeWaterCompound();
    const data = await api('/api/water/sites', compound ? { compound } : {});
    const grp = newWaterSiteLayer();
    let detected = 0, exceeds = 0, tested = 0;
    for (const s of data.sites) {
      if (s.latitude == null || s.longitude == null) continue;
      if (compound && s.detections === 0) continue;   // filter-mode hides non-detect sites
      const m = L.circleMarker([s.latitude, s.longitude], {
        pane: 'water',                 // render above the choropleth so clicks land
        radius: s.exceedances > 0 ? 8 : (s.detections > 0 ? 6 : 4),
        color: '#0d1117', weight: 0.8,
        fillColor: WQ_COLOR[s.severity] || WQ_COLOR.no_data,
        fillOpacity: 0.92,
      });
      // Bind a popup once (with a placeholder) and fill it with the fetched
      // detail each time it opens. Leaflet then owns open/close/reopen, so the
      // same marker reopens reliably instead of only working on the first click.
      m.bindPopup('<div class="wq-popup muted">Loading…</div>', { maxWidth: 340 });
      m.on('popupopen', () => openWaterPopup(m, s));
      grp.addLayer(m);
      if (s.severity === 'exceeds_mcl') exceeds++;
      else if (s.severity === 'detected') detected++;
      else if (s.severity === 'tested_no_detect') tested++;
    }
    grp.addTo(state.map);
    state.water.sitesLayer = grp;
    const lbl = compound ? `${compound} only` : 'all pesticides';
    $('wq-stats').textContent =
      `${exceeds} exceed MCL · ${detected} detected · ${tested} clean (${lbl})`;
  }

  async function openWaterPopup(layer, site) {
    // Reuse already-fetched detail on reopen (no refetch, no "Loading…" flash).
    if (layer._wqBody) { layer.setPopupContent(layer._wqBody); return; }
    const detail = await api(`/api/water/site/${encodeURIComponent(site.site_id)}`);
    const rows = (detail.compound_summary || []).slice(0, 8);
    const body =
      `<div class="wq-popup">
        <h4>${site.site_name || site.site_id}</h4>
        <div class="wq-meta">
          ${site.site_type || 'site'} · ${site.huc8 ? 'HUC-8 ' + site.huc8 + ' · ' : ''}
          ${site.latitude.toFixed(3)}, ${site.longitude.toFixed(3)}
        </div>
        <table>
          <tr><th></th>
            <th class="right" data-tip="How many water samples were tested for this chemical.">Samples</th>
            <th class="right" data-tip="How many of those samples actually contained the chemical (above the detection limit).">Detections</th>
            <th class="right" data-tip="How many samples exceeded the EPA legal drinking-water limit (MCL).">Exc.</th></tr>
          ${rows.map((r) => `
            <tr class="${r.exceedances ? 'exceeds' : (r.detections ? 'detected' : '')}">
              <td>${r.compound}${r.mcl ? ` <span class="wq-meta" data-gloss="MCL">(MCL ${r.mcl} µg/L)</span>` : ''}</td>
              <td class="right">${r.samples}</td>
              <td class="right">${r.detections}</td>
              <td class="right">${r.exceedances}</td>
            </tr>`).join('')}
        </table>
        <div class="wq-meta" style="margin-top:6px">
          ${site.organization || ''} · source ${site.source}
        </div>
      </div>`;
    layer._wqBody = body;
    // The popup is already open (bound with a placeholder); just fill it in.
    layer.setPopupContent(body);
  }

  async function refreshWaterHeat() {
    if (state.water.heatLayer) state.water.heatLayer.remove();
    state.water.heatLayer = null;
    if (!state.water.showHeat) return;
    const compound = activeWaterCompound();
    const d = await api('/api/water/heatmap', compound ? { compound } : {});
    if (!d.points.length || typeof L.heatLayer !== 'function') return;
    state.water.heatLayer = L.heatLayer(d.points, {
      radius: 22, blur: 15, minOpacity: 0.35,
      gradient: { 0.2: '#3f5cad', 0.4: '#7791e1', 0.6: '#bfb4f0',
                  0.8: '#f0b429', 1.0: '#f85149' },
    }).addTo(state.map);
  }

  // Fill a watershed by pesticide detections in its water samples (red tint
  // when there are MCL exceedances); grey when nothing was detected.
  function watershedFill(d, e, maxDet) {
    const intensity = maxDet > 0 ? Math.sqrt(d / maxDet) : 0;
    if (e > 0) return `rgba(248,81,73,${(0.35 + 0.5 * intensity).toFixed(2)})`;
    if (d > 0) return `rgba(56,142,201,${(0.28 + 0.5 * intensity).toFixed(2)})`;
    return 'rgba(110,118,129,0.10)';
  }

  function watershedPopupHtml(p) {
    const row = (k, v) => `<div class="row"><span class="k">${k}</span> ${v}</div>`;
    const exc = p.exceedances || 0;
    return `<div class="ws-popup">
      <h4>${p.name || 'Watershed'}</h4>
      <div class="ws-meta">HUC-8 ${p.huc8}</div>
      ${row('Pesticide detections (water):', `<b>${p.detections || 0}</b>` +
        (exc ? ` · <span class="exc">${exc} MCL exceedance${exc > 1 ? 's' : ''}</span>` : ''))}
      ${row('Monitoring sites:', `${p.total_sites || 0} (${p.sites_with_detections || 0} with detections)`)}
      ${row('Contamination sites:', `${p.contam_sites || 0}${p.contam_npl ? ` (${p.contam_npl} Superfund NPL)` : ''}`)}
      ${row('Pesticide applied (approx):', fmtLbs(p.pesticide_lbs || 0))}
      <div class="ws-note">Detections/exceedances are exact; pesticide use is
        approximated from the counties overlapping this watershed.</div>
    </div>`;
  }

  // A SINGLE persistent watershed layer. Toggling just adds/removes it; it is
  // (re)built only when first shown or when the compound filter changes. This
  // avoids the old ghost-layer bug where two overlapping async builds each
  // added an L.geoJSON and only the newest reference could be removed.
  async function refreshWaterWatersheds() {
    // Toggle OFF — synchronous remove, no async gap that could race a toggle-on.
    if (!state.water.showWatersheds) {
      if (state.water.wsLayer && state.map.hasLayer(state.water.wsLayer)) {
        state.map.removeLayer(state.water.wsLayer);
      }
      renderMarkerKeys();
      return;
    }
    const compound = activeWaterCompound();
    // Reuse the already-built layer when the compound is unchanged — instant.
    if (state.water.wsLayer && state.water._wsCompound === compound) {
      if (!state.map.hasLayer(state.water.wsLayer)) state.water.wsLayer.addTo(state.map);
      renderMarkerKeys();
      return;
    }
    // Build for this compound. A monotonically increasing id lets a newer build
    // cancel an older in-flight one, so overlapping builds never each add a layer.
    const buildId = (state.water._wsBuildId = (state.water._wsBuildId || 0) + 1);
    try {
      state.water._wsCache = state.water._wsCache || {};
      const key = compound || '__all__';
      let fc = state.water._wsCache[key];
      if (!fc) {
        fc = await api('/api/water/watersheds', compound ? { compound } : {});
        state.water._wsCache[key] = fc;          // cache so toggles never refetch
      }
      if (buildId !== state.water._wsBuildId) return;   // superseded by a newer build
      // Replace any existing layer with the single new reference.
      if (state.water.wsLayer) { state.map.removeLayer(state.water.wsLayer); state.water.wsLayer = null; }
      if (!fc.features || !fc.features.length) { renderMarkerKeys(); return; }
      let maxDet = 1;
      for (const f of fc.features) maxDet = Math.max(maxDet, f.properties.detections || 0);
      state.water._wsMaxDet = maxDet;
      const baseStyle = (f) => ({
        fillColor: watershedFill(f.properties.detections || 0, f.properties.exceedances || 0, maxDet),
        fillOpacity: 1.0, color: '#8db0ff', weight: 1, dashArray: '3 3',
      });
      // Explicit renderer bound to the watersheds pane so the SVG paths land
      // there (above the county fill, below markers) and remain clickable.
      if (!state.water._wsRenderer) state.water._wsRenderer = L.svg({ pane: 'watersheds' });
      const layer = L.geoJSON(fc, {
        pane: 'watersheds',
        renderer: state.water._wsRenderer,
        style: baseStyle,
        onEachFeature: (feat, lyr) => {
          const p = feat.properties;
          lyr.bindPopup(watershedPopupHtml(p), { maxWidth: 300, className: 'ws-popup-wrap' });
          lyr.on('mouseover', () => lyr.setStyle({ weight: 3, color: '#ffd23f', dashArray: null }));
          lyr.on('mouseout', () => { if (state.water.wsLayer === layer) layer.resetStyle(lyr); });
        },
      });
      state.water.wsLayer = layer;
      state.water._wsCompound = compound;
      // Only display it if still wanted (user may have toggled off during fetch).
      if (state.water.showWatersheds) layer.addTo(state.map);
    } catch (e) {
      console.error('watershed layer failed:', e && e.message, e);
    }
    renderMarkerKeys();
  }

  function refreshAllWaterLayers() {
    refreshWaterSites();
    refreshWaterHeat();
    refreshWaterWatersheds();
  }

  async function loadWaterCompounds() {
    const d = await api('/api/water/compounds');
    state.water.compounds = d.compounds;
    const sel = $('wq-compound');
    sel.innerHTML = '<option value="">— all pesticides —</option>';
    for (const c of d.compounds.slice(0, 60)) {
      const o = document.createElement('option');
      o.value = c.compound;
      o.textContent = `${c.compound} (${c.detections} det${c.exceedances ? ', ' + c.exceedances + ' exc.' : ''})`;
      sel.appendChild(o);
    }
  }

  // ---------- Respiratory choropleth overlay ----------
  // Blue-purple palette (distinct from green/red).
  const RESP_PALETTE = ['#202b4a', '#2e4382', '#3f5cad', '#5474c9', '#7791e1',
                        '#9da9f3', '#bfb4f0', '#d3a8e0', '#c97fb5', '#a85998'];

  function respColor(v, breaks) {
    if (v == null) return null;
    for (let i = 0; i < breaks.length; i++) if (v <= breaks[i]) return RESP_PALETTE[i];
    return RESP_PALETTE[RESP_PALETTE.length - 1];
  }

  // Load respiratory county data into state (the shared base layer paints it
  // when 'resp' is the active choropleth). No separate map overlay.
  async function loadRespData() {
    const data = await api('/api/respiratory/counties', { metric: state.resp.metric });
    state.resp.meta = data;
    state.resp.byFips.clear();
    const vals = [];
    for (const c of data.counties) {
      state.resp.byFips.set(c.fips, c);
      if (c.value != null) vals.push(c.value);
    }
    state.resp.hoverLabel = data.label;
    state.resp.countyLevel = data.county_level;
    state.resp.breaks = data.county_level ? computeBreaks(vals, RESP_PALETTE.length) : [];
    updateRespMeta(data);
  }

  function updateRespMeta(data) {
    const el = $('resp-meta');
    if (!state.resp.enabled || !data) { el.textContent = '—'; return; }
    const valid = data.counties.filter((c) => c.value != null).length;
    const note  = data.county_level
      ? `${valid}/${data.counties.length} counties · ${data.units}`
      : `MI statewide baseline (no county variation) · ${data.units}`;
    const icd = data.icd10 ? ` · ${data.icd10}` : '';
    el.textContent = note + icd;
  }

  // ---------- Cancer choropleth overlay ----------
  // Orange-red heat palette (distinct from green=pesticide, blue-purple=resp,
  // magenta=contamination). Low → high = pale orange → deep red.
  const CANCER_PALETTE = ['#fee0b6', '#fdc98a', '#fcae6b', '#fb9350', '#f5793b',
                          '#e85d2f', '#d6431f', '#b82e12', '#94210c', '#6b1508'];

  function cancerColor(v, breaks) {
    if (v == null) return null;
    for (let i = 0; i < breaks.length; i++) if (v <= breaks[i]) return CANCER_PALETTE[i];
    return CANCER_PALETTE[CANCER_PALETTE.length - 1];
  }

  // Load cancer county data into state; the shared base layer paints it when
  // 'cancer' is the active choropleth.
  async function loadCancerData() {
    const data = await api('/api/cancer/counties', {
      type: state.cancer.type, data_type: state.cancer.dataType,
    });
    state.cancer.meta = data;
    state.cancer.byFips.clear();
    const vals = [];
    for (const c of data.counties) {
      state.cancer.byFips.set(c.fips, c);
      if (c.value != null) vals.push(c.value);
    }
    state.cancer.hoverLabel = `${data.label} (${data.data_type})`;
    state.cancer.countyLevel = data.county_level;
    state.cancer.breaks = data.county_level ? computeBreaks(vals, CANCER_PALETTE.length) : [];
    updateCancerMeta(data);
  }

  function updateCancerMeta(data) {
    const el = $('cancer-meta');
    if (!state.cancer.enabled || !data) { el.textContent = '—'; return; }
    const valid = data.counties.filter((c) => c.value != null).length;
    const supp = data.counties.filter((c) => c.suppressed).length;
    const base = data.is_baseline ? ' · MI statewide baseline' : '';
    const mi = data.mi_rate != null ? ` · MI ${data.mi_rate}` : '';
    const suppTxt = supp ? ` · ${supp} suppressed` : '';
    el.textContent = `${valid}/${data.counties.length} counties · ${data.units}${mi}${suppTxt}${base}`;
  }

  // ---------- Cancer county card (in the county detail panel) ----------
  function trendIcon(t) {
    if (t === 'rising')  return '<span class="trend up">▲ rising</span>';
    if (t === 'falling') return '<span class="trend down">▼ falling</span>';
    if (t === 'stable')  return '<span class="trend flat">■ stable</span>';
    return '<span class="muted">—</span>';
  }

  function renderCountyCancerCard(cancer) {
    const tbody = document.querySelector('#county-cancer-table tbody');
    const note = $('county-cancer-note');
    const ru = $('county-cancer-ru');
    if (!tbody) return;
    tbody.innerHTML = '';
    if (!cancer || !cancer.metrics) {
      note.textContent = 'No cancer data.';
      return;
    }
    ru.textContent = cancer.rural_urban ? `· ${cancer.rural_urban}` : '';
    if (cancer.rural_urban) {
      ru.setAttribute('data-tip', 'Urban/rural classification. Rural agricultural counties are where pesticide exposure is more likely a factor vs urban counties where industrial pollution and lifestyle factors dominate.');
    } else {
      ru.removeAttribute('data-tip');
    }
    for (const m of cancer.metrics) {
      const tr = document.createElement('tr');
      if (m.is_top20) tr.classList.add('top20');
      const rate = m.suppressed || m.rate == null
        ? '<span class="muted" title="Suppressed (<16 cases)">suppressed</span>'
        : m.rate.toFixed(1);
      let cmp = '—', cmpClass = '';
      if (m.pct_vs_state != null) {
        const arrow = m.pct_vs_state > 0 ? '▲' : (m.pct_vs_state < 0 ? '▼' : '·');
        const sign = m.pct_vs_state > 0 ? '+' : '';
        cmp = `${arrow} ${sign}${m.pct_vs_state.toFixed(0)}%`;
        cmpClass = m.pct_vs_state > 0 ? 'high' : (m.pct_vs_state < 0 ? 'low' : '');
      }
      const us = m.us_rate != null ? m.us_rate.toFixed(1) : '—';
      tr.innerHTML =
        `<td>${m.label}${m.is_top20 ? ' <span class="top20-tag" data-tip="This county ranks in the top 20% statewide for this cancer type.">top 20%</span>' : ''}</td>` +
        `<td class="num val">${rate}</td>` +
        `<td class="num cmp ${cmpClass}">${cmp}</td>` +
        `<td class="num muted">${us}</td>` +
        `<td class="num trend-cell">${trendIcon(m.trend)}</td>`;
      tbody.appendChild(tr);
    }
    note.textContent = `Age-adjusted per 100,000, ${cancer.data_years}. ` +
      '▲/▼ = vs Michigan average. "vs US" is the national (SEER+NPCR) rate.';
  }

  // ---------- Cancer type dropdowns ----------
  function populateCancerDropdowns() {
    const types = state.meta.cancer_types || [];
    state.cancer.types = types;
    const def = state.meta.cancer_default || 'nhl';
    state.cancer.type = def;
    state.cancer.scatterCancer = def;
    const fill = (sel) => {
      sel.innerHTML = '';
      for (const t of types) {
        const o = document.createElement('option');
        o.value = t.key; o.textContent = t.label;
        if (t.key === def) o.selected = true;
        sel.appendChild(o);
      }
    };
    fill($('cancer-type'));
    fill($('cancer-scatter-cancer'));
  }

  // ---------- composition trend chart (statewide + county) ----------
  const TREND_CAT_COLORS = {
    herbicide: '#3fb950', insecticide: '#f85149',
    fungicide: '#58a6ff', other: '#f0b429',
  };
  const TREND_COMPOUND_COLORS = [
    '#3fb950', '#f85149', '#58a6ff', '#f0b429', '#bc8cff',
    '#ff9e64', '#2ac3de', '#e0af68', '#9ece6a', '#f7768e',
  ];
  const TREND_OTHER_COLOR = '#6b7280';

  function hexA(hex, a) {
    const h = hex.replace('#', '');
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${a})`;
  }

  // A self-contained trend panel: fetches /api/trend for a scope (statewide or a
  // county fips) and renders it in one of four view modes, with a mode toggle,
  // clickable legend, and a breakdown tooltip. Reused for both trend charts.
  function createTrendPanel(opts) {
    const { canvasId, modesId, scopeId, chartKey } = opts;
    const endpoint = opts.endpoint || '/api/trend';
    const catColors = opts.catColors || TREND_CAT_COLORS;
    const totalLabel = opts.totalLabel || 'Total pesticide';
    const totalColor = opts.totalColor || '#3fb950';
    // Params for the fetch; pesticide passes estimate+category, TRI just fips.
    const paramsFor = opts.paramsFor || ((fips) => ({
      fips: fips || '', estimate: state.estimate, category: state.category,
    }));
    let mode = 'category';
    let data = null;

    function buildSpec() {
      if (mode === 'total') {
        return {
          stacked: false, pct: false,
          datasets: [{
            label: totalLabel, data: data.total,
            borderColor: totalColor, backgroundColor: hexA(totalColor, 0.15),
            fill: true, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.25,
          }],
        };
      }
      if (mode === 'compounds') {
        const ds = data.compounds.map((c, i) => {
          const color = c.name === 'All others'
            ? TREND_OTHER_COLOR
            : TREND_COMPOUND_COLORS[i % TREND_COMPOUND_COLORS.length];
          return {
            label: c.name, data: c.values, borderColor: color,
            backgroundColor: hexA(color, 0.5),
            fill: i === 0 ? 'origin' : '-1',
            borderWidth: 1, pointRadius: 0, tension: 0.2,
          };
        });
        return { stacked: true, pct: false, datasets: ds };
      }
      // category or percent (both built from the 4 category bands)
      const cats = data.categories;
      const pct = mode === 'percent';
      const ds = cats.map((c, i) => {
        const vals = pct
          ? c.values.map((v, yr) => {
              const denom = cats.reduce((s, cc) => s + cc.values[yr], 0);
              return denom ? (v / denom * 100) : 0;
            })
          : c.values;
        const color = catColors[c.key] || '#9aa4b2';
        return {
          label: c.label, data: vals, borderColor: color,
          backgroundColor: hexA(color, 0.5),
          fill: i === 0 ? 'origin' : '-1',
          borderWidth: 1.2, pointRadius: 0, tension: 0.2,
        };
      });
      return { stacked: true, pct, datasets: ds };
    }

    function render() {
      const ctx = document.getElementById(canvasId);
      if (!ctx || !data) return;
      const spec = buildSpec();
      const totals = data.total;
      PMCharts.destroyIfExists(state.charts[chartKey]);
      state.charts[chartKey] = new Chart(ctx, {
        type: 'line',
        data: { labels: data.years, datasets: spec.datasets },
        options: {
          responsive: true, maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: {
              display: mode !== 'total', position: 'bottom',
              labels: { boxWidth: 10, boxHeight: 10, padding: 6,
                        font: { size: 10 }, usePointStyle: true },
            },
            tooltip: {
              callbacks: {
                title: (items) => `${items[0].label}`,
                label: (item) => {
                  const v = item.parsed.y;
                  if (spec.pct) return `${item.dataset.label}: ${v.toFixed(1)}%`;
                  const yt = totals[item.dataIndex] || 0;
                  const p = yt ? (v / yt * 100) : 0;
                  return `${item.dataset.label}: ${PMCharts.fmtLbs(v)} (${p.toFixed(0)}%)`;
                },
                footer: (items) => spec.pct ? ''
                  : `Total: ${PMCharts.fmtLbs(totals[items[0].dataIndex])}`,
              },
            },
          },
          scales: {
            x: { grid: { color: 'rgba(154,164,178,.08)' },
                 ticks: { maxRotation: 0, autoSkip: true, font: { size: 10 } } },
            y: { stacked: spec.stacked, beginAtZero: true,
                 grid: { color: 'rgba(154,164,178,.08)' },
                 ...(spec.pct ? { min: 0, max: 100 } : {}),
                 ticks: { font: { size: 10 },
                   callback: (v) => spec.pct ? v + '%' : PMCharts.fmtLbs(v) } },
          },
        },
      });
    }

    // Wire the mode toggle once.
    const bar = $(modesId);
    if (bar && !bar._wired) {
      bar._wired = true;
      bar.querySelectorAll('button').forEach((b) => {
        b.addEventListener('click', () => {
          mode = b.dataset.mode;
          bar.querySelectorAll('button').forEach((x) => x.classList.toggle('active', x === b));
          render();
        });
      });
    }

    async function load(fips) {
      data = await api(endpoint, paramsFor(fips));
      if (scopeId) {
        $(scopeId).textContent = data.scope
          + (data.category_filter ? ` · ${data.category_filter}` : '');
      }
      render();
    }
    return { load };
  }

  // ---------- statewide panel ----------
  async function refreshStatewide() {
    const data = await api('/api/statewide', { year: state.year, estimate: state.estimate });
    $('state-heading').textContent = `Statewide summary · ${data.year}`;
    $('stat-total').textContent      = fmtLbs(data.total_lbs);
    $('stat-compounds').textContent  = data.distinct_compounds.toLocaleString();
    $('stat-counties').textContent   = data.top_counties.length ? '83' : '0';

    const topC = $('top-counties'); topC.innerHTML = '';
    for (const r of data.top_counties) {
      const li = document.createElement('li');
      li.classList.add('clickable');
      li.innerHTML = `<span>${r.name}</span><span class="v">${fmtLbs(r.lbs)}</span>`;
      li.addEventListener('click', () => openCounty(r.fips));
      topC.appendChild(li);
    }

    const topX = $('top-compounds'); topX.innerHTML = '';
    for (const r of data.top_compounds) {
      const li = document.createElement('li');
      li.classList.add('clickable');
      li.innerHTML =
        `<span>${r.compound} <span class="muted small">${r.category}</span></span>` +
        `<span class="v">${fmtLbs(r.lbs)}</span>`;
      li.addEventListener('click', () => {
        $('filter-compound').value = r.compound;
        state.compound = r.compound;
        markFeatured(r.compound);
        refreshAll();
      });
      topX.appendChild(li);
    }

    if (!state.trend.sw) {
      state.trend.sw = createTrendPanel({
        canvasId: 'chart-statewide-trend', modesId: 'trend-modes-sw',
        scopeId: 'trend-scope-sw', chartKey: 'statewideTrend',
      });
    }
    state.trend.sw.load(null);

    // Statewide industrial-releases (TRI) trend — only if the layer has data.
    if (triHasData()) {
      if (!state.tri.trendSw) {
        state.tri.trendSw = createTrendPanel({
          canvasId: 'chart-tri-trend-sw', modesId: 'tri-trend-modes-sw',
          scopeId: 'tri-trend-scope-sw', chartKey: 'triTrendSw',
          endpoint: '/api/tri/trend', catColors: TRI_PATH_COLORS,
          totalLabel: 'Total on-site releases', totalColor: '#d9772f',
          paramsFor: (fips) => ({ fips: fips || '' }),
        });
      }
      state.tri.trendSw.load(null);
    }

    PMCharts.destroyIfExists(state.charts.category);
    const catLabels = data.by_category.map((r) => r.category);
    const catVals   = data.by_category.map((r) => r.lbs || 0);
    const catCols   = catLabels.map((c) => PMCharts.CATEGORY_COLORS[c] || '#9aa4b2');
    state.charts.category = PMCharts.doughnut(
      'chart-category', catLabels, catVals, catCols,
    );
  }

  // ---------- county detail ----------
  // Full "show all N compounds" list under the top-10 chart (collapsed default).
  function renderCountyCompoundsList(compounds) {
    const list = $('county-compounds-all');
    const btn = $('county-compounds-toggle');
    if (!list || !btn) return;
    const n = compounds.length;
    list.innerHTML = compounds.map((r) => {
      const col = PMCharts.CATEGORY_COLORS[r.category] || '#9aa4b2';
      return `<div class="cl-row"><span class="cl-dot" style="background:${col}"></span>` +
        `<span class="cl-name">${r.compound}</span>` +
        `<span class="cl-val">${fmtLbs(r.lbs || 0)}</span></div>`;
    }).join('');
    list.classList.add('hidden');
    const setLabel = (open) => {
      btn.textContent = open ? 'Hide full compound list' : `Show all ${n} compounds ▾`;
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    };
    setLabel(false);
    // Chart already shows the top 10; only offer the toggle when there's more.
    btn.style.display = n > 10 ? '' : 'none';
    btn.onclick = () => {
      const nowHidden = list.classList.toggle('hidden');
      setLabel(!nowHidden);
    };
  }

  async function openCounty(fips) {
    showCountyPanel();     // county panel becomes the primary view, brought into view
    selectCounty(fips);    // persistent gold outline
    showDriftZone(fips);   // no-op unless the drift-zone toggle is on
    const data = await api(`/api/county/${fips}`, { year: state.year, estimate: state.estimate });
    $('county-name').textContent = `${data.name} County`;
    $('county-fips').textContent = `FIPS ${data.fips}`;
    $('county-area').textContent = data.area_sq_miles
      ? `${data.area_sq_miles.toFixed(0)} mi²` : '';
    $('county-total').textContent = fmtLbs(data.total_lbs);
    $('county-density').textContent = data.lbs_per_sq_mile != null
      ? fmtLbs(data.lbs_per_sq_mile) : '—';
    $('county-inspector').href = data.mdard_inspector_url;

    // Respiratory comparison table — one row per metric.
    const r = data.respiratory || {};
    const tbody = document.querySelector('#county-resp-table tbody');
    tbody.innerHTML = '';
    for (const m of (r.metrics || [])) {
      const tr = document.createElement('tr');
      if (m.is_baseline_only) tr.classList.add('baseline');
      const val = m.value == null ? '—' : `${m.value.toFixed(1)} ${m.units}`;
      const pct = m.pct_vs_state;
      let cmp = '';
      let cmpClass = '';
      if (pct == null) {
        cmp = m.is_baseline_only ? '<span class="baseline-tag">MI baseline</span>' : '—';
      } else {
        const arrow = pct > 0 ? '▲' : (pct < 0 ? '▼' : '·');
        const sign = pct > 0 ? '+' : '';
        cmp = `${arrow} ${sign}${pct.toFixed(0)}%`;
        cmpClass = pct > 0 ? 'high' : (pct < 0 ? 'low' : '');
      }
      tr.innerHTML =
        `<td>${m.label}</td>` +
        `<td class="num val">${val}</td>` +
        `<td class="num cmp ${cmpClass}">${cmp}</td>`;
      tbody.appendChild(tr);
    }
    const noteParts = [];
    noteParts.push(r.is_urban
      ? 'Urban county — air quality, density, smoking, industrial emissions dominate.'
      : 'Rural county.');
    if (r.asthma_prevalence_pct != null) {
      noteParts.push(`Adult asthma prevalence (MI BRFS baseline): ${r.asthma_prevalence_pct.toFixed(1)}%.`);
    }
    $('county-resp-note').textContent = noteParts.join(' ');

    // Cancer incidence card
    renderCountyCancerCard(data.cancer);
    // Industrial contamination list
    renderCountyContamination(data.contamination);
    // Industrial toxic releases (TRI) — fetched separately (own tables).
    renderCountyTri(fips);

    PMCharts.destroyIfExists(state.charts.countyCompounds);
    state.charts.countyCompounds = PMCharts.horizontalBar(
      'chart-county-compounds',
      data.top_compounds.slice(0, 10).map((r) => r.compound),
      data.top_compounds.slice(0, 10).map((r) => r.lbs || 0),
      data.top_compounds.slice(0, 10).map(
        (r) => PMCharts.CATEGORY_COLORS[r.category] || '#9aa4b2',
      ),
    );
    renderCountyCompoundsList(data.top_compounds);

    PMCharts.destroyIfExists(state.charts.countyCategory);
    state.charts.countyCategory = PMCharts.doughnut(
      'chart-county-category',
      data.by_category.map((r) => r.category),
      data.by_category.map((r) => r.lbs || 0),
      data.by_category.map((r) => PMCharts.CATEGORY_COLORS[r.category] || '#9aa4b2'),
    );

    if (!state.trend.cty) {
      state.trend.cty = createTrendPanel({
        canvasId: 'chart-county-trend', modesId: 'trend-modes-cty',
        scopeId: 'trend-scope-cty', chartKey: 'countyTrend',
      });
    }
    state.trend.cty.load(fips);

    const tbl = $('county-crops');
    if (data.crops.length === 0) {
      tbl.innerHTML = '<tr><td class="muted small">No NASS crop data loaded — set NASS_API_KEY to enable.</td></tr>';
    } else {
      tbl.innerHTML = data.crops.map((c) => `
        <tr>
          <td>${c.crop}</td>
          <td class="year">${c.year}</td>
          <td class="val">${c.acres_harvested ? c.acres_harvested.toLocaleString() : '—'} ac</td>
        </tr>
      `).join('');
    }
  }

  // ---------- Industrial contamination overlay ----------
  // Magenta density palette (distinct from green/blue-purple/orange-red/red).
  const CONTAM_PALETTE = ['#2a1830', '#43214a', '#5e2663', '#7c2b7a', '#9c2f8c',
                          '#bd3597', '#db3f9c', '#ef5fa8', '#f98bbd', '#fdb8d6'];
  const CONTAM_GLYPH = {
    chemical_manufacturing: '☣', pesticide_manufacturing: '☣', pfas_manufacturing: '\u{1F4A7}',
    steel_manufacturing: '\u{1F3ED}', auto_manufacturing: '\u{1F3ED}',
    industrial_manufacturing: '\u{1F3ED}', paper_manufacturing: '\u{1F3ED}',
    mining: '⛏', military: '★', waste_disposal: '☠', pfas: '\u{1F4A7}',
    landfill: '☠', other: '⚠',
  };

  function contamPane() {
    if (!state.map.getPane('contam')) {
      const p = state.map.createPane('contam');
      p.style.zIndex = 650;   // above overlay choropleths + default markers
    }
    return 'contam';
  }

  async function loadContamination() {
    if (state.contam.loaded) return;
    const d = await api('/api/contamination/sites');
    state.contam.sites = d.sites;
    state.contam.loaded = true;
  }

  function contamSiteVisible(s) {
    const f = state.contam.filters;
    const hasPfas = (s.contaminants || []).some((c) => /pfas/i.test(c));
    const st = s.status_class;
    return (f.npl && (st === 'npl' || st === 'proposed')) ||
           (f.pfas && hasPfas) ||
           (f.state && st === 'state') ||
           (f.deleted && st === 'deleted');
  }

  function contamSize(s) { return Math.round(20 + Math.min(18, (s.hrs_score || 0) / 4)); }

  function renderContamMarkers() {
    if (state.contam.markers) { state.contam.markers.remove(); state.contam.markers = null; }
    if (!state.contam.showSites) { updateContamStats(); return; }
    const pane = contamPane();
    const grp = L.featureGroup();
    for (const s of state.contam.sites) {
      if (!contamSiteVisible(s)) continue;
      const size = contamSize(s);
      const m = L.marker([s.lat, s.lng], {
        pane,
        icon: L.divIcon({
          className: 'contam-divicon',
          html: `<div class="contam-marker" style="width:${size}px;height:${size}px;background:${s.status_color}"><span>${s.glyph}</span></div>`,
          iconSize: [size, size], iconAnchor: [size / 2, size / 2],
        }),
      });
      // Bind the popup once so Leaflet handles open/close/reopen. (Binding on
      // every click installed a second toggle handler that cancelled the next
      // open, so a closed marker wouldn't reopen until you clicked elsewhere.)
      m.bindPopup(contamPopupHtml(s), { maxWidth: 360, className: 'contam-popup-wrap' });
      grp.addLayer(m);
    }
    grp.addTo(state.map);
    state.contam.markers = grp;
    updateContamStats();
  }

  function contamPopupHtml(s) {
    const chips = (s.contaminants || []).map((c) => `<span class="chip">${c}</span>`).join('');
    const row = (k, v) => v ? `<div class="row"><span class="k">${k}</span> ${v}</div>` : '';
    const water = (s.affected_waterways || []).length
      ? row('Affected water:', s.affected_waterways.join(', ')) : '';
    const acounties = (s.affected_counties || []).length
      ? row('Affected counties:', s.affected_counties.join(', ')) : '';
    const hrs = s.hrs_score != null
      ? row('HRS score:', `${s.hrs_score.toFixed(2)} / 100 ${PMGloss.infoIcon('HRS score')}`) : '';
    const generated = s.desc_source === 'generated';
    const fetched = s.narrative_source === 'fetched' && s.narrative;

    // Body: a fetched narrative (if any) leads; the structured EPA-field summary
    // follows as a separate section for generated sites.
    let body = '';
    if (fetched) {
      body += `<p class="cp-desc">${s.narrative}</p>`;
      if (generated && s.description) {
        body += `<p class="cp-record"><span class="k">Site record:</span> ${s.description}</p>`;
      }
    } else if (s.description) {
      body += `<p class="cp-desc">${s.description}</p>`;
    }

    // Source line / provenance.
    let provenance = '';
    if (fetched) {
      const refs = (s.narrative_refs || []).map((r) =>
        r.url ? `<a href="${r.url}" target="_blank" rel="noopener">${r.label}</a>` : r.label);
      const epa = s.epa_profile_url
        ? `<a href="${s.epa_profile_url}" target="_blank" rel="noopener">EPA profile →</a>` : '';
      const parts = refs.concat(epa ? [epa] : []);
      provenance = `<p class="cp-generated">Sources: ${parts.join(' · ')}</p>`;
    } else if (generated) {
      const link = s.epa_profile_url
        ? ` <a href="${s.epa_profile_url}" target="_blank" rel="noopener">See full profile →</a>` : '';
      provenance = `<p class="cp-generated">No detailed public narrative found — summary generated from the EPA site record.${link}</p>`;
    } else if (s.epa_profile_url) {
      provenance = `<a href="${s.epa_profile_url}" target="_blank" rel="noopener">EPA Superfund profile →</a>`;
    }

    return `<div class="contam-popup">
      <div class="cp-status" style="background:${s.status_color}">${s.status_label}</div>
      ${s.company ? `<div class="cp-company">${s.company}</div>` : ''}
      <h4>${s.site_name}</h4>
      <div class="cp-meta">${s.category_label}${s.city ? ' · ' + s.city : ''}${s.county ? ', ' + s.county + ' Co.' : ''}${s.epa_id ? ' · ' + s.epa_id : ''}</div>
      ${row('Operated:', s.years_active)}${hrs}
      ${chips ? `<div class="chips">${chips}</div>` : ''}
      ${body}
      ${water}${acounties}${provenance}
    </div>`;
  }

  function renderContamZones() {
    if (state.contam.zones) { state.contam.zones.remove(); state.contam.zones = null; }
    if (!state.contam.showZones) return;
    const grp = L.layerGroup();
    for (const s of state.contam.sites) {
      if (!s.impact_area_miles || !contamSiteVisible(s)) continue;
      const c = L.circle([s.lat, s.lng], {
        radius: s.impact_area_miles * 1609.34,
        color: s.status_color, weight: 1, opacity: 0.55,
        fillColor: s.status_color, fillOpacity: 0.10,
      });
      c.bindTooltip(`${s.site_name}: ~${s.impact_area_miles} mi impact radius`, { sticky: true });
      grp.addLayer(c);
    }
    grp.addTo(state.map);
    state.contam.zones = grp;
  }

  // Load per-county contamination-site density into state; painted by the
  // shared base layer when 'contam_density' is the active choropleth.
  async function loadContamDensity() {
    if (!state.contam.densityByFips.size) {
      const d = await api('/api/contamination/density');
      for (const c of d.counties) state.contam.densityByFips.set(c.fips, c);
      state.contam._densityMax = d.stats.max || 1;
    }
  }

  function updateContamStats() {
    const el = $('contam-stats');
    if (!el) return;
    if (!state.contam.showSites) { el.textContent = '—'; return; }
    const vis = state.contam.sites.filter(contamSiteVisible);
    const npl = vis.filter((s) => s.status_class === 'npl').length;
    el.textContent = `${vis.length} sites shown · ${npl} active Superfund · click a marker for detail`;
  }

  function renderCountyContamination(c) {
    const el = $('county-contam-list');
    const count = $('county-contam-count');
    if (!el) return;
    if (!c || !c.total) {
      count.textContent = '· none recorded';
      el.innerHTML = '<p class="muted small">No mapped contamination sites in this county.</p>';
      return;
    }
    count.textContent = `· ${c.total} site${c.total > 1 ? 's' : ''}${c.npl ? `, ${c.npl} Superfund` : ''}`;
    el.innerHTML = c.sites.map((s) => {
      const g = CONTAM_GLYPH[s.category] || '⚠';
      const hrs = s.hrs_score != null ? ` · HRS ${s.hrs_score.toFixed(1)}` : '';
      return `<div class="contam-li ${s.status_class}">
        <span class="g">${g}</span>
        <span class="n">${s.site_name}${s.company ? `<span class="muted small"> — ${s.company}</span>` : ''}</span>
        <span class="s">${s.status_class}${hrs}</span></div>`;
    }).join('');
  }

  // ---------- EPA Toxics Release Inventory (TRI) overlay ----------
  // Choropleth: a distinct teal→indigo scale (unused by any other layer).
  const TRI_PALETTE = ['#dff2f0', '#b9e2dd', '#8fcfc9', '#65bbb4', '#42a29d',
                       '#2f8783', '#236c6c', '#1a5358', '#143c47', '#0e2833'];
  // Trend pathway band colors.
  const TRI_PATH_COLORS = {
    air: '#e8873c', water: '#58a6ff', land: '#a3874f', underground: '#bc8cff',
  };
  // Facility-marker fill by release volume: amber (low) → deep red (high) so the
  // worst emitters stand out (per spec: bigger/redder = more pounds released).
  const TRI_MARKER_RAMP = ['#f0d06b', '#f0b429', '#e8873c', '#d96b35', '#bf3b2c', '#8b1f1f'];

  function triHasData() {
    return ((state.meta && state.meta.data_sources) || [])
      .some((s) => s.source_id === 'epa_tri' && (s.rows_loaded || 0) > 0);
  }

  function triPane() {
    if (!state.map.getPane('tri')) {
      state.map.createPane('tri').style.zIndex = 640;   // above choropleth
    }
    return 'tri';
  }

  function triMarkerColor(total, max) {
    const f = max > 0 ? Math.sqrt(Math.max(0, total) / max) : 0;
    return TRI_MARKER_RAMP[Math.min(TRI_MARKER_RAMP.length - 1,
      Math.floor(f * TRI_MARKER_RAMP.length))];
  }
  function triMarkerSize(total, max) {
    const f = max > 0 ? Math.sqrt(Math.max(0, total) / max) : 0;
    return Math.round(16 + f * 26);   // 16..42 px
  }

  function newTriClusterLayer() {
    if (typeof L.markerClusterGroup === 'function') {
      return L.markerClusterGroup({
        clusterPane: 'tri', maxClusterRadius: 48, chunkedLoading: true,
        showCoverageOnHover: false, spiderfyOnMaxZoom: true,
        removeOutsideVisibleBounds: true,
      });
    }
    return L.layerGroup();
  }

  async function loadTriSites() {
    if (state.tri.loaded) return;
    const d = await api('/api/tri/sites');
    state.tri.facilities = d.facilities || [];
    state.tri.latestYear = d.latest_year;
    state.tri.maxTotal = (d.stats && d.stats.max_total) || 1;
    state.tri.loaded = true;
  }

  // Tiny inline SVG sparkline of a facility's per-year total releases.
  function triSpark(spark) {
    if (!spark || spark.length < 2) return '';
    const vals = spark.map((p) => p.total);
    const max = Math.max(1, ...vals);
    const w = 130, h = 26, n = vals.length;
    const pts = vals.map((v, i) =>
      `${(i / (n - 1) * (w - 2) + 1).toFixed(1)},${(h - 2 - (v / max) * (h - 4)).toFixed(1)}`).join(' ');
    return `<div class="tri-spark-wrap"><svg class="tri-spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
      <polyline points="${pts}" fill="none" stroke="#e8873c" stroke-width="1.5"/></svg>
      <span class="muted small">${spark[0].year}–${spark[spark.length - 1].year}</span></div>`;
  }

  function triTrendBadge(trend) {
    if (trend === 'up') return '<span class="tri-trend up">▲ rising</span>';
    if (trend === 'down') return '<span class="tri-trend down">▼ falling</span>';
    return '<span class="tri-trend flat">■ ~flat</span>';
  }

  function triFacilityPopupHtml(f) {
    const path = (label, v) => v > 0
      ? `<div class="row"><span class="k">${label}</span> <b>${fmtLbs(v)}</b></div>` : '';
    const chem = (f.top_chemicals || []).slice(0, 5).map((c) =>
      `<div class="tri-chem"><span class="cn">${c.chemical}`
      + `${c.pfas ? ' <span class="tri-flag pfas" data-gloss="PFAS">PFAS</span>' : ''}`
      + `${c.carcinogen ? ' <span class="tri-flag carc">carc.</span>' : ''}</span>`
      + `<span class="cv">${fmtLbs(c.lbs)}</span></div>`).join('');
    const parent = (f.parent_company && f.parent_company !== 'NA') ? f.parent_company : '';
    const addr = [f.street_address, f.city].filter(Boolean).join(', ');
    const loc = addr ? `${addr}${f.county ? ', ' + f.county + ' Co.' : ''}` : (f.county ? `${f.county} Co.` : '');
    return `<div class="tri-popup">
      ${parent ? `<div class="tri-parent">${parent}</div>` : ''}
      <h4>${f.name}</h4>
      <div class="tri-meta">${f.industry_sector || 'Industry n/a'}${f.naics_code ? ` · NAICS ${f.naics_code}` : ''}</div>
      ${loc ? `<div class="tri-meta">${loc}</div>` : ''}
      ${f.company_summary ? `<div class="tri-summary">${f.company_summary}</div>` : ''}
      <div class="tri-total">${fmtLbs(f.total_lbs)} <span class="muted">released · ${f.year}</span> ${triTrendBadge(f.trend)}</div>
      <div class="tri-paths">${path('Air:', f.air_lbs)}${path('Water:', f.water_lbs)}${path('Land:', f.land_lbs)}${path('Underground:', f.underground_lbs)}</div>
      ${chem ? `<div class="tri-chem-head">Top chemicals released</div>${chem}` : ''}
      ${triSpark(f.spark)}
      <div class="tri-note">Facility data: EPA Toxics Release Inventory (self-reported, EPCRA). Pounds per year.</div>
    </div>`;
  }

  function renderTriMarkers() {
    if (state.tri.markers) { state.tri.markers.remove(); state.tri.markers = null; }
    if (!state.tri.showSites) { updateTriStats(); return; }
    const pane = triPane();
    const grp = newTriClusterLayer();
    const byId = new Map();          // facility_id -> marker, for click-to-locate
    const max = state.tri.maxTotal || 1;
    let shown = 0;
    for (const f of state.tri.facilities) {
      if (f.lat == null || f.lng == null) continue;
      const size = triMarkerSize(f.total_lbs, max);
      const color = triMarkerColor(f.total_lbs, max);
      const m = L.marker([f.lat, f.lng], {
        pane,
        icon: L.divIcon({
          className: 'tri-divicon',
          html: `<div class="tri-marker" style="width:${size}px;height:${size}px;background:${color}"><span>🏭</span></div>`,
          iconSize: [size, size], iconAnchor: [size / 2, size / 2],
        }),
      });
      m.bindPopup(triFacilityPopupHtml(f), { maxWidth: 340, className: 'tri-popup-wrap' });
      grp.addLayer(m);
      byId.set(f.facility_id, m);
      shown++;
    }
    grp.addTo(state.map);
    state.tri.markers = grp;
    state.tri.markerById = byId;
    updateTriStats(shown);
  }

  async function refreshTriSites() {
    if (state.tri.showSites) await loadTriSites();
    renderTriMarkers();
    renderMarkerKeys();
  }

  function updateTriStats(shown) {
    const el = $('tri-stats');
    if (!el) return;
    if (!state.tri.showSites || !state.tri.loaded) {
      el.textContent = triHasData()
        ? 'Enable "TRI industrial facilities" (Overlays) or choose "TRI toxic releases".'
        : 'No TRI data loaded — run refresh_data.py --source tri.';
      return;
    }
    const n = shown != null ? shown : state.tri.facilities.length;
    el.textContent = `${n.toLocaleString()} facilities · ${state.tri.latestYear} · bigger/redder = more released`;
  }

  // Per-county TRI totals for the choropleth (cached per pathway metric).
  async function loadTriDensity(metric) {
    if (state.tri._densityMetric === metric && state.tri.densityByFips.size) return;
    const d = await api('/api/tri/density', { metric });
    state.tri.densityByFips.clear();
    for (const c of d.counties) state.tri.densityByFips.set(c.fips, c);
    state.tri._densityMetric = metric;
    state.tri._densityMax = (d.stats && d.stats.max) || 1;
    state.tri.latestYear = d.year;
  }

  function showCountyTriTrend(on) {
    const m = $('tri-trend-modes-cty'), b = $('county-tri-trend-box');
    if (m) m.classList.toggle('hidden', !on);
    if (b) b.classList.toggle('hidden', !on);
  }

  // County-panel TRI section: pathway breakdown + top facilities + top chemicals.
  async function renderCountyTri(fips) {
    const el = $('county-tri-detail');
    const count = $('county-tri-count');
    if (!el) return;
    if (!triHasData()) {
      if (count) count.textContent = '';
      el.innerHTML = '<p class="muted small">No TRI data loaded.</p>';
      showCountyTriTrend(false);
      return;
    }
    let d;
    try { d = await api('/api/tri/county', { fips }); }
    catch (e) { el.innerHTML = '<p class="muted small">TRI data unavailable.</p>'; return; }
    if (!d.total_lbs) {
      if (count) count.textContent = '· none reported';
      el.innerHTML = '<p class="muted small">No TRI facilities reported releases in this county.</p>';
      showCountyTriTrend(false);
      return;
    }
    if (count) count.textContent =
      `· ${fmtLbs(d.total_lbs)} · ${d.facilities} facilit${d.facilities === 1 ? 'y' : 'ies'} · ${d.year}`;
    const pathRow = (p) => p.lbs > 0
      ? `<div class="tri-pathrow"><span class="k">${p.label}</span><span class="v">${fmtLbs(p.lbs)}</span></div>` : '';
    const facRow = (f) =>
      `<div class="tri-firow tri-clickable tri-fac" data-fid="${f.facility_id}" role="button" tabindex="0" title="Show this facility on the map">`
      + `<span class="n">${f.name}${f.industry ? `<span class="muted small"> — ${f.industry}</span>` : ''}</span>`
      + `<span class="v">${fmtLbs(f.lbs)} <span class="tri-chev">›</span></span></div>`;
    const chemRow = (c) =>
      `<div class="tri-firow tri-clickable tri-chem-item" data-chem="${encodeURIComponent(c.key || c.chemical)}" role="button" tabindex="0" title="What is this chemical?">`
      + `<span class="n">${c.chemical}${c.pfas ? ' <span class="tri-flag pfas" data-gloss="PFAS">PFAS</span>' : ''}${c.carcinogen ? ' <span class="tri-flag carc">carc.</span>' : ''}</span>`
      + `<span class="v">${fmtLbs(c.lbs)} <span class="tri-chev">›</span></span></div>`;
    el.innerHTML =
      `<div class="tri-paths-block">${d.pathways.map(pathRow).join('')}</div>`
      + `<div class="tri-sub">Top facilities <span class="tri-hint">click to locate</span></div>${d.top_facilities.map(facRow).join('')}`
      + `<div class="tri-sub">Top chemicals <span class="tri-hint">click for detail</span></div>${d.top_chemicals.map(chemRow).join('')}`
      + `<div class="tri-note">Self-reported to EPA (TRI). Pounds released in ${d.year}.</div>`;
    el.dataset.fips = fips;
    if (!el._triWired) {
      el._triWired = true;
      const act = (target) => {
        const fac = target.closest('.tri-fac');
        if (fac) { focusTriFacility(fac.dataset.fid); return; }
        const ch = target.closest('.tri-chem-item');
        if (ch) { openTriChemInfo(el.dataset.fips, decodeURIComponent(ch.dataset.chem)); }
      };
      el.addEventListener('click', (e) => act(e.target));
      el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); act(e.target); }
      });
    }
    showCountyTriTrend(true);
    if (!state.tri.trendCty) {
      state.tri.trendCty = createTrendPanel({
        canvasId: 'chart-tri-trend-cty', modesId: 'tri-trend-modes-cty',
        scopeId: null, chartKey: 'triTrendCty',
        endpoint: '/api/tri/trend', catColors: TRI_PATH_COLORS,
        totalLabel: 'Total on-site releases', totalColor: '#d9772f',
        paramsFor: (f) => ({ fips: f || '' }),
      });
    }
    state.tri.trendCty.load(fips);
  }

  // Locate a TRI facility on the map: turn the markers layer on if needed, zoom
  // until its marker un-clusters, and open its detail popup. The county panel
  // stays open the whole time.
  async function focusTriFacility(fid) {
    if (!fid) return;
    if (!state.tri.showSites) {
      state.tri.showSites = true;
      const cb = $('tri-sites'); if (cb) cb.checked = true;
      await refreshTriSites();
    } else if (!state.tri.loaded) {
      await refreshTriSites();
    }
    if (state.map) state.map.invalidateSize();
    const m = state.tri.markerById && state.tri.markerById.get(fid);
    if (!m) {
      const f = (state.tri.facilities || []).find((x) => x.facility_id === fid);
      if (f && f.lat != null && f.lng != null) state.map.setView([f.lat, f.lng], 11);
      return;
    }
    const open = () => m.openPopup();
    if (state.tri.markers && typeof state.tri.markers.zoomToShowLayer === 'function') {
      state.tri.markers.zoomToShowLayer(m, open);   // markercluster: un-cluster then open
    } else {
      state.map.setView(m.getLatLng(), Math.max(state.map.getZoom() || 8, 10));
      open();
    }
  }

  // Chemical drill-down modal for a chemical in the current county.
  async function openTriChemInfo(fips, chemKey) {
    const modal = $('tri-info-modal');
    const body = $('tri-info-body');
    if (!modal || !body) return;
    body.innerHTML = '<p class="muted">Loading…</p>';
    show(modal);
    let d;
    try { d = await api('/api/tri/chemical', { fips, chemical: chemKey }); }
    catch (e) { body.innerHTML = '<p class="muted">Could not load chemical info.</p>'; return; }
    if (!d || !d.found) { body.innerHTML = '<p class="muted">No data for this chemical.</p>'; return; }
    body.innerHTML = triChemInfoHtml(d);
  }

  function triChemInfoHtml(d) {
    const p = d.profile || {};
    const flags =
      (d.carcinogen ? '<span class="tri-flag carc">carcinogen</span> ' : '')
      + (d.pfas ? '<span class="tri-flag pfas" data-gloss="PFAS">PFAS</span>' : '');
    const line = (label, val) => val
      ? `<div class="tci-row"><span class="tci-k">${label}</span><span class="tci-v">${val}</span></div>` : '';
    const paths = (d.pathways || []).filter((x) => x.lbs > 0)
      .map((x) => `${x.label} ${fmtLbs(x.lbs)}`).join(' · ') || 'not reported this year';
    const facs = (d.facilities || []).map((f) =>
      `<div class="tci-firow"><span class="n">${f.name}</span><span class="v">${fmtLbs(f.lbs)}</span></div>`).join('')
      || '<p class="muted small">None in this county this year.</p>';
    const carcBlock = p.carcinogen ? `<div class="tci-carc">⚠ ${p.carcinogen}</div>` : '';
    return `
      <div class="tci-head">
        <h3>${d.chemical}</h3>
        <div class="tci-sub">${d.cas ? 'CAS ' + d.cas + ' · ' : ''}${flags}</div>
      </div>
      ${p.what ? `<p class="tci-what">${p.what}</p>` : ''}
      ${line('Used for', p.uses)}
      ${line('Health', p.health)}
      ${carcBlock}
      ${line('Typical pathways', p.pathways)}
      <div class="tci-stats">
        <div><strong>${fmtLbs(d.county_total_lbs)}</strong><span>released in ${d.county} Co. (${d.year})</span></div>
        <div><strong>${fmtLbs(d.statewide_total_lbs)}</strong><span>released statewide (${d.year})</span></div>
      </div>
      ${line('Released in-county via', paths)}
      <div class="tci-sub2">Facilities releasing it in ${d.county} County</div>
      <div class="tci-facs">${facs}</div>
      ${p.sourced === false ? '<p class="muted small tci-nolookup">Descriptive detail for this chemical is not in our reference set; the figures above are from the reported TRI data.</p>' : ''}
      <div class="tri-note">Release data: EPA Toxics Release Inventory. Health &amp; carcinogen classifications: EPA / IARC.</div>
    `;
  }

  // ---------- Wind roses & pesticide-drift overlay ----------
  const DIRS_16 = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                   'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
  // Wind-speed category colors (mph): 0-5 / 5-10 / 10-15 / 15+.
  const WIND_SPEED_BANDS = [
    { max: 5,        c: '#3fb950' },
    { max: 10,       c: '#d5c832' },
    { max: 15,       c: '#e8873c' },
    { max: Infinity, c: '#f85149' },
  ];
  function windSpeedColor(mph) {
    for (const b of WIND_SPEED_BANDS) if (mph <= b.max) return b.c;
    return '#f85149';
  }
  // bearing (deg, 0=N clockwise) -> unit vector in SVG space (y down)
  function bearingXY(deg, r) {
    const rad = deg * Math.PI / 180;
    return [Math.sin(rad) * r, -Math.cos(rad) * r];
  }

  // Build an SVG wind rose: petal length ∝ direction frequency, petal color by
  // that direction's mean wind speed band. Semi-transparent for map legibility.
  function windRoseSvg(station, size) {
    const cx = size / 2, cy = size / 2;
    const rMax = size / 2 - 6;
    const counts = station.direction_counts || {};
    const speeds = station.speed_by_direction || {};
    const maxCount = Math.max(1, ...DIRS_16.map((d) => counts[d] || 0));
    let petals = '';
    for (let i = 0; i < 16; i++) {
      const d = DIRS_16[i];
      const cnt = counts[d] || 0;
      if (!cnt) continue;
      const r = 6 + (rMax - 6) * (cnt / maxCount);
      const [x, y] = bearingXY(i * 22.5, r);
      const col = windSpeedColor(speeds[d] || 0);
      petals += `<line x1="${cx}" y1="${cy}" x2="${(cx + x).toFixed(1)}" y2="${(cy + y).toFixed(1)}" ` +
                `stroke="${col}" stroke-width="5" stroke-linecap="round" opacity="0.82"/>`;
    }
    // faint reference rings + center
    return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" class="wind-rose-svg">
      <circle cx="${cx}" cy="${cy}" r="${rMax}" fill="rgba(13,17,23,0.35)" stroke="rgba(154,164,178,0.35)" stroke-width="0.6"/>
      <circle cx="${cx}" cy="${cy}" r="${rMax * 0.5}" fill="none" stroke="rgba(154,164,178,0.25)" stroke-width="0.5"/>
      ${petals}
      <circle cx="${cx}" cy="${cy}" r="2.4" fill="#e6edf3"/>
    </svg>`;
  }

  async function loadWindStations() {
    if (state.wind.stations) return state.wind.stations;
    state.wind.stations = await api('/api/wind/stations');
    return state.wind.stations;
  }

  async function renderWindRoses() {
    if (state.wind.roseLayer) { state.wind.roseLayer.remove(); state.wind.roseLayer = null; }
    if (!state.wind.showRoses) { renderMarkerKeys(); return; }
    const data = await loadWindStations();
    const size = 58;
    const grp = L.layerGroup();
    for (const s of data.stations) {
      if (s.latitude == null || s.longitude == null) continue;
      const m = L.marker([s.latitude, s.longitude], {
        icon: L.divIcon({
          className: 'wind-rose-icon',
          html: windRoseSvg(s, size),
          iconSize: [size, size],
          iconAnchor: [size / 2, size / 2],
        }),
        interactive: true,
      });
      m.bindTooltip(
        `<strong>${s.station_name}</strong> (${s.station_id})<br>` +
        `Prevailing: <b>${s.prevailing_from}</b> at ${s.avg_speed_mph} mph · ${s.pct_calm}% calm<br>` +
        `Drift toward <b>${s.drift_toward}</b> · growing season, ${s.years}`,
        { className: 'wind-tip', direction: 'top', offset: [0, -size / 2] },
      );
      grp.addLayer(m);
    }
    grp.addTo(state.map);
    state.wind.roseLayer = grp;
    renderMarkerKeys();
  }

  // Drift arrow SVG pointing "up" (north); the marker is rotated by CSS to the
  // drift bearing. Colored by application intensity, length by wind speed.
  function driftArrowSvg(a, size) {
    const w = size, h = size;
    const cx = w / 2;
    const len = 12 + (h - 20) * (0.25 + 0.75 * (a.speed_scale || 0));  // speed → length
    const tail = h - 4, tip = tail - len;
    // intensity green→yellow→red
    const col = a.intensity >= 0.66 ? '#f85149' : (a.intensity >= 0.33 ? '#e8873c' : '#3fb950');
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
      <line x1="${cx}" y1="${tail}" x2="${cx}" y2="${tip + 4}" stroke="${col}" stroke-width="3.2" stroke-linecap="round"/>
      <path d="M${cx} ${tip} L${cx - 5} ${tip + 9} L${cx + 5} ${tip + 9} Z" fill="${col}"/>
    </svg>`;
  }

  async function renderDriftArrows() {
    if (state.wind.driftLayer) { state.wind.driftLayer.remove(); state.wind.driftLayer = null; }
    if (!state.wind.showDrift) { renderMarkerKeys(); return; }
    const data = await api('/api/wind/drift');
    const size = 46;
    const grp = L.layerGroup();
    for (const a of data.arrows) {
      const m = L.marker([a.lat, a.lon], {
        icon: L.divIcon({
          className: 'drift-arrow-icon',
          html: `<div class="drift-arrow-rot" style="transform:rotate(${a.drift_deg}deg)">${driftArrowSvg(a, size)}</div>`,
          iconSize: [size, size],
          iconAnchor: [size / 2, size / 2],
        }),
      });
      m.bindTooltip(
        `<strong>${a.county} County</strong><br>` +
        `Prevailing wind: <b>${a.prevailing_from}</b> at ${a.avg_speed_mph} mph (Apr–Sep avg)<br>` +
        `Primary drift direction: <b>${a.drift_toward}</b><br>` +
        `<span class="muted">${fmtLbs(a.per_sq_mile_lbs)}/mi² · via ${a.station_id} (${a.station_distance_mi} mi)</span>`,
        { className: 'wind-tip', direction: 'top' },
      );
      grp.addLayer(m);
    }
    grp.addTo(state.map);
    state.wind.driftLayer = grp;
    renderMarkerKeys();
  }

  function clearDriftZone() {
    if (state.wind.zoneLayer) { state.wind.zoneLayer.remove(); state.wind.zoneLayer = null; }
  }

  // Draw the downwind drift fan for a clicked county (near/mid/far bands).
  async function showDriftZone(fips) {
    clearDriftZone();
    if (!state.wind.driftZoneOnClick) return;
    let z;
    try {
      z = await api(`/api/wind/drift-zone/${fips}`);
    } catch (e) {
      return;   // county has no nearby station / no data
    }
    const grp = L.layerGroup();
    const bandStyle = {
      near: { fillColor: '#f85149', fillOpacity: 0.34 },
      mid:  { fillColor: '#e8873c', fillOpacity: 0.24 },
      far:  { fillColor: '#f0b429', fillOpacity: 0.15 },
    };
    // draw far→near so nearer (stronger) bands sit on top
    for (const b of [...z.bands].reverse()) {
      const st = bandStyle[b.key] || bandStyle.far;
      const poly = L.polygon(b.ring, {
        ...st, color: st.fillColor, weight: 1, opacity: 0.6, interactive: true,
      });
      poly.bindTooltip(
        `<strong>${z.county} County — drift zone</strong><br>` +
        `${b.label} · ${b.r0}–${b.r1} mi<br>` +
        `Wind from <b>${z.prevailing_from}</b> at ${z.avg_speed_mph} mph → drift <b>${z.drift_toward}</b><br>` +
        `<span class="muted small">${z.disclaimer}</span>`,
        { className: 'wind-tip drift-zone-tip', sticky: true },
      );
      grp.addLayer(poly);
    }
    grp.addTo(state.map);
    state.wind.zoneLayer = grp;
  }

  function refreshAllWindLayers() {
    renderWindRoses();
    renderDriftArrows();
  }

  // ---------- filters ----------
  function bindSegment(rootId, key) {
    const root = $(rootId === 'seg-normalize' ? 'seg-normalize' : null);
    document.querySelectorAll(`#${rootId} button`).forEach((b) => {
      b.addEventListener('click', () => {
        document.querySelectorAll(`#${rootId} button`).forEach((x) => x.classList.remove('active'));
        b.classList.add('active');
        state[key] = b.dataset.val;
        refreshAll();
      });
    });
  }

  function bindFilters() {
    $('filter-category').addEventListener('change', (e) => {
      state.category = e.target.value;
      refreshAll();
    });
    $('filter-compound').addEventListener('change', (e) => {
      state.compound = e.target.value;
      markFeatured(state.compound);
      refreshAll();
    });

    // segments — bind both (estimate + normalize). Skip the cancer measure
    // segment, which has its own handler below.
    document.querySelectorAll('.panel .seg').forEach((seg) => {
      if (seg.id === 'seg-cancer-dtype') return;
      seg.querySelectorAll('button').forEach((b) => {
        b.addEventListener('click', () => {
          seg.querySelectorAll('button').forEach((x) => x.classList.remove('active'));
          b.classList.add('active');
          // figure out which segment by buttons' data values
          const v = b.dataset.val;
          if (['low', 'avg', 'high'].includes(v)) state.estimate = v;
          else state.normalize = v;
          refreshAll();
        });
      });
    });

    $('year-slider').addEventListener('input', (e) => {
      state.year = state.years[Number(e.target.value)];
      $('year-label').textContent = state.year;
      refreshAll();
    });

    $('play-btn').addEventListener('click', () => {
      if (state.playInterval) {
        clearInterval(state.playInterval);
        state.playInterval = null;
        $('play-btn').textContent = '▶';
        return;
      }
      $('play-btn').textContent = '⏸';
      state.playInterval = setInterval(() => {
        const slider = $('year-slider');
        let i = Number(slider.value);
        i = (i + 1) % state.years.length;
        slider.value = i;
        slider.dispatchEvent(new Event('input'));
      }, 1300);
    });

    // County-coloring radio group — exactly one choropleth at a time.
    document.querySelectorAll('input[name="choropleth"]').forEach((r) => {
      r.addEventListener('change', (e) => {
        if (e.target.checked) setActiveChoropleth(e.target.value);
      });
    });

    // Water-quality overlays
    $('wq-sites').addEventListener('change', (e) => {
      state.water.showSites = e.target.checked; refreshWaterSites(); renderMarkerKeys();
    });
    $('wq-heat').addEventListener('change', (e) => {
      state.water.showHeat = e.target.checked; refreshWaterHeat(); renderMarkerKeys();
    });
    $('wq-watersheds').addEventListener('change', (e) => {
      state.water.showWatersheds = e.target.checked; refreshWaterWatersheds(); renderMarkerKeys();
    });
    $('wq-compound').addEventListener('change', (e) => {
      state.water.compound = e.target.value;
      // Manually picking turns off match-main to avoid surprise
      if (state.water.compound) {
        $('wq-match-main').checked = false;
        state.water.matchMain = false;
      }
      refreshAllWaterLayers();
    });
    $('wq-match-main').addEventListener('change', (e) => {
      state.water.matchMain = e.target.checked;
      if (state.water.matchMain) {
        $('wq-compound').value = '';
        state.water.compound = '';
      }
      refreshAllWaterLayers();
    });

    // Respiratory metric — reloads the fill when respiratory is active.
    $('resp-metric').addEventListener('change', (e) => {
      state.resp.metric = e.target.value;
      if (state.activeChoropleth === 'resp') setActiveChoropleth('resp');
      else updateActiveIndicator();
    });

    // Cancer type / measure — reload the fill when cancer is active.
    $('cancer-type').addEventListener('change', (e) => {
      state.cancer.type = e.target.value;
      if (state.activeChoropleth === 'cancer') setActiveChoropleth('cancer');
      else updateActiveIndicator();
    });
    document.querySelectorAll('#seg-cancer-dtype button').forEach((b) => {
      b.addEventListener('click', () => {
        document.querySelectorAll('#seg-cancer-dtype button').forEach((x) => x.classList.remove('active'));
        b.classList.add('active');
        state.cancer.dataType = b.dataset.val;
        if (state.activeChoropleth === 'cancer') setActiveChoropleth('cancer');
        else updateActiveIndicator();
      });
    });
    $('cancer-evidence-btn').addEventListener('click', openCancerEvidence);
    $('cancer-evidence-close').addEventListener('click', () => hide($('cancer-evidence-modal')));
    $('cancer-evidence-modal').addEventListener('click', (e) => {
      if (e.target.id === 'cancer-evidence-modal') hide($('cancer-evidence-modal'));
    });

    // Industrial contamination overlays (markers + impact zones stack freely)
    $('contam-sites').addEventListener('change', async (e) => {
      state.contam.showSites = e.target.checked;
      if (e.target.checked) await loadContamination();
      renderContamMarkers(); renderContamZones(); renderMarkerKeys();
    });
    ['npl', 'pfas', 'state', 'deleted'].forEach((k) => {
      $(`contam-f-${k}`).addEventListener('change', (e) => {
        state.contam.filters[k] = e.target.checked;
        renderContamMarkers(); renderContamZones();
      });
    });
    $('contam-zones').addEventListener('change', async (e) => {
      state.contam.showZones = e.target.checked;
      if (e.target.checked) await loadContamination();
      renderContamZones(); renderMarkerKeys();
    });

    // TRI industrial-facility markers (independent overlay).
    $('tri-sites').addEventListener('change', async (e) => {
      state.tri.showSites = e.target.checked;
      await refreshTriSites();
    });
    // TRI choropleth pathway sub-option.
    $('tri-metric').addEventListener('change', async (e) => {
      state.tri.metric = e.target.value;
      if (state.activeChoropleth === 'tri') {
        await loadTriDensity(state.tri.metric);
        if (state.geoLayer) state.geoLayer.setStyle(styleFor);
        restyleSelection();
        renderLegend();
        updateActiveIndicator();
      }
    });

    // Wind / drift overlays (stack freely)
    $('wind-roses').addEventListener('change', (e) => {
      state.wind.showRoses = e.target.checked; renderWindRoses();
    });
    $('wind-drift').addEventListener('change', (e) => {
      state.wind.showDrift = e.target.checked; renderDriftArrows();
    });
    $('wind-driftzone').addEventListener('change', (e) => {
      state.wind.driftZoneOnClick = e.target.checked;
      if (!e.target.checked) clearDriftZone();
      else if (state.selectedFips) showDriftZone(state.selectedFips);
    });

    // View switch (map / explore / correlation / …), with shareable #hash deep links.
    document.querySelectorAll('#view-switch button').forEach((b) => {
      b.addEventListener('click', () => switchView(b.dataset.view, true));
    });
    window.addEventListener('hashchange', () => {
      const v = (location.hash || '').replace('#', '');
      if (v && document.getElementById('view-' + v)) switchView(v, false);
    });

    $('county-close').addEventListener('click', closeCountyPanel);
    $('county-back').addEventListener('click', closeCountyPanel);
    $('open-sources').addEventListener('click', openSources);
    $('sources-close').addEventListener('click', () => hide($('sources-modal')));
    $('sources-modal').addEventListener('click', (e) => {
      if (e.target.id === 'sources-modal') hide($('sources-modal'));
    });

    // TRI chemical info modal — close via ×, backdrop click, or Escape.
    $('tri-info-close').addEventListener('click', () => hide($('tri-info-modal')));
    $('tri-info-modal').addEventListener('click', (e) => {
      if (e.target.id === 'tri-info-modal') hide($('tri-info-modal'));
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') hide($('tri-info-modal'));
    });

    bindSearch();
  }

  // Intro modal is wired in DOMContentLoaded (not bindEvents) so its buttons
  // work even while the map data is still loading on first visit.
  const INTRO_KEY = 'pm_intro_seen_v1';
  function wireIntro() {
    $('open-intro').addEventListener('click', () => show($('intro-modal')));
    $('intro-close').addEventListener('click', () => hide($('intro-modal')));
    $('intro-start').addEventListener('click', dismissIntro);
    $('intro-modal').addEventListener('click', (e) => {
      if (e.target.id === 'intro-modal') hide($('intro-modal'));
    });
    $('intro-sources-link').addEventListener('click', (e) => {
      e.preventDefault();
      hide($('intro-modal'));
      openSources();
    });
  }
  function dismissIntro() {
    // Persist dismissal only if the viewer left "don't show again" checked.
    if ($('intro-dontshow').checked) {
      try { localStorage.setItem(INTRO_KEY, '1'); } catch (e) {}
    }
    hide($('intro-modal'));
  }
  function maybeShowIntroOnFirstVisit() {
    // Skip the first-visit intro when arriving via a shared deep link (query
    // params or a #view hash) — the visitor wanted a specific view, not onboarding.
    if (location.search.length > 1 || (location.hash && location.hash !== '#')) return;
    let seen = false;
    try { seen = localStorage.getItem(INTRO_KEY) === '1'; } catch (e) {}
    if (!seen) show($('intro-modal'));
  }

  function markFeatured(name) {
    document.querySelectorAll('#featured-compounds button').forEach((b) => {
      b.classList.toggle('active', b.dataset.compound === name);
    });
  }

  function buildFeatured() {
    const root = $('featured-compounds');
    root.innerHTML = '';
    const all = document.createElement('button');
    all.textContent = 'Clear';
    all.dataset.compound = '';
    all.addEventListener('click', () => {
      state.compound = '';
      $('filter-compound').value = '';
      markFeatured('');
      refreshAll();
    });
    root.appendChild(all);
    for (const name of state.meta.featured_compounds) {
      const b = document.createElement('button');
      b.textContent = name;
      b.dataset.compound = name;
      b.addEventListener('click', () => {
        state.compound = name;
        $('filter-compound').value = name;
        markFeatured(name);
        refreshAll();
      });
      root.appendChild(b);
    }
  }

  // ---------- search ----------
  function bindSearch() {
    const input = $('search');
    const out = $('search-results');
    let t = null;
    input.addEventListener('input', () => {
      clearTimeout(t);
      const q = input.value.trim();
      if (!q) { hide(out); return; }
      t = setTimeout(async () => {
        const r = await api('/api/search', { q });
        out.innerHTML = '';
        if (r.counties.length) {
          const h = document.createElement('div');
          h.className = 'group-title'; h.textContent = 'Counties';
          out.appendChild(h);
          r.counties.forEach((c) => {
            const it = document.createElement('div');
            it.className = 'item';
            it.textContent = `${c.name} County`;
            it.addEventListener('click', () => {
              hide(out); input.value = '';
              openCounty(c.fips);
            });
            out.appendChild(it);
          });
        }
        if (r.compounds.length) {
          const h = document.createElement('div');
          h.className = 'group-title'; h.textContent = 'Compounds';
          out.appendChild(h);
          r.compounds.forEach((c) => {
            const it = document.createElement('div');
            it.className = 'item';
            it.textContent = c;
            it.addEventListener('click', () => {
              hide(out); input.value = '';
              state.compound = c;
              $('filter-compound').value = c;
              markFeatured(c);
              refreshAll();
            });
            out.appendChild(it);
          });
        }
        if (!r.counties.length && !r.compounds.length) {
          out.innerHTML = '<div class="item muted">No matches</div>';
        }
        show(out);
      }, 180);
    });
    document.addEventListener('click', (e) => {
      if (!out.contains(e.target) && e.target !== input) hide(out);
    });
  }

  // ---------- sources modal ----------
  function openSources() {
    // "Data current as of" banner — the most recent successful refresh.
    const asOf = state.meta.data_current_as_of;
    const banner = $('sources-asof');
    if (banner) {
      banner.textContent = asOf
        ? `Data current as of ${asOf.slice(0, 10)}`
        : 'Data has not been refreshed yet — run refresh_data.py to populate freshness.';
    }

    const tbl = $('sources-table');
    tbl.innerHTML =
      '<tr><th>Source</th><th>Status</th><th>Coverage</th><th>Rows</th>' +
      '<th>Last updated</th><th>Notes</th></tr>';
    for (const s of state.meta.data_sources) {
      const tr = document.createElement('tr');
      // Coverage window (from the refreshed data), e.g. "2018–2022".
      const cov = s.coverage_start
        ? (s.coverage_end && s.coverage_end !== s.coverage_start
            ? `${s.coverage_start}–${s.coverage_end}`
            : s.coverage_start)
        : '';
      // Prefer last_success (a real refresh) over last_updated for the date.
      const updated = (s.last_success || s.last_updated || '').slice(0, 10);
      const staleTag = s.stale
        ? ' <span class="stale-flag" title="Older than its expected refresh '
          + 'interval — data may be out of date">stale</span>'
        : '';
      const failTag = s.refresh_status === 'failed'
        ? ' <span class="stale-flag" title="Last refresh attempt failed; '
          + 'showing the last good data">refresh failed</span>'
        : '';
      tr.innerHTML = `
        <td><a href="${s.url}" target="_blank" rel="noopener">${s.title}</a></td>
        <td><span class="status status-${s.status}">${s.status}</span></td>
        <td class="muted small">${cov}</td>
        <td>${(s.rows_loaded || 0).toLocaleString()}</td>
        <td class="muted small">${updated}${staleTag}${failTag}</td>
        <td class="small">${s.notes || ''}</td>`;
      tbl.appendChild(tr);
    }
    show($('sources-modal'));
  }

  // Activate one of the top-level views. Central so both button clicks, #hash
  // deep links, and boot-time restoration go through the same path.
  const VIEWS = ['map', 'explore', 'respiratory', 'cancer'];
  function switchView(v, updateHash) {
    if (!VIEWS.includes(v)) v = 'map';
    // Leaving the map view — dismiss any open mobile bottom sheets.
    document.body.classList.remove('m-layers-open', 'm-detail-open');
    document.querySelectorAll('#view-switch button').forEach((x) =>
      x.classList.toggle('active', x.dataset.view === v));
    VIEWS.forEach((name) =>
      $('view-' + name).classList.toggle('hidden', name !== v));
    if (v === 'explore') renderExplore();
    else if (v === 'respiratory') renderRespiratory();
    else if (v === 'cancer') renderCancer();
    else if (state.map) state.map.invalidateSize();
    if (updateHash) {
      try { history.replaceState(null, '', v === 'map' ? '#' : '#' + v); } catch (e) {}
    }
  }

  // ---------- Unified "Explore correlations" view ----------
  const fmtR = (v) => (v == null ? '—' : Number(v).toFixed(3));
  const fmtP = (v) => (v == null ? '—'
    : v < 0.001 ? Number(v).toExponential(1) : Number(v).toFixed(3));

  async function renderExplore() {
    const st = state.explore;
    if (!st.vars) {
      st.vars = await api('/api/explore/variables');
      fillExploreSelect($('explore-x'), st.vars.x, st.vars.x_default);
      fillExploreSelect($('explore-y'), st.vars.y, st.vars.y_default);
    }
    if (!st.wired) {
      st.wired = true;
      ['explore-x', 'explore-y', 'explore-rural', 'explore-exclude-missing']
        .forEach((id) => $(id).addEventListener('change', refreshExplore));
    }
    await refreshExplore();
  }

  function fillExploreSelect(sel, items, def) {
    sel.innerHTML = '';
    const groups = {};
    const order = [];
    for (const it of items) {
      if (!groups[it.group]) { groups[it.group] = []; order.push(it.group); }
      groups[it.group].push(it);
    }
    for (const g of order) {
      const og = document.createElement('optgroup');
      og.label = g;
      for (const it of groups[g]) {
        const o = document.createElement('option');
        o.value = it.key;
        o.textContent = it.label;
        og.appendChild(o);
      }
      sel.appendChild(og);
    }
    if (def) sel.value = def;
  }

  async function refreshExplore() {
    const x = $('explore-x').value;
    const y = $('explore-y').value;
    const cohort = $('explore-rural').checked ? 'rural' : 'all';
    const excludeMissing = $('explore-exclude-missing').checked;
    const d = await api('/api/explore', {
      x, y, cohort, exclude_missing: excludeMissing ? 1 : 0,
    });

    const xFmt = d.x.is_count ? PMCharts.fmtCount : PMCharts.fmtLbs;
    const yFmt = PMCharts.fmtNum;
    const xLbl = d.x.label, yLbl = d.y.label;

    // Split dots by urban/rural for a clearly-labelled legend.
    const rural = [], urban = [];
    for (const p of d.points) {
      const pt = { x: p.x, y: p.y, label: p.county, ur: p.is_urban ? 'Urban' : 'Rural' };
      (p.is_urban ? urban : rural).push(pt);
    }
    const datasets = [
      { label: `Rural counties (${rural.length})`, data: rural,
        backgroundColor: '#3fb950', pointRadius: 6, pointHoverRadius: 9 },
      { label: `Urban counties (${urban.length})`, data: urban,
        backgroundColor: '#58a6ff', pointRadius: 6, pointHoverRadius: 9 },
    ];
    if (d.trend_line) {
      datasets.push({
        label: 'Overall trend', data: d.trend_line, type: 'line',
        borderColor: 'rgba(240,180,41,.9)', borderWidth: 2, borderDash: [6, 4],
        pointRadius: 0, fill: false,
      });
    }
    PMCharts.destroyIfExists(state.explore.chart);
    state.explore.chart = PMCharts.scatter('chart-explore', datasets, {
      xLabel: `${xLbl} (${d.x.unit})`,
      yLabel: `${yLbl} — ${d.y.unit}`,
      xName: xLbl, yName: yLbl, xFmt, yFmt,
    });

    $('explore-scatter-title').textContent = `${xLbl} vs ${yLbl}`;
    $('explore-scatter-explainer').innerHTML =
      `Each dot is one Michigan county. <b>Left-to-right</b> shows ${xLbl.toLowerCase()} ` +
      `(${d.x.unit}). <b>Bottom-to-top</b> shows ${yLbl.toLowerCase()} (${d.y.unit}). ` +
      `If dots trend upward from left to right, more ${xLbl.toLowerCase()} is associated ` +
      `with higher ${yLbl.toLowerCase()} in this data.`;

    renderExploreReadout(d);
    $('explore-summary').textContent =
      PMGloss.summarySentence(d.fit, xLbl.toLowerCase(), yLbl.toLowerCase(), cohort);
    $('explore-caveat').textContent = d.caveat || '';

    // Surface the "TRI as a control" note whenever an industrial-release
    // variable is being compared, to frame it against the pesticide signal.
    const triNote = $('explore-tri-note');
    if (triNote) triNote.classList.toggle('hidden', !(x && x.startsWith('tri')));
  }

  function renderExploreReadout(d) {
    const el = $('explore-readout');
    const yNoun = d.y.label.toLowerCase() + ' rates';
    const info = PMGloss.interpret(d.fit, yNoun);
    if (!info.ok) {
      el.innerHTML = `<div class="sr-row">${info.r2Sentence}</div>`;
      return;
    }
    const sigClass = info.significant ? 'sr-sig-yes' : 'sr-sig-no';
    let html = '';
    html += `<div class="sr-row"><span class="sr-strong">How strong is the pattern?</span> `
      + `${info.r2Sentence} ${PMGloss.infoIcon('R-squared')}</div>`;
    html += `<div class="sr-row"><span class="sr-strong">Is it likely real, or chance?</span> `
      + `<span class="${sigClass}">${info.pSentence}</span> ${PMGloss.infoIcon('p-value')}</div>`;
    if (d.quartiles) {
      const q = d.quartiles;
      html += `<div class="sr-row">Counties in the <b>top 25%</b> for ${d.x.label.toLowerCase()} `
        + `average <b>${PMCharts.fmtNum(q.top_mean)}</b> ${d.y.unit}, versus `
        + `<b>${PMCharts.fmtNum(q.bottom_mean)}</b> in the bottom 25%.</div>`;
    }
    html += `<div class="sr-row muted small">Based on ${d.fit.n} counties`
      + (d.n_excluded_missing ? ` (${d.n_excluded_missing} left out for missing data)` : '')
      + `. Raw statistics: correlation r = ${fmtR(d.fit.r)}, `
      + `R² = ${fmtR(d.fit.r2)}, p-value = ${fmtP(d.fit.p_value)}.</div>`;
    el.innerHTML = html;
  }

  // ---------- Respiratory tab ----------
  async function renderRespiratory() {
    bindRespiratoryControlsOnce();
    await Promise.all([
      refreshRespScatter(),
      refreshRespTrend(),
      refreshRespRankings(),
    ]);
  }

  let _respBound = false;
  function bindRespiratoryControlsOnce() {
    if (_respBound) return;
    _respBound = true;
    $('resp-scatter-pest').addEventListener('change', (e) => {
      state.resp.scatterPest = e.target.value;
      refreshRespScatter();
    });
    $('resp-scatter-resp').addEventListener('change', (e) => {
      state.resp.scatterResp = e.target.value;
      refreshRespScatter(); refreshRespRankings();
    });
    $('exclude-wayne').addEventListener('change', (e) => {
      state.resp.excludeWayne = e.target.checked;
      refreshRespScatter(); refreshRespRankings();
    });
    document.querySelectorAll('#resp-table th.sortable').forEach((th) => {
      th.addEventListener('click', () => {
        const k = th.dataset.sort;
        if (state.resp.sortKey === k) {
          state.resp.sortDir = state.resp.sortDir === 'asc' ? 'desc' : 'asc';
        } else {
          state.resp.sortKey = k;
          state.resp.sortDir = (k === 'county' || k.startsWith('rank_')) ? 'asc' : 'desc';
        }
        renderRespTable();
      });
    });
  }

  async function refreshRespScatter() {
    const [scatter, stats] = await Promise.all([
      api('/api/correlation/respiratory/scatter', {
        pest: state.resp.scatterPest, resp: state.resp.scatterResp,
        exclude_wayne: state.resp.excludeWayne ? '1' : '',
      }),
      api('/api/correlation/respiratory/stats', {
        pest: state.resp.scatterPest, resp: state.resp.scatterResp,
        exclude_wayne: state.resp.excludeWayne ? '1' : '',
      }),
    ]);
    const mk = (p) => ({ x: p.x, y: p.y, label: p.county, ur: p.is_urban ? 'Urban' : 'Rural' });
    const urban = scatter.points.filter((p) => p.is_urban && p.x != null && p.y != null).map(mk);
    const rural = scatter.points.filter((p) => !p.is_urban && p.x != null && p.y != null).map(mk);
    const fit = scatter.fit || {};
    const respLabel = labelForRespMetric(state.resp.scatterResp);
    const pestLabel = labelForPestMetric(state.resp.scatterPest);
    const datasets = [
      { label: `Rural counties (${rural.length})`,
        data: rural, backgroundColor: '#3fb950', pointRadius: 6, pointHoverRadius: 9 },
      { label: `Urban counties (${urban.length})`,
        data: urban, backgroundColor: '#58a6ff', pointRadius: 6, pointHoverRadius: 9 },
    ];
    if (scatter.trend_line && fit.r != null) {
      datasets.push({
        label: 'Overall trend',
        data: scatter.trend_line, type: 'line',
        borderColor: 'rgba(240,180,41,.9)', borderWidth: 2,
        borderDash: [6, 4], pointRadius: 0, fill: false,
      });
    }
    PMCharts.destroyIfExists(state.charts.respScatter);
    state.charts.respScatter = PMCharts.scatter('chart-resp-scatter', datasets, {
      xLabel: `Pesticide applied — ${pestLabel} (lbs)`,
      yLabel: respLabel,
      xName: 'Pesticide', yName: respLabel, yFmt: PMCharts.fmtNum,
    });
    // One-sentence quartile summary below the chart.
    const q = stats.quartile_comparison || {};
    const summary = $('resp-summary');
    if (q.top_mean == null || q.bottom_mean == null) {
      summary.textContent = 'Quartile comparison unavailable for the current filter.';
    } else {
      const diff = q.top_mean - q.bottom_mean;
      const pct  = q.bottom_mean ? (diff / q.bottom_mean * 100) : null;
      const dir  = diff > 0 ? 'higher' : 'lower';
      const pctText = pct == null ? '' : ` (${pct >= 0 ? '+' : ''}${pct.toFixed(0)}%)`;
      summary.innerHTML =
        `Counties in the <strong>top 25% for pesticide use</strong> have an average ` +
        `respiratory rate of <strong>${q.top_mean.toFixed(1)}</strong> vs ` +
        `<strong>${q.bottom_mean.toFixed(1)}</strong> for the bottom 25% — ` +
        `<strong>${Math.abs(diff).toFixed(1)} ${dir}${pctText}</strong>.`;
    }
  }

  async function refreshRespTrend() {
    const d = await api('/api/respiratory/trends', { metric: 'combined' });
    PMCharts.destroyIfExists(state.charts.respTrend);
    state.charts.respTrend = PMCharts.lineChart(
      'chart-resp-trend',
      d.trend.map((p) => p.year),
      d.trend.map((p) => p.rate),
      '#8db0ff',
    );
    if (state.charts.respTrend) {
      const c = state.charts.respTrend;
      c.options.scales.y.title = { display: true, text: 'rate per 10,000' };
      c.options.scales.y.ticks = { callback: (v) => v.toFixed(0) };
      c.update();
    }
  }

  function labelForRespMetric(k) {
    return ({
      asthma_ed:   'Asthma ED visits (per 10,000)',
      asthma_hosp: 'Asthma hospitalizations (per 10,000)',
      copd_ed:     'COPD ED visits (per 10,000)',
      copd_hosp:   'COPD hospitalizations (per 10,000)',
      prevalence:  'Adult asthma prevalence (%)',
    })[k] || k;
  }
  function labelForPestMetric(k) {
    return ({ total:'total lbs', per_sq_mile:'lbs / mi²',
              herbicide:'herbicide lbs', insecticide:'insecticide lbs',
              fungicide:'fungicide lbs' })[k] || k;
  }

  async function refreshRespRankings() {
    const d = await api('/api/correlation/respiratory/rankings',
                        { resp: state.resp.scatterResp });
    state.resp.rankings = d.rows;
    renderRespTable();
  }

  function renderRespTable() {
    const tbody = $('resp-tbody');
    tbody.innerHTML = '';
    const rows = state.resp.rankings.slice();
    const k = state.resp.sortKey;
    const dir = state.resp.sortDir === 'asc' ? 1 : -1;
    rows.sort((a, b) => {
      const va = a[k], vb = b[k];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === 'string') return va.localeCompare(vb) * dir;
      return (va - vb) * dir;
    });
    document.querySelectorAll('#resp-table th').forEach((th) => {
      th.classList.remove('sorted-asc', 'sorted-desc');
      if (th.dataset.sort === k) {
        th.classList.add(dir === 1 ? 'sorted-asc' : 'sorted-desc');
      }
    });
    const num = (v) => v == null ? '—' : Number(v).toFixed(1);
    for (const r of rows) {
      const tr = document.createElement('tr');
      if (r.overlap_top20) tr.classList.add('overlap');
      tr.innerHTML = `
        <td class="right">${r.rank_pest ?? '—'}</td>
        <td>${r.county}</td>
        <td><span class="${r.is_urban ? 'urban-pill' : 'rural-pill'}">${r.is_urban ? 'urban' : 'rural'}</span></td>
        <td class="right">${r.pest_lbs == null ? '—' : PMCharts.fmtLbs(r.pest_lbs)}</td>
        <td class="right">${num(r.asthma_ed_rate)}</td>
        <td class="right">${num(r.asthma_hosp_rate)}</td>
        <td class="right">${num(r.copd_ed_rate)}</td>
        <td class="right">${num(r.copd_hosp_rate)}</td>
        <td class="right">${r.rank_resp ?? '—'}</td>`;
      tr.addEventListener('click', () => {
        document.querySelector('#view-switch button[data-view="map"]').click();
        openCounty(r.county_fips);
      });
      tbody.appendChild(tr);
    }
  }

  // ---------- Cancer tab ----------
  async function renderCancer() {
    bindCancerControlsOnce();
    // Keep the correlation-tab cancer selector in sync with the map selection.
    $('cancer-scatter-cancer').value = state.cancer.scatterCancer;
    $('cancer-scatter-pest').value = ensurePestOption(state.cancer.scatterPest);
    $('cancer-scatter-dtype').value = state.cancer.scatterDtype;
    await Promise.all([
      refreshCancerScatter(),
      renderCancerMatrix(),
      refreshCancerQuartiles(),
    ]);
  }

  let _cancerBound = false;
  function bindCancerControlsOnce() {
    if (_cancerBound) return;
    _cancerBound = true;
    $('cancer-scatter-cancer').addEventListener('change', (e) => {
      state.cancer.scatterCancer = e.target.value;
      refreshCancerScatter(); refreshCancerQuartiles();
    });
    $('cancer-scatter-pest').addEventListener('change', (e) => {
      state.cancer.scatterPest = e.target.value;
      refreshCancerScatter(); refreshCancerQuartiles();
    });
    $('cancer-scatter-dtype').addEventListener('change', (e) => {
      state.cancer.scatterDtype = e.target.value;
      refreshCancerScatter(); refreshCancerQuartiles();
    });
    $('cancer-exclude-urban').addEventListener('change', (e) => {
      state.cancer.excludeUrban = e.target.checked;
      refreshCancerScatter(); refreshCancerQuartiles();
    });
    $('cancer-rural-only').addEventListener('change', (e) => {
      state.cancer.ruralOnly = e.target.checked;
      refreshCancerScatter(); refreshCancerQuartiles();
    });
    $('cancer-control-smoking').addEventListener('change', (e) => {
      state.cancer.controlSmoking = e.target.checked;
      refreshCancerScatter();
    });
    $('cancer-matrix-evidence').addEventListener('click', openCancerEvidence);
  }

  function cancerScatterParams() {
    return {
      cancer: state.cancer.scatterCancer,
      pesticide: state.cancer.scatterPest,
      data_type: state.cancer.scatterDtype,
      exclude_urban: state.cancer.excludeUrban ? '1' : '',
      rural_only: state.cancer.ruralOnly ? '1' : '',
      control_smoking: state.cancer.controlSmoking ? '1' : '',
    };
  }

  async function refreshCancerScatter() {
    const d = await api('/api/correlation/cancer', cancerScatterParams());
    const isCount = (d.x_label || '').includes('(count)');
    const mk = (p) => ({ x: p.x, y: p.y, label: p.county, ur: p.is_urban ? 'Urban' : 'Rural' });
    const urban = d.points.filter((p) => p.is_urban).map(mk);
    const rural = d.points.filter((p) => !p.is_urban).map(mk);
    const fit = d.fit || {};
    const datasets = [
      { label: `Rural counties (${rural.length})`, data: rural,
        backgroundColor: '#3fb950', pointRadius: 6, pointHoverRadius: 9 },
      { label: `Urban counties (${urban.length})`, data: urban,
        backgroundColor: '#58a6ff', pointRadius: 6, pointHoverRadius: 9 },
    ];
    if (d.trend_line && fit.r != null) {
      datasets.push({
        label: 'Overall trend', data: d.trend_line, type: 'line',
        borderColor: 'rgba(240,180,41,.9)', borderWidth: 2,
        backgroundColor: 'transparent', borderDash: [6, 4], pointRadius: 0, fill: false,
      });
    }
    PMCharts.destroyIfExists(state.charts.cancerScatter);
    state.charts.cancerScatter = PMCharts.scatter('chart-cancer-scatter', datasets, {
      xLabel: d.x_label, yLabel: d.y_label,
      xName: d.pesticide_label || 'Pesticide', yName: d.cancer_label || 'Rate',
      xFmt: isCount ? PMCharts.fmtCount : PMCharts.fmtLbs,
      yFmt: PMCharts.fmtNum, yBeginAtZero: false,
    });
    // stats box
    $('cancer-stat-r').textContent   = fit.r != null ? fit.r.toFixed(3) : '—';
    $('cancer-stat-p').textContent   = fit.p_value != null ? fit.p_value.toFixed(3) : '—';
    $('cancer-stat-rho').textContent = d.spearman && d.spearman.rho != null ? d.spearman.rho.toFixed(3) : '—';
    $('cancer-stat-n').textContent   = d.n;
    const qc = d.quartile_comparison || {};
    $('cancer-stat-top').textContent = qc.top_mean != null ? qc.top_mean.toFixed(1) : '—';
    $('cancer-stat-bot').textContent = qc.bottom_mean != null ? qc.bottom_mean.toFixed(1) : '—';
    const sig = $('cancer-stat-sig');
    if (fit.p_value != null) {
      const significant = fit.p_value < 0.05;
      sig.innerHTML = significant
        ? '<span class="sig yes">Statistically significant at p&lt;0.05</span>'
        : '<span class="sig no">Not statistically significant (p≥0.05)</span>';
    } else { sig.textContent = ''; }
    $('cancer-stat-interp').textContent = d.interpretation || '';
    $('cancer-smoking-note').textContent = d.smoking_note || '';
    // deep-dive text
    const dd = $('cancer-deep-dive');
    const isCompound = (state.cancer.scatterPest || '').startsWith('compound:');
    const head = isCompound
      ? `<strong>${d.pesticide_label} application vs ${d.cancer_label}</strong> — `
      : '';
    dd.innerHTML = head + (d.link_note || '');
  }

  function matrixColor(r) {
    if (r == null) return '#20262e';
    const t = Math.max(-1, Math.min(1, r));
    // neutral gray at 0 → blue at -1, red at +1
    const mix = (a, b, k) => Math.round(a + (b - a) * k);
    const neutral = [58, 66, 78];
    const red = [214, 67, 31];
    const blue = [63, 92, 173];
    const k = Math.abs(t);
    const end = t >= 0 ? red : blue;
    return `rgb(${mix(neutral[0], end[0], k)}, ${mix(neutral[1], end[1], k)}, ${mix(neutral[2], end[2], k)})`;
  }

  async function renderCancerMatrix() {
    const d = await api('/api/correlation/cancer/matrix', { data_type: state.cancer.scatterDtype });
    const el = $('cancer-matrix');
    el.innerHTML = '';
    const table = document.createElement('table');
    table.className = 'matrix-table';
    // header row
    const thead = document.createElement('tr');
    thead.innerHTML = '<th class="corner"></th>' +
      d.cancers.map((c) => `<th title="${c.label}">${c.label.replace(/ (Cancer|&.*)$/, '')}</th>`).join('');
    table.appendChild(thead);
    for (const row of d.matrix) {
      const tr = document.createElement('tr');
      const label = document.createElement('th');
      label.className = 'rowlabel';
      label.textContent = row.compound;
      tr.appendChild(label);
      row.cells.forEach((cell, i) => {
        const td = document.createElement('td');
        td.className = 'mcell';
        td.style.background = matrixColor(cell.r);
        const rTxt = cell.r == null ? '·' : cell.r.toFixed(2);
        const ev = cell.evidence
          ? `<span class="ev-dot" title="Evidence: ${cell.evidence.level}${cell.evidence.iarc ? ' · IARC ' + cell.evidence.iarc : ''}">●</span>`
          : '';
        td.innerHTML = `<span class="rval">${rTxt}</span>${ev}`;
        if (cell.r != null && Math.abs(cell.r) > 0.45) td.classList.add('strong');
        const cancerKey = d.cancers[i].key;
        td.title = `${row.compound} × ${d.cancers[i].label}: ` +
          (cell.r == null ? 'no data' : `r=${cell.r.toFixed(2)}, n=${cell.n}`) +
          (cell.evidence ? ` · evidence: ${cell.evidence.level}` : '');
        td.addEventListener('click', () => {
          // load this compound+cancer combo into the scatter
          state.cancer.scatterCancer = cancerKey;
          state.cancer.scatterPest = 'compound:' + row.compound;
          $('cancer-scatter-cancer').value = cancerKey;
          $('cancer-scatter-pest').value = ensurePestOption('compound:' + row.compound);
          refreshCancerScatter(); refreshCancerQuartiles();
        });
        tr.appendChild(td);
      });
      table.appendChild(tr);
    }
    el.appendChild(table);
  }

  async function refreshCancerQuartiles() {
    const d = await api('/api/correlation/cancer/quartiles', {
      cancer: state.cancer.scatterCancer, pesticide: state.cancer.scatterPest,
      data_type: state.cancer.scatterDtype,
      exclude_urban: state.cancer.excludeUrban ? '1' : '',
      rural_only: state.cancer.ruralOnly ? '1' : '',
    });
    const labels = d.bars.map((b) => b.label);
    const vals = d.bars.map((b) => b.mean_rate);
    const cols = d.bars.map((_, i) => CANCER_PALETTE[[1, 4, 6, 9][i]]);
    PMCharts.destroyIfExists(state.charts.cancerQuartiles);
    state.charts.cancerQuartiles = PMCharts.verticalBar(
      'chart-cancer-quartiles', labels, vals, cols,
      `${d.cancer_label} — ${d.units}`);
    $('cancer-quartile-note').textContent =
      `Counties split into quartiles by ${d.pesticide_label} use; bars = mean ` +
      `${d.cancer_label} rate per 100,000. MI average: ${d.mi_rate != null ? d.mi_rate : '—'}.`;
  }

  // Make sure a compound value exists as an <option> in the scatter dropdown.
  function ensurePestOption(val) {
    const sel = $('cancer-scatter-pest');
    if (![...sel.options].some((o) => o.value === val)) {
      const o = document.createElement('option');
      o.value = val;
      o.textContent = val.startsWith('compound:') ? val.split(':')[1] : val;
      sel.appendChild(o);
    }
    return val;
  }

  // ---------- Cancer evidence modal ----------
  let _evidenceRows = null;
  async function openCancerEvidence() {
    if (!_evidenceRows) {
      const d = await api('/api/cancer/evidence');
      _evidenceRows = d.evidence;
    }
    const tbl = $('cancer-evidence-table');
    tbl.innerHTML =
      '<tr><th>Compound</th><th>Cancer</th><th>Evidence</th><th>IARC</th><th>Mechanism</th><th>Key studies</th></tr>';
    for (const e of _evidenceRows) {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><strong>${e.compound}</strong></td>
        <td>${e.cancer_label}</td>
        <td><span class="evidence-pill ev-${(e.evidence_level || '').toLowerCase().replace(/[^a-z]/g, '')}">${e.evidence_level || '—'}</span></td>
        <td>${e.iarc_classification || '—'}</td>
        <td class="small">${e.key_mechanism || ''}</td>
        <td class="small">${e.key_studies || ''}</td>`;
      tbl.appendChild(tr);
    }
    show($('cancer-evidence-modal'));
  }

  // ---------- driver ----------
  async function refreshAll() {
    await Promise.all([refreshChoropleth(), refreshStatewide()]);
    // If the user has the water-quality "match main" checkbox on, the
    // water overlays follow whatever compound the main map is filtered to.
    if (state.water.matchMain) refreshAllWaterLayers();
    // Deep-dive: mirror the main map's compound into the cancer scatter so
    // picking e.g. Glyphosate pre-loads "Glyphosate vs NHL".
    syncCancerDeepDive();
  }

  function syncCancerDeepDive() {
    const want = state.compound ? 'compound:' + state.compound.toUpperCase() : 'all';
    if (want === state.cancer.scatterPest) return;
    state.cancer.scatterPest = want;
    if (!$('view-cancer').classList.contains('hidden')) {
      $('cancer-scatter-pest').value = ensurePestOption(want);
      refreshCancerScatter(); refreshCancerQuartiles();
    }
  }

  // Apply shareable map-state query params (?normalize=&year=&category=&compound=)
  // so a specific map view can be linked or bookmarked. Controls are synced to
  // match. Called after the UI is populated, before the first refresh.
  function applyUrlParams() {
    const p = new URLSearchParams(location.search);
    const norm = p.get('normalize');
    if (norm && ['total', 'per_sq_mile', 'per_acre'].includes(norm)) {
      state.normalize = norm;
      document.querySelectorAll('#seg-normalize button').forEach((b) =>
        b.classList.toggle('active', b.dataset.val === norm));
    }
    const yr = parseInt(p.get('year'), 10);
    if (yr && state.years.includes(yr)) {
      state.year = yr;
      $('year-slider').value = state.years.indexOf(yr);
      $('year-label').textContent = yr;
    }
    const cat = p.get('category');
    const catEl = $('filter-category');
    if (cat && [...catEl.options].some((o) => o.value === cat)) {
      state.category = cat; catEl.value = cat;
    }
    const cmp = p.get('compound');
    const cmpEl = $('filter-compound');
    if (cmp && [...cmpEl.options].some((o) => o.value === cmp)) {
      state.compound = cmp; cmpEl.value = cmp;
    }
    const cty = p.get('county');
    if (cty && /^\d{5}$/.test(cty)) state._pendingCounty = cty;
  }

  async function boot() {
    initMap();
    loading(true);
    try {
      const [meta, geo] = await Promise.all([
        api('/api/meta'),
        fetch('/api/geojson').then((r) => r.json()),
      ]);
      state.meta = meta;
      state.geojson = geo;
      state.years = meta.years;
      state.year = state.years[state.years.length - 1];

      // populate UI
      const sel = $('filter-compound');
      for (const c of meta.compounds) {
        const o = document.createElement('option');
        o.value = c; o.textContent = c;
        sel.appendChild(o);
      }
      buildFeatured();
      populateCancerDropdowns();
      $('year-min').textContent = state.years[0];
      $('year-max').textContent = state.years[state.years.length - 1];
      $('year-slider').max = state.years.length - 1;
      $('year-slider').value = state.years.length - 1;
      $('year-label').textContent = state.year;

      applyUrlParams();

      // Honor a shareable deep link like /#explore as soon as the UI is ready,
      // without waiting for the (slower) map layers to finish loading.
      const initial = (location.hash || '').replace('#', '');
      if (initial && VIEWS.includes(initial) && initial !== 'map') {
        switchView(initial, false);
      }

      renderChoropleth();
      await loadWaterCompounds();
      bindFilters();
      await refreshAll();

      // Shareable deep link to a specific county (?county=26077) opens its panel.
      if (state._pendingCounty) { openCounty(state._pendingCounty); state._pendingCounty = null; }
    } catch (e) {
      console.error(e);
      alert('Failed to load app: ' + e.message +
            '\nRun `python -m app.data_loader` to populate the database.');
    } finally {
      loading(false);
    }
  }

  // ---------- hover tooltips (data-tip / data-gloss) ----------
  // Elements can carry either data-tip="literal text" or
  // data-gloss="glossary term" (resolved to a plain-language definition via
  // PMGloss). Info "?" icons use data-gloss so definitions stay consistent.
  const TIP_SELECTOR = '[data-tip],[data-gloss]';

  function tipText(el) {
    const lit = el.getAttribute('data-tip');
    if (lit) return lit;
    const term = el.getAttribute('data-gloss');
    if (term && window.PMGloss) return window.PMGloss.gloss(term);
    return term || '';
  }

  function setupTooltips() {
    const tip = document.createElement('div');
    tip.className = 'js-tooltip';
    document.body.appendChild(tip);

    let showTimer = null;
    let current = null;

    const positionXY = (cx, cy) => {
      const pad = 12;
      let x = cx + pad;
      let y = cy + pad;
      const r = tip.getBoundingClientRect();
      if (x + r.width + 4 > window.innerWidth) x = cx - r.width - pad;
      if (y + r.height + 4 > window.innerHeight) y = cy - r.height - pad;
      tip.style.left = Math.max(4, x) + 'px';
      tip.style.top = Math.max(4, y) + 'px';
    };
    const position = (e) => positionXY(e.clientX, e.clientY);

    const hide = () => {
      clearTimeout(showTimer);
      current = null;
      tip.classList.remove('show');
    };

    const showFor = (el, cx, cy, delay) => {
      current = el;
      clearTimeout(showTimer);
      showTimer = setTimeout(() => {
        const txt = tipText(el);
        if (!txt) return;
        tip.textContent = txt;
        positionXY(cx, cy);
        tip.classList.add('show');
      }, delay);
    };

    document.addEventListener('mouseover', (e) => {
      const el = e.target.closest(TIP_SELECTOR);
      if (!el || el === current) return;
      showFor(el, e.clientX, e.clientY, 350);
    });

    document.addEventListener('mousemove', (e) => {
      if (current && tip.classList.contains('show')) position(e);
    });

    document.addEventListener('mouseout', (e) => {
      const el = e.target.closest(TIP_SELECTOR);
      if (el && el === current && !el.contains(e.relatedTarget)) hide();
    });

    // Keyboard/touch accessibility for focusable info icons.
    document.addEventListener('focusin', (e) => {
      const el = e.target.closest(TIP_SELECTOR);
      if (!el) return;
      const r = el.getBoundingClientRect();
      showFor(el, r.right, r.bottom, 0);
    });
    document.addEventListener('focusout', (e) => {
      if (e.target.closest(TIP_SELECTOR) === current) hide();
    });
    // Tap an info icon on touch devices to toggle its definition.
    document.addEventListener('click', (e) => {
      const el = e.target.closest('.info-i');
      if (!el) return;
      e.stopPropagation();
      if (current === el && tip.classList.contains('show')) { hide(); return; }
      const r = el.getBoundingClientRect();
      showFor(el, r.right, r.bottom, 0);
    });

    // hide if the underlying element is scrolled away or removed
    window.addEventListener('scroll', hide, true);
  }

  // ---------- mobile bottom-sheet controls ----------
  function setupMobileUI() {
    const body = document.body;
    const closeSheets = () => body.classList.remove('m-layers-open', 'm-detail-open');

    const fab = $('m-layers-fab');
    if (fab) fab.addEventListener('click', () => {
      body.classList.remove('m-detail-open');
      body.classList.add('m-layers-open');
    });
    const layersClose = $('m-layers-close');
    if (layersClose) layersClose.addEventListener('click', () =>
      body.classList.remove('m-layers-open'));
    const backdrop = $('m-backdrop');
    if (backdrop) backdrop.addEventListener('click', closeSheets);

    // "View statewide summary" opens the right-side sheet on the statewide panel.
    const summaryBtn = $('m-summary-btn');
    if (summaryBtn) summaryBtn.addEventListener('click', () => {
      closeCountyPanel();                 // ensure the statewide panel is the one shown
      body.classList.remove('m-layers-open');
      body.classList.add('m-detail-open');
      const p = $('statewide-panel');
      if (p) p.scrollTop = 0;
    });

    // Growing back to desktop width: drop mobile sheet state and re-measure the map.
    let rt = null;
    window.addEventListener('resize', () => {
      clearTimeout(rt);
      rt = setTimeout(() => {
        if (!isMobile()) closeSheets();
        if (state.map) state.map.invalidateSize();
      }, 200);
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    setupTooltips();
    setupMobileUI();
    wireIntro();
    maybeShowIntroOnFirstVisit();
    boot();
  });
})();
