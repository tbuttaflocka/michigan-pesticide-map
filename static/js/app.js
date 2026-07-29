// Main app — Michigan Pesticide Heat Map.
(function () {
  const $ = (id) => document.getElementById(id);

  // Charts are a PROGRESSIVE ENHANCEMENT. If charts.js or the Chart.js CDN fails
  // to load (a flaky network, an ad-blocker, an offline reload), the map,
  // overlays, legends, popups, and the address report must ALL still work — a
  // single failed <script> must never blank the whole app. So we never hard-
  // depend on window.PMCharts: we supply local number formatters (identical to
  // charts.js) plus no-op chart stubs, fill any gaps on the global, and neutralise
  // the chart-drawing functions if the Chart library itself is missing — so every
  // existing PMCharts.* call degrades to a no-op instead of throwing.
  (function ensureCharts() {
    const _fmtLbs = (v) => {
      if (v == null) return '—';
      const n = Number(v);
      if (n >= 1e9) return (n / 1e9).toFixed(2) + ' B lbs';
      if (n >= 1e6) return (n / 1e6).toFixed(2) + ' M lbs';
      if (n >= 1e3) return (n / 1e3).toFixed(1) + ' k lbs';
      return n.toFixed(1) + ' lbs';
    };
    const _fmtCount = (v) => (v == null ? '—' : Number(v).toLocaleString());
    const _fmtNum = (v) => {
      if (v == null) return '—';
      const n = Number(v);
      return (Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(1));
    };
    const _noop = () => null;
    const fallback = {
      fmtKg: _fmtLbs, fmtLbs: _fmtLbs, fmtCount: _fmtCount, fmtNum: _fmtNum,
      horizontalBar: _noop, doughnut: _noop, lineChart: _noop, scatter: _noop,
      verticalBar: _noop, destroyIfExists: _noop,
      CATEGORY_COLORS: { herbicide: '#3fb950', insecticide: '#f85149',
        fungicide: '#58a6ff', growth_regulator: '#bc8cff', other: '#f0b429' },
    };
    const pc = window.PMCharts || {};
    for (const k of Object.keys(fallback)) {
      if (typeof pc[k] === 'undefined') pc[k] = fallback[k];   // fill gaps
    }
    if (typeof window.Chart === 'undefined') {                 // Chart.js missing
      for (const k of ['horizontalBar', 'doughnut', 'lineChart', 'scatter', 'verticalBar']) {
        pc[k] = _noop;
      }
    }
    window.PMCharts = pc;
  })();

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
      filters: { npl: true, state: true, deleted: false },
      markers: null,               // L.featureGroup
      zones: null,                 // L.layerGroup
      density: null,               // L.geoJSON
      densityByFips: new Map(),
    },
    pfas: {
      loaded: false,
      features: [],                // from /api/pfas/features
      legend: null,
      showSites: false,
      filters: { site: true, aoi: true, surface_water: true,
                 pws: false, fish: false, potw: false },
      markers: null,               // L.markerClusterGroup (points)
      polys: null,                 // (legacy) not used since hexbins moved to _polyLayer
      _polyLayer: null,            // single persistent L.geoJSON of PWS hexbins (canvas)
      _canvas: null,               // dedicated L.canvas() renderer for the hexbins
      densityByFips: new Map(),    // county Site+AOI counts (choropleth)
      _densityMax: 1,
    },
    airToxics: {                   // EPA air toxics (NATA) census-tract risk choropleth
      loaded: false,
      tracts: [],                  // from /api/airtoxics/features
      legend: null,
      stats: null,                 // {max, mi_avg, national_avg}
      metric: 'cancer',            // selectable metric (hazard index deferred)
      _max: 1,
      _canvas: null,               // dedicated L.canvas() renderer for the tracts
      _polyLayer: null,            // single persistent L.geoJSON of tract polygons
    },
    ust: {
      legend: null,
      showSites: false,
      // Open leaking releases on by default; closed & licensed are lazy (loaded
      // only when their sub-toggle is switched on — the payload is large).
      filters: { leaking_open: true, leaking_closed: false, licensed: false },
      byCat: {},                   // category -> features[] (lazy-loaded)
      loaded: {},                  // category -> true once fetched
      markers: null,               // L.markerClusterGroup
      densityByFips: new Map(),    // county open-release counts (choropleth)
      _densityMax: 1,
    },
    spraying: {
      loaded: false,
      programs: [],                // from /api/spraying/programs
      types: [],                   // type legend (key/glyph/color/label)
      showMarkers: false,
      markers: null,               // L.markerClusterGroup / layerGroup
    },
    coalAsh: {
      loaded: false,
      sites: [],                   // from /api/coal-ash/sites
      statuses: [],                // status legend (key/color/label)
      unitTypes: [],               // unit-type legend (key/letter/label)
      showMarkers: false,
      markers: null,               // L.markerClusterGroup / layerGroup
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
    landfill: {
      loaded: false,
      sites: [],                   // from /api/landfill/sites
      legend: null,                // category/status legend payload
      showSites: false,
      filters: { msw: true, industrial: true, coal_ash: true, hazardous: true },
      markers: null,               // L.markerClusterGroup / layerGroup
      densityByFips: new Map(),
      _densityMax: 1,
    },
    golf: {
      loaded: false,
      sites: [],                   // from /api/golf/sites
      legend: null,                // ownership legend + sourced turf context
      showSites: false,
      filters: { municipal: true, private: true, unknown: true },
      markers: null,               // L.markerClusterGroup / layerGroup (centroid pins)
      polys: null,                 // L.layerGroup of course footprint polygons
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

  // POST a JSON body. Used for the address report so the address travels in the
  // request body (never a URL/query string) and leaves no shareable link.
  async function apiPost(path, body) {
    const r = await fetch(path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    let data = null;
    try { data = await r.json(); } catch (e) { /* non-JSON error */ }
    return { ok: r.ok, status: r.status, data };
  }

  // HTML-escape for text interpolated into popup/report markup.
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
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

  // Detach a dedicated L.canvas RENDERER from the map. Vector layers that use a
  // private canvas renderer (air toxics, PFAS hexbins) must call this when hidden:
  // removing the vector layer alone leaves the renderer — and thus a blank,
  // full-map <canvas> — sitting in its pane. Because those panes sit above the
  // county overlay pane with pointer-events:auto, the leftover canvas silently
  // intercepts every county click until a full page refresh. Leaflet re-attaches
  // the renderer automatically when the layer is shown again, so this is safe.
  function removeCanvasRenderer(renderer) {
    if (renderer && state.map && state.map.hasLayer(renderer)) renderer.remove();
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
      case 'landfill_density': {
        const c = state.landfill.densityByFips.get(fips);
        const v = c ? c.value : 0;
        if (!v) return NO_DATA;
        const max = state.landfill._densityMax || 1;
        const idx = Math.min(LANDFILL_PALETTE.length - 1,
          Math.floor(Math.sqrt(v / max) * LANDFILL_PALETTE.length));
        return LANDFILL_PALETTE[idx];
      }
      case 'pfas_density': {
        const c = state.pfas.densityByFips.get(fips);
        const v = c ? c.value : 0;
        if (!v) return NO_DATA;
        const max = state.pfas._densityMax || 1;
        const idx = Math.min(PFAS_PALETTE.length - 1,
          Math.floor(Math.sqrt(v / max) * PFAS_PALETTE.length));
        return PFAS_PALETTE[idx];
      }
      case 'ust_density': {
        const c = state.ust.densityByFips.get(fips);
        const v = c ? c.value : 0;
        if (!v) return NO_DATA;
        const max = state.ust._densityMax || 1;
        const idx = Math.min(UST_PALETTE.length - 1,
          Math.floor(Math.sqrt(v / max) * UST_PALETTE.length));
        return UST_PALETTE[idx];
      }
      default: {   // pesticide
        const c = state.countyByFips.get(fips);
        return colorFor(c ? c.value : 0, state.breaks, state.palette);
      }
    }
  }

  // Choropleths that are painted by their OWN polygon layer (not the county base):
  // the county fills must be transparent so that layer reads through.
  function paintsCountiesTransparent(which) {
    return which === 'none' || which === 'air_toxics';
  }

  function styleFor(feature) {
    // "None" (and the tract-level air-toxics layer) = no county fill: transparent
    // so the base map, point overlays, or tract polygons read cleanly.
    if (paintsCountiesTransparent(state.activeChoropleth)) {
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
    if (paintsCountiesTransparent(state.activeChoropleth)) {
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
        const units = (state.resp.meta && state.resp.meta.units) ? ` ${state.resp.meta.units}` : '';
        return (c && c.value != null)
          ? `<div><span class="muted">${state.resp.hoverLabel}:</span> <span class="r-v">${c.value.toFixed(1)}</span><span class="muted">${units}</span>${base}</div>`
          : '<div class="muted">No data</div>';
      }
      case 'cancer': {
        const c = state.cancer.byFips.get(fips);
        const base = (state.cancer.meta && state.cancer.meta.is_baseline) ? ' · MI baseline' : '';
        const units = (state.cancer.meta && state.cancer.meta.units) ? ` ${state.cancer.meta.units}` : ' per 100,000';
        if (c && c.value != null) {
          return `<div><span class="muted">${state.cancer.hoverLabel}:</span> <span class="v">${c.value.toFixed(1)}</span><span class="muted">${units}</span>${base}</div>`;
        }
        return `<div class="muted">${c && c.suppressed ? 'Suppressed (&lt;16 cases)' : 'No data'}</div>`;
      }
      case 'contam_density': {
        const c = state.contam.densityByFips.get(fips);
        return (c && c.value)
          ? `<div><span class="muted">Contamination sites in county:</span> <span class="v">${c.value}</span></div>`
          : '<div class="muted">No mapped sites</div>';
      }
      case 'tri': {
        const c = state.tri.densityByFips.get(fips);
        if (!c || !c.value) return '<div class="muted">No TRI releases reported</div>';
        return `<div><span class="muted">${triMetricLabel(state.tri.metric)}:</span> <span class="v">${fmtLbs(c.value)}</span><span class="muted">/yr</span></div>
             <div><span class="muted">TRI facilities:</span> <span class="v">${c.facilities || 0}</span></div>`;
      }
      case 'landfill_density': {
        const c = state.landfill.densityByFips.get(fips);
        if (!c || !c.value) return '<div class="muted">No mapped landfills</div>';
        const haz = c.hazardous ? ` <span class="muted">(${c.hazardous} hazardous)</span>` : '';
        return `<div><span class="muted">Landfills &amp; waste facilities:</span> <span class="v">${c.value}</span>${haz}</div>`;
      }
      case 'pfas_density': {
        const c = state.pfas.densityByFips.get(fips);
        if (!c || !c.value) return '<div class="muted">No mapped PFAS sites</div>';
        const aoi = c.aois ? ` <span class="muted">(${c.aois} area${c.aois > 1 ? 's' : ''} of interest)</span>` : '';
        return `<div><span class="muted">PFAS sites &amp; AOIs:</span> <span class="v">${c.value}</span>${aoi}</div>`;
      }
      case 'ust_density': {
        const c = state.ust.densityByFips.get(fips);
        if (!c || !c.value) return '<div class="muted">No open leaking releases</div>';
        const s = c.open_sites ? ` <span class="muted">(${c.open_sites} site${c.open_sites > 1 ? 's' : ''})</span>` : '';
        return `<div><span class="muted">Open leaking UST releases:</span> <span class="v">${c.value}</span>${s}</div>`;
      }
      default: {   // pesticide
        const c = state.countyByFips.get(fips);
        if (!c) return '<div class="muted">No pesticide data</div>';
        const compounds = `<div><span class="muted">Compounds applied:</span> <span class="v">${c.compound_count}</span></div>`;
        if (state.normalize === 'per_sq_mile') {
          return `<div><span class="muted">Pesticide applied:</span> <span class="v">${fmtLbs(c.value)}/mi²</span></div>
             <div><span class="muted">Total applied:</span> <span class="v">${fmtLbs(c.total_lbs)}</span></div>
             ${compounds}`;
        }
        if (state.normalize === 'per_acre') {
          const acreLine = c.cropland_acres
            ? `<div><span class="muted">Cropland:</span> <span class="v">${Math.round(c.cropland_acres).toLocaleString()} ac</span></div>` : '';
          return `<div><span class="muted">Pesticide intensity:</span> <span class="v">${fmtLbs(c.value)}/acre</span></div>
             <div><span class="muted">Total applied:</span> <span class="v">${fmtLbs(c.total_lbs)}</span></div>
             ${acreLine}
             ${compounds}`;
        }
        return `<div><span class="muted">Pesticide applied:</span> <span class="v">${fmtLbs(c.value)}</span></div>
             ${compounds}`;
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
      case 'landfill_density': return 'Landfill density';
      case 'pfas_density': return 'PFAS site density';
      case 'ust_density': return 'Open leaking storage-tank releases';
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
      case 'landfill_density':
        paletteStrip(el, LANDFILL_PALETTE);
        note.textContent = 'active landfills & waste facilities per county (lower → higher)';
        break;
      case 'pfas_density':
        paletteStrip(el, PFAS_PALETTE);
        note.textContent = 'PFAS sites & areas of interest per county (lower → higher)';
        break;
      case 'ust_density':
        paletteStrip(el, UST_PALETTE);
        note.textContent = 'open leaking storage-tank releases per county (lower → higher)';
        break;
      case 'air_toxics': {
        const pal = (state.airToxics.legend && state.airToxics.legend.palette) || [];
        if (pal.length) paletteStrip(el, pal);
        note.textContent = 'modeled air toxics cancer risk per census tract, in a million '
          + '(lower → higher) · SCREENING estimate, not measured air';
        break;
      }
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
    { on: () => state.spraying.showMarkers,  c: '#5dbb63', t: 'Spraying programs (directory)' },
    { on: () => state.coalAsh.showMarkers,   c: '#e3a008', t: 'Coal ash sites (color = closure status; ⚠ = unlined)' },
    { on: () => state.tri.showSites,         c: '#d9772f', t: 'TRI facilities (size/red = more released)' },
    { on: () => state.landfill.showSites,    c: '#d96b35', t: 'Landfills & waste facilities (by type)' },
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
    // Water-site severity key — makes the two DISTINCT standards explicit so
    // the violet aquatic-life color is never read as a red drinking-water one.
    if (state.water.showSites) {
      html += '<div class="mk-title" style="margin-top:8px">Water sites</div>' +
        `<div class="mk"><span class="mk-dot" style="background:${WQ_COLOR.exceeds_mcl}"></span>exceeds drinking-water MCL (human)</div>` +
        `<div class="mk"><span class="mk-dot" style="background:${WQ_COLOR.exceeds_benchmark}"></span>exceeds aquatic-life benchmark (ecological)</div>` +
        `<div class="mk"><span class="mk-dot" style="background:${WQ_COLOR.detected}"></span>detected, within limits</div>` +
        `<div class="mk"><span class="mk-dot" style="background:${WQ_COLOR.tested_no_detect}"></span>tested, none detected</div>`;
    }
    // Landfill type/status key — markers are colored by facility type.
    if (state.landfill.showSites && state.landfill.legend) {
      html += '<div class="mk-title" style="margin-top:8px">Landfills · by type</div>' +
        state.landfill.legend.categories.map((t) =>
          `<div class="mk"><span class="mk-dot" style="background:${t.color}"></span>${t.glyph} ${t.label}</div>`
        ).join('');
    }
    // Golf-course ownership key — pins/footprints are colored by ownership,
    // which is what determines records access (public = FOIA-able).
    if (state.golf.showSites && state.golf.legend) {
      html += '<div class="mk-title" style="margin-top:8px">Golf courses · ownership</div>' +
        state.golf.legend.ownership.map((o) =>
          `<div class="mk"><span class="mk-dot" style="background:${o.color}"></span>${o.glyph} ${o.label}</div>`
        ).join('') +
        '<div class="mk mk-sub">Footprint = land under turf management · locations only, no pesticide amounts</div>';
    }
    // PFAS key — confirmed Sites vs Areas of Interest and the sampling kinds.
    if (state.pfas.showSites && state.pfas.legend) {
      html += '<div class="mk-title" style="margin-top:8px">PFAS · MPART</div>' +
        state.pfas.legend.kinds.filter((k) => state.pfas.filters[k.key] !== false).map((k) =>
          `<div class="mk"><span class="mk-dot" style="background:${k.color}"></span>${k.glyph} ${k.label}</div>`
        ).join('') +
        '<div class="mk mk-sub">AOI = area under investigation · public water shown as hexbin areas</div>';
    }
    // UST key — open leaking (prominent) vs closed vs licensed (muted).
    if (state.ust.showSites && state.ust.legend) {
      html += '<div class="mk-title" style="margin-top:8px">Storage tanks · EGLE</div>' +
        state.ust.legend.categories.filter((c) => state.ust.filters[c.key] !== false).map((c) =>
          `<div class="mk"><span class="mk-dot" style="background:${c.color}"></span>${c.glyph} ${c.short}</div>`
        ).join('') +
        '<div class="mk mk-sub">Part 213 leaking ≠ Part 211 licensed · locations vary in accuracy</div>';
    }
    // Spraying-programs type key — the markers are colored by program type.
    if (state.spraying.showMarkers && state.spraying.types.length) {
      html += '<div class="mk-title" style="margin-top:8px">Spraying programs · by type</div>' +
        state.spraying.types.map((t) =>
          `<div class="mk"><span class="mk-dot" style="background:${t.color}"></span>${t.glyph} ${t.label}</div>`
        ).join('');
    }
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
    updateMapHint();          // the "press & hold" hint names the active layer
  }

  // Short plain-language phrase for what long-pressing a county reveals, keyed
  // to the active choropleth (used in the mobile map hint). null = coloring off.
  function layerPeekLabel() {
    switch (state.activeChoropleth) {
      case 'none':           return null;
      case 'resp':           return 'respiratory rates';
      case 'cancer':         return 'cancer rates';
      case 'contam_density': return 'contamination-site counts';
      case 'tri':            return 'toxic-release amounts';
      case 'landfill_density': return 'landfill counts';
      case 'pfas_density':   return 'PFAS site counts';
      case 'ust_density':    return 'open leaking-tank counts';
      case 'air_toxics':     return null;   // tract-level; not a county peek
      default:               return 'pesticide amounts';
    }
  }

  // Fill the mobile "how to use the map" hint, referencing the active layer so
  // it always tells the user exactly what press-and-hold will show them.
  function updateMapHint() {
    const el = $('map-hint-text');
    if (!el) return;
    const peek = layerPeekLabel();
    el.innerHTML = peek
      ? `👆 <b>Tap</b> a county for full details · ✋ <b>press &amp; hold</b> to see its <b>${peek}</b>`
      : `👆 <b>Tap</b> a county for full details · turn on county coloring, then <b>press &amp; hold</b> to compare values`;
  }

  // Show only the filter panel(s) that belong to the active choropleth. Panels
  // tag themselves with data-layer-filters="pesticide|resp|cancer|contam_density|tri"
  // (space-separated for multiple). The point-overlay section and universal
  // controls (Legend, Water contamination) have no such tag and stay visible,
  // so stackable overlays remain toggleable regardless of the active layer.
  function applyLayerFilterVisibility() {
    const active = state.activeChoropleth;
    document.querySelectorAll('[data-layer-filters]').forEach((el) => {
      const owns = el.getAttribute('data-layer-filters').split(/\s+/).includes(active);
      el.classList.toggle('hidden', !owns);
    });
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
      if (which === 'landfill_density') await loadLandfillDensity();
      if (which === 'pfas_density') await loadPfasDensity();
      if (which === 'ust_density') await loadUstDensity();
      // Air toxics is a tract-level canvas layer (not county coloring): lazy-load
      // + show it when selected, and detach it whenever another choropleth is.
      if (which === 'air_toxics') { await loadAirToxics(); showAirToxicsLayer(); }
      else hideAirToxicsLayer();
    } catch (e) {
      console.error(e);
    } finally {
      loading(false);
    }

    if (state.geoLayer) state.geoLayer.setStyle(styleFor);
    restyleSelection();   // setStyle wiped the selection border — re-apply it
    renderLegend();
    updateActiveIndicator();
    refreshCountyHeadline();   // keep an open county's headline in sync
    applyLayerFilterVisibility();

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
      refreshCountyHeadline();   // pesticide filter changed → refresh headline
    } catch (e) {
      console.error(e);
    } finally {
      loading(false);
    }
  }

  // ---------- Water-quality overlay ----------
  // Red is reserved for human drinking-water (MCL) violations. Aquatic-life
  // benchmark exceedances get a distinct violet so an ecological exceedance is
  // never mistaken for a drinking-water violation.
  const WQ_COLOR = {
    exceeds_mcl:       '#f85149',   // above human drinking-water limit (MCL)
    exceeds_benchmark: '#bc8cff',   // above aquatic-life benchmark (ecological)
    detected:          '#f0b429',
    tested_no_detect:  '#3fb950',
    no_data:           '#6e7681',
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
    let detected = 0, exceeds = 0, benchmark = 0, tested = 0;
    for (const s of data.sites) {
      if (s.latitude == null || s.longitude == null) continue;
      if (compound && s.detections === 0) continue;   // filter-mode hides non-detect sites
      const radius = s.exceedances > 0 ? 8
        : (s.benchmark_exceedances > 0 ? 7 : (s.detections > 0 ? 6 : 4));
      const m = L.circleMarker([s.latitude, s.longitude], {
        pane: 'water',                 // render above the choropleth so clicks land
        radius,
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
      else if (s.severity === 'exceeds_benchmark') benchmark++;
      else if (s.severity === 'detected') detected++;
      else if (s.severity === 'tested_no_detect') tested++;
    }
    grp.addTo(state.map);
    state.water.sitesLayer = grp;
    const lbl = compound ? `${compound} only` : 'all pesticides';
    $('wq-stats').textContent =
      `${exceeds} exceed drinking-water MCL · ${benchmark} exceed aquatic-life benchmark · `
      + `${detected} detected · ${tested} clean (${lbl})`;
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
            <th class="right" data-tip="How many water samples were tested for this chemical.">Samp.</th>
            <th class="right" data-tip="How many of those samples actually contained the chemical (above the detection limit).">Det.</th>
            <th class="right wq-mcl-h" data-tip="Samples above the EPA legal human drinking-water limit (MCL).">MCL&nbsp;✗</th>
            <th class="right wq-bench-h" data-gloss="aquatic-life benchmark" data-tip="Samples above the USGS/EPA aquatic-life benchmark — a threshold for ecological harm to fish and aquatic insects, not a drinking-water limit.">Aq.&nbsp;life&nbsp;✗</th></tr>
          ${rows.map((r) => {
            const cls = r.exceedances ? 'exceeds' : (r.benchmark_exceedances ? 'exceeds-bench' : (r.detections ? 'detected' : ''));
            const lim = [];
            if (r.mcl) lim.push(`<span class="wq-meta" data-gloss="MCL">MCL ${r.mcl}</span>`);
            if (r.benchmark) lim.push(`<span class="wq-meta wq-bench" data-gloss="aquatic-life benchmark">aq-life ${r.benchmark}</span>`);
            return `
            <tr class="${cls}">
              <td>${chemLink(r.compound, { site: site.site_id, fips: site.county_fips })}${lim.length ? ` <span class="wq-lims">(${lim.join(' · ')} µg/L)</span>` : ''}</td>
              <td class="right">${r.samples}</td>
              <td class="right">${r.detections}</td>
              <td class="right wq-mcl-c">${r.exceedances || '·'}</td>
              <td class="right wq-bench-c">${r.benchmark_exceedances || '·'}</td>
            </tr>`;
          }).join('')}
        </table>
        <div class="wq-meta wq-legend"><span class="dot mcl"></span>MCL = human drinking-water limit ·
          <span class="dot bench"></span>aquatic-life = ecological (fish/insects), often far lower</div>
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
      // Charts are a progressive enhancement — if the Chart.js library failed to
      // load, skip drawing rather than throwing (the data tables still render).
      if (typeof Chart === 'undefined') return;
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
        `<span>${chemLink(r.compound)} <span class="muted small">${r.category}</span></span>` +
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
        `<span class="cl-name">${chemLink(r.compound, { fips: state.selectedFips })}</span>` +
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

  // The two "big stat" cards at the top of the county panel reflect whatever
  // layer is currently coloring the map, each clearly labeled with what it is
  // and its units — never a bare number. `data` is the pesticide county payload.
  function renderCountyHeadline(fips, data) {
    const v1 = $('county-total'),   l1 = $('county-total-label');
    const v2 = $('county-density'), l2 = $('county-density-label');
    const card2 = $('county-stat-2');
    const showCard2 = (on) => { if (card2) card2.style.display = on ? '' : 'none'; };
    switch (state.activeChoropleth) {
      case 'resp': {
        const c = state.resp.byFips.get(fips);
        const units = (state.resp.meta && state.resp.meta.units) || 'rate';
        v1.textContent = (c && c.value != null) ? c.value.toFixed(1) : '—';
        l1.textContent = `${state.resp.hoverLabel || 'Respiratory'} (${units})`;
        showCard2(false);
        break;
      }
      case 'cancer': {
        const c = state.cancer.byFips.get(fips);
        const units = (state.cancer.meta && state.cancer.meta.units) || 'per 100,000';
        v1.textContent = (c && c.value != null) ? c.value.toFixed(1)
          : (c && c.suppressed ? 'N/A' : '—');
        l1.textContent = `${cancerTypeLabel(state.cancer.type)} · ${state.cancer.dataType} (${units})`;
        showCard2(false);
        break;
      }
      case 'contam_density': {
        const c = state.contam.densityByFips.get(fips);
        v1.textContent = (c && c.value) ? String(c.value) : '0';
        l1.textContent = 'Known contamination sites';
        showCard2(false);
        break;
      }
      case 'pfas_density': {
        const c = state.pfas.densityByFips.get(fips);
        v1.textContent = (c && c.value) ? String(c.value) : '0';
        l1.textContent = 'PFAS sites & areas of interest';
        v2.textContent = (c && c.aois) ? String(c.aois) : '0';
        l2.textContent = 'Areas of interest';
        showCard2(true);
        break;
      }
      case 'ust_density': {
        const c = state.ust.densityByFips.get(fips);
        v1.textContent = (c && c.value) ? String(c.value) : '0';
        l1.textContent = 'Open leaking UST releases';
        v2.textContent = (c && c.open_sites) ? String(c.open_sites) : '0';
        l2.textContent = 'Sites with an open release';
        showCard2(true);
        break;
      }
      case 'tri': {
        const c = state.tri.densityByFips.get(fips);
        v1.textContent = (c && c.value) ? fmtLbs(c.value) + '/yr' : '—';
        l1.textContent = `Industrial toxic releases · ${triMetricLabel(state.tri.metric).toLowerCase()} (TRI)`;
        v2.textContent = (c && c.facilities) ? String(c.facilities) : '0';
        l2.textContent = 'TRI facilities';
        showCard2(true);
        break;
      }
      default: {   // pesticide (also when coloring is off)
        v1.textContent = fmtLbs(data.total_lbs);
        l1.textContent = 'Pesticide applied (total)';
        v2.textContent = data.lbs_per_sq_mile != null ? fmtLbs(data.lbs_per_sq_mile) + '/mi²' : '—';
        l2.textContent = 'Pesticide per square mile';
        showCard2(true);
        break;
      }
    }
  }

  // Re-render the headline in place if a county panel is already open (e.g. the
  // user switched the active layer while viewing a county).
  function refreshCountyHeadline() {
    if (!state.selectedFips || !state._countyData) return;
    const panel = $('county-panel');
    if (!panel || panel.classList.contains('hidden')) return;
    renderCountyHeadline(state.selectedFips, state._countyData);
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
    state._countyData = data;
    renderCountyHeadline(fips, data);
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
    // Landfills & waste facilities rollup
    renderCountyLandfills(data.landfills);
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
    // PFAS now has its own dedicated first-class layer (see the PFAS overlay), so
    // this overlay no longer carries a PFAS sub-filter — that avoids duplicate
    // PFAS markers from two sources. Genuine Superfund/state PFAS sites still show
    // here under their NPL/state status and are cross-linked from the PFAS layer.
    const f = state.contam.filters;
    const st = s.status_class;
    return (f.npl && (st === 'npl' || st === 'proposed')) ||
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

  // ---------- Landfills & waste facilities overlay ----------
  // Michigan EGLE Part 115 solid-waste landfills + disposal-capable Part 111
  // hazardous-waste facilities. Markers colored by facility type; popups carry
  // regulatory status, what monitoring is REQUIRED (results are FOIA-only), and
  // cross-links to the app's TRI + Superfund records when the same facility
  // appears there. Earthy brown→tan density scale (unused by any other layer).
  const LANDFILL_PALETTE = ['#2b2118', '#3d2e1c', '#523c20', '#6b4f24', '#876428',
                            '#a67d2c', '#c39a3a', '#d9b458', '#ead089', '#f3e4b8'];
  const LANDFILL_GLYPH = {
    msw: '\u{1F5D1}', industrial: '\u{1F3ED}', cnd: '\u{1F9F1}',
    coal_ash: '⚫', hazardous: '☣',
  };

  function landfillPane() {
    if (!state.map.getPane('landfill')) {
      // Above TRI (640), below contamination (650) + spraying (655).
      state.map.createPane('landfill').style.zIndex = 645;
    }
    return 'landfill';
  }

  function newLandfillClusterLayer() {
    if (typeof L.markerClusterGroup === 'function') {
      return L.markerClusterGroup({
        clusterPane: 'landfill', maxClusterRadius: 46, chunkedLoading: true,
        showCoverageOnHover: false, spiderfyOnMaxZoom: true,
        removeOutsideVisibleBounds: true,
      });
    }
    return L.layerGroup();   // graceful fallback if the cluster plugin didn't load
  }

  async function loadLandfills() {
    if (state.landfill.loaded) return;
    const d = await api('/api/landfill/sites');
    state.landfill.sites = d.sites || [];
    state.landfill.legend = d.legend || null;
    state.landfill.foiaAgency = (d.legend && d.legend.foia_agency) || null;
    state.landfill.loaded = true;
  }

  async function loadLandfillDensity() {
    if (!state.landfill.densityByFips.size) {
      const d = await api('/api/landfill/density');
      for (const c of d.counties) state.landfill.densityByFips.set(c.fips, c);
      state.landfill._densityMax = (d.stats && d.stats.max) || 1;
    }
  }

  // Per-county PFAS Site + Area-of-Interest count for the PFAS choropleth.
  async function loadPfasDensity() {
    if (!state.pfas.densityByFips.size) {
      const d = await api('/api/pfas/density');
      for (const c of d.counties) state.pfas.densityByFips.set(c.fips, c);
      state.pfas._densityMax = (d.stats && d.stats.max) || 1;
      const el = $('pfas-density-stats');
      if (el && d.stats) {
        el.textContent = `${d.stats.total_sites} PFAS sites & areas of interest across `
          + `${d.stats.counties_with_sites} of 83 counties.`;
      }
    }
  }

  // Per-county open leaking-release count for the UST choropleth (Wayne leads).
  async function loadUstDensity() {
    if (!state.ust.densityByFips.size) {
      const d = await api('/api/ust/density');
      for (const c of d.counties) state.ust.densityByFips.set(c.fips, c);
      state.ust._densityMax = (d.stats && d.stats.max) || 1;
      const el = $('ust-density-stats');
      if (el && d.stats) {
        el.textContent = `${d.stats.total_sites.toLocaleString()} open leaking releases across `
          + `${d.stats.counties_with_sites} counties (Wayne alone has the most).`;
      }
    }
  }

  function landfillVisible(s) { return state.landfill.filters[s.category] !== false; }
  function landfillSize(s) { return s.category === 'hazardous' ? 30 : 26; }

  function renderLandfillMarkers() {
    if (state.landfill.markers) { state.landfill.markers.remove(); state.landfill.markers = null; }
    if (!state.landfill.showSites) { updateLandfillStats(); renderMarkerKeys(); return; }
    const pane = landfillPane();
    const grp = newLandfillClusterLayer();
    for (const s of state.landfill.sites) {
      if (s.lat == null || s.lng == null || !landfillVisible(s)) continue;
      const size = landfillSize(s);
      // Closed / post-closure facilities (if EGLE ever publishes them) render
      // desaturated with a dashed ring so they read as distinct from active ones.
      const closed = (s.status_class && s.status_class !== 'active') ? ' closed' : '';
      const m = L.marker([s.lat, s.lng], {
        pane,
        icon: L.divIcon({
          className: 'landfill-divicon',
          html: `<div class="landfill-marker${closed}" style="width:${size}px;height:${size}px;background:${s.color}"><span>${s.glyph}</span></div>`,
          iconSize: [size, size], iconAnchor: [size / 2, size / 2],
        }),
      });
      m.bindPopup(landfillPopupHtml(s), { maxWidth: 340, className: 'landfill-popup-wrap' });
      grp.addLayer(m);
    }
    grp.addTo(state.map);
    state.landfill.markers = grp;
    updateLandfillStats();
    renderMarkerKeys();
  }

  function landfillPopupHtml(s) {
    const addr = [s.address, s.city].filter(Boolean).join(', ');
    const loc = addr ? `${addr}${s.county ? ', ' + s.county + ' Co.' : ''}`
                     : (s.county ? s.county + ' County' : '');
    const types = (s.facility_types || []).length > 1
      ? `<ul class="lf-types">${s.facility_types.map((t) => `<li>${t}</li>`).join('')}</ul>` : '';
    const fed = s.federal_regulated ? ' · federally regulated' : '';
    const comm = s.commercial ? ' · accepts offsite waste' : '';
    const lic = s.license_id ? ` <span class="muted small">License ${s.license_id}</span>` : '';

    // Cross-links to the app's own TRI / Superfund records (matched at load time).
    let xlinks = '';
    if (s.tri_total_lbs != null) {
      xlinks += `<button type="button" class="lf-xlink tri" data-lf-focus="tri" data-id="${s.tri_facility_id || ''}" data-lat="${s.lat}" data-lng="${s.lng}">🏭 Also reports to TRI — <b>${fmtLbs(s.tri_total_lbs)}</b> released${s.tri_year ? ` (${s.tri_year})` : ''} · show on map →</button>`;
    }
    if (s.contam_site_key) {
      xlinks += `<button type="button" class="lf-xlink contam" data-lf-focus="contam" data-lat="${s.lat}" data-lng="${s.lng}">☣ Also a contaminated / Superfund site${s.contam_status ? ` — ${s.contam_status}` : ''} · show on map →</button>`;
    }
    const egle = s.egle_url
      ? `<a href="${s.egle_url}" target="_blank" rel="noopener">EGLE facility record →</a>` : '';

    return `<div class="landfill-popup">
      <div class="lf-type" style="background:${s.color}">${s.glyph} ${s.category_label}</div>
      ${s.operator && s.operator !== s.name ? `<div class="lf-operator">${s.operator}</div>` : ''}
      <h4>${s.name}</h4>
      ${s.type_label ? `<div class="lf-meta">${s.type_label}</div>` : ''}
      ${loc ? `<div class="lf-meta">${loc}</div>` : ''}
      <div class="lf-status"><span class="lf-badge" style="background:${s.status_color}">${s.status_display}</span>${lic}${fed}${comm}</div>
      ${types}
      ${xlinks ? `<div class="lf-xlinks">${xlinks}</div>` : ''}
      <div class="lf-monitor"><span class="k">Monitoring required:</span> ${s.monitoring}</div>
      <div class="lf-foia">
        <p class="lf-foia-note">Monitoring <em>results</em> (groundwater, air, leachate) aren't published online — but you can request them.</p>
        <button type="button" class="lf-foia-btn" data-lf-foia="${s.site_key}">📄 Request monitoring records (FOIA)</button>
      </div>
      ${egle ? `<div class="lf-links">${egle}</div>` : ''}
      <div class="lf-note">Facility data: Michigan EGLE Materials Management (Part 115 / Part 111). Capacity &amp; monitoring results are not in the public feed.</div>
    </div>`;
  }

  function updateLandfillStats() {
    const el = $('landfill-stats');
    if (!el) return;
    if (!state.landfill.loaded) { el.textContent = '—'; return; }
    const vis = state.landfill.sites.filter(landfillVisible);
    const haz = vis.filter((s) => s.category === 'hazardous').length;
    el.textContent = `${vis.length} active facilities · ${haz} hazardous-waste · click a marker for detail`;
  }

  function renderCountyLandfills(c) {
    const el = $('county-landfill-list');
    const count = $('county-landfill-count');
    if (!el) return;
    if (!c || !c.total) {
      if (count) count.textContent = '· none active';
      el.innerHTML = '<p class="muted small">No active licensed landfills or disposal facilities mapped in this county. Closed / pre-regulation sites may appear under <em>Industrial contamination</em> above.</p>';
      return;
    }
    if (count) count.textContent = `· ${c.total} facilit${c.total > 1 ? 'ies' : 'y'}${c.hazardous ? `, ${c.hazardous} hazardous` : ''}`;
    el.innerHTML = c.sites.map((s) => {
      const g = LANDFILL_GLYPH[s.category] || '\u{1F5D1}';
      const tri = s.tri_total_lbs != null ? ` · TRI ${fmtLbs(s.tri_total_lbs)}` : '';
      return `<div class="landfill-li ${s.category}"><span class="g">${g}</span>
        <span class="n">${s.name}${s.operator && s.operator !== s.name ? `<span class="muted small"> — ${s.operator}</span>` : ''}</span>
        <span class="s">${s.type_label || s.category}${tri}</span></div>`;
    }).join('');
  }

  // ---------- Golf courses overlay (OpenStreetMap) ----------
  // Golf courses are a pesticide-intensive turf land use that the USGS EPest
  // agricultural layer excludes entirely. This overlay maps WHERE that use
  // happens; it NEVER shows or estimates per-course pesticide amounts, because
  // Michigan publishes none (the popup's disclosure section explains why). The
  // footprint polygon shows the land area under turf management; the popup
  // carries the sourced turf-chemical list, the cited intensity comparison, and
  // the records-access gap. See app/golf_data.py + app/golf_content.py.
  function golfPane() {
    if (!state.map.getPane('golf')) {
      state.map.createPane('golf').style.zIndex = 646;   // ~ landfill markers
    }
    return 'golf';
  }
  function golfPolyPane() {
    if (!state.map.getPane('golfpoly')) {
      // Above the county choropleth/overlay panes, below the marker pins.
      state.map.createPane('golfpoly').style.zIndex = 415;
    }
    return 'golfpoly';
  }
  function newGolfClusterLayer() {
    if (typeof L.markerClusterGroup === 'function') {
      return L.markerClusterGroup({
        clusterPane: 'golf', maxClusterRadius: 48, chunkedLoading: true,
        showCoverageOnHover: false, spiderfyOnMaxZoom: true,
        removeOutsideVisibleBounds: true,
      });
    }
    return L.layerGroup();   // graceful fallback if the cluster plugin didn't load
  }
  async function loadGolf() {
    if (state.golf.loaded) return;
    const d = await api('/api/golf/sites');
    state.golf.sites = d.sites || [];
    state.golf.legend = d.legend || null;
    state.golf._shared = null;   // rebuilt from the fresh legend on first popup
    state.golf.loaded = true;
  }
  function golfVisible(s) { return state.golf.filters[s.ownership_class] !== false; }
  function golfStyle(s) {
    const c = s.color || '#8b98a5';
    return { color: c, weight: 1.4, opacity: 0.9, fillColor: c,
             fillOpacity: 0.22, pane: golfPolyPane() };
  }

  function renderGolfCourses() {
    if (state.golf.markers) { state.golf.markers.remove(); state.golf.markers = null; }
    if (state.golf.polys) { state.golf.polys.remove(); state.golf.polys = null; }
    if (!state.golf.showSites) { updateGolfStats(); renderMarkerKeys(); return; }
    const pane = golfPane();
    const grp = newGolfClusterLayer();
    const polys = L.layerGroup();
    for (const s of state.golf.sites) {
      if (s.lat == null || s.lng == null || !golfVisible(s)) continue;
      const html = golfPopupHtml(s);
      // Footprint polygon (the whole point — it shows the land area under turf
      // management). Clicking it opens the same popup as the pin.
      if (s.geometry) {
        const gj = L.geoJSON(s.geometry, { style: () => golfStyle(s) });
        gj.bindPopup(html, { maxWidth: 340, className: 'golf-popup-wrap' });
        polys.addLayer(gj);
      }
      // Centroid pin — discoverable and clusterable at every zoom (fallback when
      // a course has no polygon, and a click target when the footprint is tiny).
      const m = L.marker([s.lat, s.lng], {
        pane,
        icon: L.divIcon({
          className: 'golf-divicon',
          html: `<div class="golf-marker" style="background:${s.color}"><span>${s.glyph}</span></div>`,
          iconSize: [24, 24], iconAnchor: [12, 12],
        }),
      });
      m.bindPopup(html, { maxWidth: 340, className: 'golf-popup-wrap' });
      grp.addLayer(m);
    }
    polys.addTo(state.map);
    grp.addTo(state.map);
    state.golf.polys = polys;
    state.golf.markers = grp;
    updateGolfStats();
    renderMarkerKeys();
  }

  function updateGolfStats() {
    const el = $('golf-stats');
    if (!el) return;
    if (!state.golf.loaded) { el.textContent = '—'; return; }
    const vis = state.golf.sites.filter(golfVisible);
    const muni = vis.filter((s) => s.ownership_class === 'municipal').length;
    el.textContent = `${vis.length} golf courses · ${muni} public/municipal · `
      + 'locations only — Michigan publishes no per-course pesticide amounts';
  }

  // The turf-chemical list + intensity comparison are identical for every course
  // (they're general turf-management facts, not course records), so build that
  // fragment once and reuse it in every popup.
  function golfChem(n) {
    // Show the full label; query PubChem on the clean name (drop parentheticals
    // like "Mecoprop (MCPP)" -> "Mecoprop", "PCNB (quintozene)" -> "PCNB").
    return chemLink(String(n).split(' (')[0].trim(), { label: n });
  }
  function golfSharedHtml() {
    if (state.golf._shared) return state.golf._shared;
    const lg = state.golf.legend || {};
    const chem = lg.turf_chemicals || [];
    const intensity = lg.intensity || {};
    const chemBlocks = chem.map((cat) =>
      `<div class="golf-chem-cat"><span class="cc">${cat.category}</span>`
      + `<div class="golf-chem-note muted small">${cat.note || ''}</div>`
      + `<div class="golf-chem-list">${(cat.chemicals || []).map(golfChem).join(', ')}</div>`
      + `</div>`).join('');
    const iSrc = intensity.source_url
      ? `<a href="${intensity.source_url}" target="_blank" rel="noopener">${intensity.source || 'source'}</a>`
      : (intensity.source || '');
    state.golf._shared =
      `<div class="golf-sec">
         <div class="golf-h">What's typically applied to golf-course turf</div>
         <p class="golf-note muted small">Chemicals commonly used in turfgrass management
           <strong>generally</strong> — <strong>not</strong> a record of what this course
           applies (no such record is public in Michigan). Tap any chemical for details.</p>
         ${chemBlocks}
       </div>
       <div class="golf-sec golf-intensity">
         <div class="golf-h">How intensive is golf-turf pesticide use?</div>
         <p>${intensity.headline || ''}</p>
         <p class="muted small">${intensity.basis_note || ''} ${intensity.regional_note || ''}</p>
         <p class="golf-cite small">Source: ${iSrc}</p>
       </div>`;
    return state.golf._shared;
  }

  function golfPopupHtml(s) {
    const lg = state.golf.legend || {};
    const disc = lg.disclosure || {};
    const loc = [s.city, s.county ? s.county + ' Co.' : ''].filter(Boolean).join(', ');
    const acres = s.acres ? `${Math.round(s.acres).toLocaleString()} acres` : '';
    const meta = [s.ownership_legend, loc, acres].filter(Boolean).join(' · ');
    const isMuni = s.ownership_class === 'municipal';

    // Disclosure gap — the substantive content. Municipal guidance is made
    // prominent for publicly-owned courses (records ARE obtainable there).
    let discHtml = `<div class="golf-sec golf-disclose${isMuni ? ' muni' : ''}">
      <div class="golf-h">Can you find out what this course applies?</div>
      <p>${disc.michigan || ''}</p>
      <p>${disc.private_vs_public || ''}</p>`;
    if (isMuni) {
      discHtml += `<p class="golf-guide"><strong>This is a publicly-owned course.</strong> ${disc.municipal_guidance || ''}</p>`;
    }
    discHtml += `<p class="muted small">${disc.industry || ''}</p>`
      + `<p class="muted small">${disc.could_exist || ''}</p></div>`;

    // Cross-references — context only, never causal.
    const agRank = s.county_ag_rank
      ? `${s.county} County ranks #${s.county_ag_rank} of 83 for reported <em>agricultural</em> pesticide use${s.high_ag_use ? ' (top quartile)' : ''}. `
      : '';
    let xref = `<div class="golf-xref"><span class="k">County context:</span> ${agRank}`
      + `The app's agricultural pesticide layer (USGS EPest) <strong>excludes</strong> golf `
      + `courses, so this land use is <strong>not</strong> counted in county pesticide totals.</div>`;
    if (s.water_site_id) {
      const comps = (s.water_compounds || []).map(golfChem).join(', ');
      xref += `<div class="golf-xref water"><span class="k">Nearby water monitoring (${s.water_site_km} km):</span> `
        + `${comps} detected at ${s.water_site_name}. This is <strong>nearby monitoring, not `
        + `attributable</strong> to this course — these turf-associated compounds also have `
        + `agricultural, lawn, and other sources.</div>`;
    }
    const site = s.website
      ? `<a href="${s.website}" target="_blank" rel="noopener">Course website →</a>` : '';

    return `<div class="golf-popup">
      <div class="golf-type" style="background:${s.color}">${s.glyph} ${s.ownership_legend}</div>
      ${s.operator ? `<div class="golf-operator">${s.operator}</div>` : ''}
      <h4>${s.name}</h4>
      ${meta ? `<div class="golf-meta">${meta}</div>` : ''}
      ${golfSharedHtml()}
      ${discHtml}
      <div class="golf-sec">${xref}</div>
      ${site ? `<div class="golf-links">${site}</div>` : ''}
      <div class="golf-src">Locations: OpenStreetMap (© OpenStreetMap contributors, ODbL)
        via Overpass — crowd-sourced, so coverage may be incomplete or out of date. No
        pesticide-use amounts are shown because Michigan publishes none for golf courses.</div>
    </div>`;
  }

  // Choropleth ramp for PFAS site density (dark → PFAS red).
  const PFAS_PALETTE = ['#22171b', '#361c24', '#4d2029', '#6a2530', '#8a2c37',
                        '#a83a41', '#c2535a', '#d67680', '#e79fa6', '#f4ccd0'];

  // ---------- PFAS overlay (Michigan MPART / EGLE) ----------
  // A dedicated first-class layer. Confirmed Sites read as red hazard markers;
  // Areas of Interest are amber diamonds (under investigation). Public-water
  // results render as hexbin polygons (never precise locations, by EGLE design).
  function pfasPane() {
    if (!state.map.getPane('pfas')) state.map.createPane('pfas').style.zIndex = 648;
    return 'pfas';
  }
  function pfasPolyPane() {
    if (!state.map.getPane('pfaspoly')) state.map.createPane('pfaspoly').style.zIndex = 416;
    return 'pfaspoly';
  }
  function newPfasClusterLayer() {
    if (typeof L.markerClusterGroup === 'function') {
      return L.markerClusterGroup({
        clusterPane: 'pfas', maxClusterRadius: 42, chunkedLoading: true,
        showCoverageOnHover: false, spiderfyOnMaxZoom: true,
        removeOutsideVisibleBounds: true,
      });
    }
    return L.layerGroup();
  }
  async function loadPfas() {
    if (state.pfas.loaded) return;
    const d = await api('/api/pfas/features');
    state.pfas.features = d.features || [];
    state.pfas.legend = d.legend || null;
    state.pfas.loaded = true;
  }
  function pfasVisible(f) { return state.pfas.filters[f.kind] !== false; }

  // The 1,449 public-water-supply hexbins are the heavy part of this layer. Two
  // things keep them fast: (1) a dedicated Canvas renderer draws all of them in a
  // SINGLE <canvas> element instead of 1,449 individual SVG paths; (2) the layer
  // is built ONCE and cached — toggling just adds/removes the same instance rather
  // than re-parsing GeoJSON and reconstructing every polygon.
  function pfasCanvasRenderer() {
    if (!state.pfas._canvas) {
      pfasPolyPane();                                  // ensure the pane exists
      // padding 0.5 draws a little beyond the viewport so hexes don't pop in at
      // the edges while panning; Canvas culls off-screen drawing on its own.
      state.pfas._canvas = L.canvas({ pane: 'pfaspoly', padding: 0.5 });
    }
    return state.pfas._canvas;
  }

  function buildPfasPolyLayer() {
    // One L.geoJSON FeatureCollection (not 1,449 separate layers) on one canvas.
    const fc = { type: 'FeatureCollection', features: [] };
    for (const f of state.pfas.features) {
      if (f.kind !== 'pws' || !f.geometry) continue;
      fc.features.push({ type: 'Feature', geometry: f.geometry, properties: { f } });
    }
    return L.geoJSON(fc, {
      pane: 'pfaspoly',
      renderer: pfasCanvasRenderer(),
      style: (feat) => {
        const f = feat.properties.f;
        return { color: f.color, weight: 1, opacity: 0.8,
          fillColor: f.color, fillOpacity: 0.18 };
      },
      onEachFeature: (feat, layer) => {
        layer.bindPopup(pfasPopupHtml(feat.properties.f),
          { maxWidth: 340, className: 'pfas-popup-wrap' });
      },
    });
  }

  function ensurePfasPolyLayer() {
    if (!state.pfas._polyLayer) state.pfas._polyLayer = buildPfasPolyLayer();
    return state.pfas._polyLayer;
  }

  function renderPfas() {
    if (state.pfas.markers) { state.pfas.markers.remove(); state.pfas.markers = null; }
    // Hexbins: build-once + show/hide. Detach the cached layer when it shouldn't
    // show (full-layer off, or the PWS sub-filter off) — this fully removes it
    // from the map (no ghost) but keeps the instance so re-enabling is instant.
    const wantPolys = state.pfas.showSites && state.pfas.filters.pws !== false;
    if (!wantPolys && state.pfas._polyLayer && state.map.hasLayer(state.pfas._polyLayer)) {
      state.pfas._polyLayer.remove();
      // Also drop the dedicated canvas renderer — otherwise its blank full-map
      // <canvas> (pane 'pfaspoly', pointer-events:auto, z416, above the county
      // overlay pane) lingers and swallows county clicks. See hideAirToxicsLayer.
      removeCanvasRenderer(state.pfas._canvas);
    }
    if (!state.pfas.showSites) { updatePfasStats(); renderMarkerKeys(); return; }
    const pane = pfasPane();
    const grp = newPfasClusterLayer();
    for (const f of state.pfas.features) {
      if (!pfasVisible(f)) continue;
      if (f.lat == null || f.lng == null) continue;
      const isSite = f.kind === 'site';
      const isAoi = f.kind === 'aoi';
      // Site = solid red hazard square; AOI = amber diamond (under investigation).
      const cls = isSite ? 'pfas-marker site' : isAoi ? 'pfas-marker aoi' : 'pfas-marker';
      const size = (isSite || isAoi) ? 26 : 20;
      const m = L.marker([f.lat, f.lng], {
        pane,
        icon: L.divIcon({ className: 'pfas-divicon',
          html: `<div class="${cls}" style="width:${size}px;height:${size}px;background:${f.color}"><span>${f.glyph}</span></div>`,
          iconSize: [size, size], iconAnchor: [size / 2, size / 2] }),
      });
      m.bindPopup(pfasPopupHtml(f), { maxWidth: 340, className: 'pfas-popup-wrap' });
      grp.addLayer(m);
    }
    grp.addTo(state.map);
    state.pfas.markers = grp;
    if (wantPolys) ensurePfasPolyLayer().addTo(state.map);   // add is idempotent
    updatePfasStats(); renderMarkerKeys();
  }

  function updatePfasStats() {
    const el = $('pfas-stats');
    if (!el) return;
    if (!state.pfas.loaded) { el.textContent = '—'; return; }
    const vis = state.pfas.features.filter(pfasVisible);
    const sites = vis.filter((f) => f.kind === 'site').length;
    const aois = vis.filter((f) => f.kind === 'aoi').length;
    el.textContent = `${sites} confirmed sites · ${aois} areas of interest · investigation ongoing`;
  }

  function _pfasXlinks(f) {
    let out = '';
    if (f.contam_site_key) out += `<button type="button" class="pfas-xlink" data-lf-focus="contam" data-lat="${f.lat}" data-lng="${f.lng}">☣ Also a contamination / Superfund site · show on map →</button>`;
    if (f.tri_facility_id) out += `<button type="button" class="pfas-xlink" data-lf-focus="tri" data-id="${f.tri_facility_id}" data-lat="${f.lat}" data-lng="${f.lng}">🏭 Also reports to TRI · show on map →</button>`;
    if (f.landfill_site_key) out += `<button type="button" class="pfas-xlink" data-lf-focus="landfill" data-lat="${f.lat}" data-lng="${f.lng}">🗑 Also a landfill / waste facility · show on map →</button>`;
    return out ? `<div class="pfas-xlinks">${out}</div>` : '';
  }

  function pfasPopupHtml(f) {
    const p = f.props || {};
    const loc = [f.city, f.county ? f.county + ' Co.' : ''].filter(Boolean).join(', ');
    if (f.kind === 'site' || f.kind === 'aoi') {
      const wells = f.residential_wells;
      const wellsHtml = wells
        ? `<div class="pfas-wells ${/^y/i.test(wells) ? 'yes' : 'no'}"><span class="k">Residential wells sampled:</span> <b>${esc(wells)}</b></div>`
        : '';
      const lead = f.site_lead
        ? `<div class="pfas-lead"><span class="k">EGLE site lead:</span> ${esc(f.site_lead)}`
          + `${f.site_lead_email ? ` · <a href="mailto:${esc(f.site_lead_email)}">${esc(f.site_lead_email)}</a>` : ''}`
          + `${f.site_lead_phone ? ` · ${esc(f.site_lead_phone)}` : ''}</div>`
        : '';
      const link = f.hyperlink
        ? `<a class="pfas-cta" href="${esc(f.hyperlink)}" target="_blank" rel="noopener">Official EGLE site investigation summary →</a>` : '';
      return `<div class="pfas-popup">
        <div class="pfas-type ${f.kind}" style="background:${f.color}">${f.glyph} ${esc(f.kind_label)}</div>
        <h4>${esc(f.name)}</h4>
        ${f.site_type ? `<div class="pfas-meta">${esc(f.site_type)}${loc ? ' · ' + esc(loc) : ''}</div>` : (loc ? `<div class="pfas-meta">${esc(loc)}</div>` : '')}
        ${f.kind === 'aoi' ? '<div class="pfas-aoi-note">An Area of Interest is under investigation — the PFAS source has not yet been determined, and residential wells in the area may be affected.</div>' : ''}
        ${wellsHtml}
        ${lead}
        ${_pfasXlinks(f)}
        ${link}
        <div class="pfas-src">Source: Michigan PFAS Action Response Team (MPART) / EGLE, live. Investigation ongoing — absence of a site does not mean absence of PFAS.</div>
      </div>`;
    }
    if (f.kind === 'surface_water') {
      const det = p.detected || {};
      const chips = Object.keys(det).map((k) => `<span class="pfas-chip">${esc(k)} ${det[k]} ppt</span>`).join(' ');
      return `<div class="pfas-popup">
        <div class="pfas-type" style="background:${f.color}">${f.glyph} ${esc(f.kind_label)}</div>
        <h4>${esc(f.name)}</h4>
        ${p.waterbody ? `<div class="pfas-meta">${esc(p.waterbody)}${f.county ? ' · ' + esc(f.county) + ' Co.' : ''}</div>` : ''}
        <div class="pfas-conc">${chips || 'No key PFAS analytes above the reporting limit in the highest sample.'}</div>
        <div class="pfas-meta small">Highest sample${f.sample_date ? ` (${esc(f.sample_date)})` : ''}. Values in parts per trillion (ng/L). Surface water is not drinking water; for context, EPA's drinking-water limit for PFOA/PFOS is 4 ppt.</div>
        <div class="pfas-src">Source: EGLE Water Resources Division — surface-water PFAS sampling.</div>
      </div>`;
    }
    if (f.kind === 'pws') {
      return `<div class="pfas-popup">
        <div class="pfas-type" style="background:${f.color}">${f.glyph} ${esc(f.kind_label)}</div>
        <h4>Public water supply sampling area</h4>
        <div class="pfas-meta">${f.county ? esc(f.county) + ' County' : ''} · general hexbin area (exact system locations withheld by EGLE)</div>
        <div class="pfas-conc">
          <div><b>${p.systems || 0}</b> water system(s) · <b>${p.samples || 0}</b> samples · <b>${p.detections || 0}</b> with a PFAS detection</div>
          ${p.max_pfos != null ? `<div>Max PFOS: <b>${p.max_pfos} ppt</b></div>` : ''}
          ${p.max_pfoa != null ? `<div>Max PFOA: <b>${p.max_pfoa} ppt</b></div>` : ''}
        </div>
        <div class="pfas-meta small">${f.sample_date ? `Latest sample ${esc(f.sample_date)}. ` : ''}EPA's 2024 drinking-water limit for PFOA and PFOS is 4 ppt. Locations are shown as hexbin areas by EGLE's design to protect critical infrastructure.</div>
        <div class="pfas-src">Source: EGLE / AECOM — Public Water Supply PFAS sampling.</div>
      </div>`;
    }
    if (f.kind === 'fish') {
      const url = (state.pfas.legend && state.pfas.legend.mdhhs_fish_url) || f.hyperlink;
      return `<div class="pfas-popup">
        <div class="pfas-type" style="background:${f.color}">${f.glyph} ${esc(f.kind_label)}</div>
        <h4>${esc(f.name)}</h4>
        <div class="pfas-meta">${f.county ? esc(f.county) + ' County' : ''}${f.site_type ? ' · ' + esc(f.site_type) : ''}</div>
        <div class="pfas-conc">
          ${p.max_pfos_ppb != null ? `<div>Max PFOS in fish tissue: <b>${p.max_pfos_ppb} ppb</b></div>` : '<div>PFOS results on record for this water body.</div>'}
          ${(p.species || []).length ? `<div class="small">Species tested: ${p.species.map(esc).join(', ')}</div>` : ''}
        </div>
        <div class="pfas-meta small">${f.sample_date ? `Latest sample ${esc(f.sample_date)}. ` : ''}Fish-tissue PFOS is measured in parts per billion (ppb). Consumption guidance is set by MDHHS.</div>
        ${url ? `<a class="pfas-cta" href="${esc(url)}" target="_blank" rel="noopener">MDHHS Eat Safe Fish guidance →</a>` : ''}
        <div class="pfas-src">Source: Michigan Fish Contaminant Monitoring Program (EGLE).</div>
      </div>`;
    }
    // potw
    return `<div class="pfas-popup">
      <div class="pfas-type" style="background:${f.color}">${f.glyph} ${esc(f.kind_label)}</div>
      <h4>${esc(f.name)}</h4>
      <div class="pfas-meta">${f.county ? esc(f.county) + ' County' : ''}${p.permit ? ' · Permit ' + esc(p.permit) : ''}</div>
      <div class="pfas-conc">
        ${p.receiving_water ? `<div>Discharges to: ${esc(p.receiving_water)}${p.outfall ? ` (outfall ${esc(p.outfall)})` : ''}</div>` : ''}
        ${p.approved_ipp ? `<div>Approved industrial pretreatment program: <b>${esc(p.approved_ipp)}</b></div>` : ''}
        ${p.exceeds_gw_criteria ? `<div>Exceeds groundwater cleanup criteria: <b>${esc(p.exceeds_gw_criteria)}</b></div>` : ''}
      </div>
      ${f.site_lead ? `<div class="pfas-lead"><span class="k">EGLE contact:</span> ${esc(f.site_lead)}${f.site_lead_email ? ` · <a href="mailto:${esc(f.site_lead_email)}">${esc(f.site_lead_email)}</a>` : ''}</div>` : ''}
      ${f.hyperlink ? `<a class="pfas-cta" href="${esc(f.hyperlink)}" target="_blank" rel="noopener">MiEnviro permit record →</a>` : ''}
      <div class="pfas-src">Source: EGLE — Publicly Owned Treatment Works with PFAS data.</div>
    </div>`;
  }

  // ---------- EPA air toxics risk (NATA) census-tract choropleth ----------
  // A fine-grained choropleth (~2,769 tracts) shaded by modeled cancer risk. It
  // reuses the PFAS hexbin performance recipe: ONE Canvas renderer draws all the
  // tract polygons in a single <canvas>, the layer is built once and cached, and
  // the data is lazy-loaded only when the choropleth is selected.
  function airToxicsPane() {
    if (!state.map.getPane('airtox')) state.map.createPane('airtox').style.zIndex = 417;
    return 'airtox';
  }
  function airToxicsCanvasRenderer() {
    if (!state.airToxics._canvas) {
      airToxicsPane();
      state.airToxics._canvas = L.canvas({ pane: 'airtox', padding: 0.5 });
    }
    return state.airToxics._canvas;
  }
  // Cool sequential palette (from the legend), scaled linearly against the 95th
  // percentile so the common range shows variation and a few extreme ethylene-
  // oxide tracts don't flatten the whole map to one color.
  function airToxicsColor(risk) {
    const pal = (state.airToxics.legend && state.airToxics.legend.palette) || ['#1c5462', '#c3d64e'];
    const mx = state.airToxics._max || 1;
    const idx = Math.min(pal.length - 1, Math.max(0, Math.floor((risk / mx) * pal.length)));
    return pal[idx];
  }
  async function loadAirToxics() {
    if (state.airToxics.loaded) return;
    const d = await api('/api/airtoxics/features');
    state.airToxics.tracts = d.tracts || [];
    state.airToxics.legend = d.legend || null;
    state.airToxics.stats = d.stats || null;
    // 95th-percentile color ceiling for good visual spread on a skewed metric.
    const risks = state.airToxics.tracts.map((t) => t.r).sort((a, b) => a - b);
    state.airToxics._max = risks.length
      ? (risks[Math.floor(risks.length * 0.95)] || risks[risks.length - 1] || 1) : 1;
    state.airToxics.loaded = true;
  }
  function buildAirToxicsPolyLayer() {
    const fc = { type: 'FeatureCollection', features: [] };
    for (const t of state.airToxics.tracts) {
      if (!t.geometry) continue;
      fc.features.push({ type: 'Feature', geometry: t.geometry, properties: { t } });
    }
    return L.geoJSON(fc, {
      pane: 'airtox',
      renderer: airToxicsCanvasRenderer(),
      style: (feat) => ({ color: '#0d1117', weight: 0.3, opacity: 0.5,
        fillColor: airToxicsColor(feat.properties.t.r), fillOpacity: 0.72 }),
      onEachFeature: (feat, layer) => {
        layer.bindPopup(airToxicsPopupHtml(feat.properties.t),
          { maxWidth: 320, className: 'atx-popup-wrap' });
      },
    });
  }
  function ensureAirToxicsPolyLayer() {
    if (!state.airToxics._polyLayer) state.airToxics._polyLayer = buildAirToxicsPolyLayer();
    return state.airToxics._polyLayer;
  }
  function showAirToxicsLayer() {
    ensureAirToxicsPolyLayer().addTo(state.map);   // idempotent add
    updateAirToxicsStats();
  }
  function hideAirToxicsLayer() {
    if (state.airToxics._polyLayer && state.map.hasLayer(state.airToxics._polyLayer)) {
      state.airToxics._polyLayer.remove();
    }
    // CRITICAL: removing the polygon layer does NOT remove its dedicated canvas
    // RENDERER — Leaflet keeps a layer's custom renderer on the map after the
    // layer itself is gone. That leaves a blank, full-map <canvas> in the
    // 'airtox' pane (pointer-events:auto, z-index 417, ABOVE the county overlay
    // pane at z400) which silently swallows every county click until a page
    // refresh. Remove the renderer too. Re-showing re-adds it automatically when
    // the polygon layer is added back (Leaflet re-attaches the layer's renderer).
    removeCanvasRenderer(state.airToxics._canvas);
  }
  function updateAirToxicsStats() {
    const el = $('airtox-stats');
    if (!el) return;
    const s = state.airToxics.stats;
    el.textContent = s
      ? `${state.airToxics.tracts.length} tracts · Michigan avg ${s.mi_avg} · national avg ${s.national_avg} in-a-million`
      : '—';
  }
  // One-sentence clarifying clause for the "driven mostly by X" headline, so
  // secondary/background aren't dead ends a layperson can't interpret.
  function _atxDriverClause(key) {
    if (key === 'secondary') {
      return ' — which forms in the air from precursor emissions (traffic, industry, '
        + 'solvents), rather than being released directly from any one source';
    }
    if (key === 'background') {
      return ' — which reflects regional and long-range pollution already in the air, '
        + 'not local sources';
    }
    return '';
  }
  // What the percentages actually mean — not obvious, and it changes how they read.
  const ATX_SHARE_NOTE = 'Each bar is that category’s share of the total modeled '
    + 'cancer risk in this tract — <b>not</b> share of emissions or pollution by weight. '
    + 'Tap or hover a name to see what it means.';

  // Render the eight source-category bars, labels tappable for a plain definition.
  function _atxSourceBars(entries, ssum, meta) {
    return entries.map(([k, v]) => {
      const m = meta[k] || { label: k, color: '#8a94a3', gloss: '' };
      const pct = Math.round(v / ssum * 100);
      const pctTxt = (pct < 1 && v > 0) ? '<1%' : pct + '%';
      const lbl = m.gloss
        ? `<span class="gloss-term" data-gloss="${esc(m.gloss)}" tabindex="0">${esc(m.label)}</span>`
        : esc(m.label);
      return `<div class="atx-bar"><span class="atx-bar-l">${lbl}</span>`
        + `<span class="atx-bar-t"><span style="width:${pct}%;background:${m.color}"></span></span>`
        + `<span class="atx-bar-v">${pctTxt}</span></div>`;
    }).join('');
  }

  function airToxicsPopupHtml(t) {
    const L = state.airToxics.legend || {};
    const s = state.airToxics.stats || {};
    const mi = s.mi_avg, natl = s.national_avg;
    const vsMi = mi ? Math.round((t.r - mi) / mi * 100) : null;
    const srcMeta = {}; (L.sources || []).forEach((x) => { srcMeta[x.key] = x; });
    const src = t.src || {};
    const ssum = Object.values(src).reduce((a, b) => a + b, 0) || 1;
    const sorted = Object.entries(src).sort((a, b) => b[1] - a[1]);  // all 8 shown
    const dom = sorted[0];
    const bars = _atxSourceBars(sorted, ssum, srcMeta);
    const polls = (t.poll || []).slice(0, 5)
      .map((p) => `${chemLink(p[0])}`).join(', ');
    const vsCls = vsMi > 0 ? 'hi' : vsMi < 0 ? 'lo' : '';
    const vsTxt = vsMi != null ? `${Math.abs(vsMi)}% ${vsMi >= 0 ? 'above' : 'below'} MI avg` : '';
    return `<div class="atx-popup">
      <div class="atx-type">🌫 Air toxics cancer risk · modeled</div>
      <div class="atx-risk"><b>${t.r}</b> <span class="atx-unit">in a million</span>`
      + `${vsTxt ? ` <span class="atx-vs ${vsCls}">${vsTxt}</span>` : ''}</div>
      <div class="atx-meta">${esc(t.c || '')} County · Michigan avg ${mi} · national avg ${natl}</div>
      ${dom ? `<div class="atx-driver">Risk here is driven mostly by <b>${esc((srcMeta[dom[0]] || {}).label || dom[0])}</b>${_atxDriverClause(dom[0])}.</div>` : ''}
      <div class="atx-share-note">${ATX_SHARE_NOTE}</div>
      <div class="atx-bars">${bars}</div>
      ${polls ? `<div class="atx-poll"><span class="k">Top pollutants:</span> ${polls}</div>` : ''}
      <details class="atx-caveat">
        <summary>⚠ A screening estimate — what this is (and isn't)</summary>
        <ul>${(L.caveats || []).map((c) => `<li>${esc(c)}</li>`).join('')}</ul>
        <div class="atx-assess">${esc(L.assessment || '')}. EPA cautions against comparing across assessment years, so this is not trended.</div>
      </details>
    </div>`;
  }

  // ---------- Underground Storage Tanks overlay (EGLE RRD) ----------
  // ~32k points, so we lazy-load per category (open leaking / closed / licensed)
  // and cluster. A licensed Part 211 tank must never look like a Part 213 release:
  // open leaking = prominent red, closed = amber, licensed = small muted grey.
  const UST_PALETTE = ['#241a15', '#3a2416', '#542c17', '#71341a', '#8f3d1d',
                       '#ae4a23', '#c85f2c', '#dc7c40', '#ec9f63', '#f7c795'];
  function ustPane() {
    if (!state.map.getPane('ust')) state.map.createPane('ust').style.zIndex = 643;
    return 'ust';
  }
  function newUstClusterLayer() {
    if (typeof L.markerClusterGroup === 'function') {
      return L.markerClusterGroup({
        clusterPane: 'ust', maxClusterRadius: 50, chunkedLoading: true,
        showCoverageOnHover: false, spiderfyOnMaxZoom: true,
        removeOutsideVisibleBounds: true,
      });
    }
    return L.layerGroup();
  }
  function _ustCat(cat) {
    const list = (state.ust.legend && state.ust.legend.categories) || [];
    return list.find((c) => c.key === cat) || { glyph: '⛽', color: '#7f8b99', label: cat };
  }
  async function loadUstCategory(cat) {
    if (state.ust.loaded[cat]) return;
    const d = await api('/api/ust/sites', { category: cat });
    state.ust.legend = d.legend || state.ust.legend;
    state.ust.byCat[cat] = d.sites || [];
    state.ust.loaded[cat] = true;
  }
  async function ensureUstLoaded() {
    for (const cat of Object.keys(state.ust.filters)) {
      if (state.ust.filters[cat] && !state.ust.loaded[cat]) await loadUstCategory(cat);
    }
  }
  function ustSize(cat) {
    return cat === 'leaking_open' ? 26 : cat === 'leaking_closed' ? 22 : 17;
  }
  function renderUst() {
    if (state.ust.markers) { state.ust.markers.remove(); state.ust.markers = null; }
    if (!state.ust.showSites) { updateUstStats(); renderMarkerKeys(); return; }
    const pane = ustPane();
    const grp = newUstClusterLayer();
    for (const cat of Object.keys(state.ust.filters)) {
      if (!state.ust.filters[cat] || !state.ust.loaded[cat]) continue;
      const meta = _ustCat(cat);
      const size = ustSize(cat);
      const muted = cat === 'licensed' ? ' muted' : '';
      for (const f of state.ust.byCat[cat] || []) {
        if (f.lat == null || f.lng == null) continue;
        const m = L.marker([f.lat, f.lng], {
          pane,
          icon: L.divIcon({ className: 'ust-divicon',
            html: `<div class="ust-marker ${cat}${muted}" style="width:${size}px;height:${size}px;background:${meta.color}"><span>${meta.glyph}</span></div>`,
            iconSize: [size, size], iconAnchor: [size / 2, size / 2] }),
        });
        m.bindPopup(ustPopupHtml(f), { maxWidth: 340, className: 'ust-popup-wrap' });
        grp.addLayer(m);
      }
    }
    grp.addTo(state.map);
    state.ust.markers = grp;
    updateUstStats(); renderMarkerKeys();
  }
  function updateUstStats() {
    const el = $('ust-stats');
    if (!el) return;
    if (!state.ust.showSites) { el.textContent = '—'; return; }
    const open = (state.ust.byCat.leaking_open || []).length;
    el.textContent = state.ust.loaded.leaking_open
      ? `${open.toLocaleString()} open leaking releases mapped · toggle closed & licensed tanks above`
      : 'loading…';
  }
  function _ustProgramLabel(pg) {
    return pg === 213
      ? 'Part 213 — a confirmed leaking tank under state cleanup oversight'
      : pg === 211
      ? 'Part 211 — a licensed (registered) tank, not a reported leak'
      : '';
  }

  // ----- plain-language UST helpers (shared by the popup and the report) -----

  // A one/two-sentence explanation of what this actually is, by category. Visible
  // by default so a skimmer immediately gets "buried fuel tank leaked here".
  function _ustPlainLead(cat) {
    if (cat === 'leaking_open') {
      return 'A buried fuel tank at this site <b>leaked</b>, and the contamination is '
        + 'still being investigated or cleaned up. Underground storage tanks sit at gas '
        + 'stations, truck stops, auto shops, and industrial sites — when a tank or its '
        + 'underground piping corrodes or fails, fuel escapes into the soil and can reach '
        + 'groundwater.';
    }
    if (cat === 'leaking_closed') {
      return 'A buried fuel tank here <b>leaked in the past</b>, and the state has since '
        + 'determined the site met its cleanup criteria and closed the case. Note: '
        + '"closed" does <b>not</b> always mean all contamination was removed — some sites '
        + 'close with residual contamination left in place under land-use restrictions.';
    }
    return 'This is a <b>registered fuel tank with no reported leak</b> — most gas stations '
      + 'have these. It is <b>not</b> a documented contamination site.';
  }

  // EGLE Class 1–5 -> plain meaning. EGLE-sourced: the class maps 1:1 to the
  // dataset's own risk_condition text (Class 1 = immediate … Class 5 = closed),
  // confirmed against EGLE policy RRD-21. We show the code + a plain phrase.
  const UST_CLASS_PLAIN = {
    'Class 1': 'the state considers the risk present and immediate',
    'Class 2': 'risks are present and need action in the short term',
    'Class 3': 'risks are present and need action in the long term',
    'Class 4': 'risks are being controlled (interim / long-term state-funded action)',
    'Class 5': 'cleanup criteria were met — closure report approved',
    'No Longer A Facility': 'no longer an active facility',
    'Unknown': 'not yet determined',
  };
  function _ustClassPlain(cc) {
    if (!cc) return '';
    return UST_CLASS_PLAIN[cc] || '';
  }

  // "What typically leaks" — labeled explicitly as what petroleum releases usually
  // involve, NOT a site-specific measurement (EGLE carries no per-site chemical
  // list). Same honesty pattern as the golf-course turf chemicals. Chemical names
  // link through to the shared PubChem chemical popups.
  function _ustContaminantsHtml() {
    const c = (n) => chemLink(n);
    return `<p class="ust-sub">What typically leaks from a petroleum tank</p>`
      + `<p class="ust-fine">These tanks usually hold gasoline, diesel, used/waste oil, or `
      + `heating oil. When petroleum leaks, the substances of concern are usually the ones `
      + `below — this is <b>what such releases typically involve, not a measurement at this `
      + `specific site</b> (EGLE's dataset carries no per-site chemical list):</p>`
      + `<ul class="ust-chem-list">`
      + `<li>${c('Benzene')} — the biggest concern; a known human carcinogen linked to leukemia</li>`
      + `<li>${c('Toluene')}, ${c('Ethylbenzene')}, and ${c('Xylenes')} — with benzene these are `
      + `<span data-gloss="BTEX">BTEX</span>, the standard petroleum-contamination markers</li>`
      + `<li>${c('MTBE')} — a fuel additive used from the late 1970s into the early 2000s; `
      + `extremely mobile in groundwater and detectable by taste and odor at very low levels</li>`
      + `<li>${c('Naphthalene')} and other <span data-gloss="PAH">PAHs</span></li>`
      + `<li>${c('Lead')} — at sites with releases from the leaded-gasoline era (phased out `
      + `for on-road fuel by 1996)</li>`
      + `<li>Used-oil tanks may also involve heavy metals and sometimes chlorinated solvents</li>`
      + `</ul>`;
  }

  // The three exposure pathways in plain language — vapor intrusion is the one
  // people don't know about, so it's spelled out.
  function _ustPathwaysHtml() {
    return `<p class="ust-sub">How a leak could actually reach people</p>`
      + `<ul class="ust-path-list">`
      + `<li><b>Drinking water</b> — contamination migrating into groundwater used by private `
      + `wells, or (less commonly) affecting a public water supply.</li>`
      + `<li><b>Vapor intrusion</b> — petroleum <span data-gloss="vapor intrusion">vapors</span> `
      + `rising up through soil into the basements and crawlspaces of nearby buildings, `
      + `affecting indoor air. This can happen <b>even if you're on municipal water and never `
      + `touch the soil</b> — which is why being close to a release matters beyond just water.</li>`
      + `<li><b>Direct soil contact</b> — mainly on, or immediately next to, the site itself.</li>`
      + `</ul>`;
  }
  function _ustAccuracyNote(f) {
    if (f.am) return 'This point was located by address matching, not GPS — its position is approximate (may be off by a parcel or block).';
    if (f.ha && f.ha >= 50) return `Location accuracy about ${Math.round(f.ha)} m — treat the point as approximate.`;
    return '';
  }
  function ustPopupHtml(f) {
    const meta = _ustCat(f.c);
    const loc = [f.a, f.ci].filter(Boolean).join(', ');
    const isLeaking = f.c === 'leaking_open' || f.c === 'leaking_closed';
    const isOpen = f.c === 'leaking_open';
    const prog = _ustProgramLabel(f.pg);
    const acc = _ustAccuracyNote(f);

    // Regulatory detail, now with short inline explanations of the jargon.
    let body = '';
    if (isLeaking) {
      const bits = [];
      if (f.rs) {
        const relGloss = /open/i.test(f.rs)
          ? ' <span class="ust-gloss">— cleanup is not yet finished</span>'
          : /closed/i.test(f.rs)
          ? ' <span class="ust-gloss">— the state agreed cleanup criteria were met</span>' : '';
        bits.push(`<div><span class="k">Release status:</span> <b>${esc(f.rs)}</b>`
          + `${isOpen && f.orl ? ` · ${f.orl} open` : ''}${f.cr ? ` · ${f.cr} closed` : ''}${relGloss}</div>`);
      }
      if (f.cc) {
        const plain = _ustClassPlain(f.cc);
        const egle = f.rk ? ` <span class="ust-gloss">(EGLE: ${esc(f.rk)})</span>` : '';
        bits.push(`<div><span class="k">Site classification:</span> <b>${esc(f.cc)}</b>`
          + `${plain ? ` — ${esc(plain)}` : ''}${egle}</div>`);
      }
      // "corrective action" gloss where the process is named.
      if (isOpen) {
        bits.push('<div class="ust-gloss">The site is in <b>corrective action</b> — the '
          + 'required investigation and cleanup the responsible party must carry out until '
          + 'the release meets closure criteria.</div>');
      }
      body = bits.join('');
    } else {
      // Licensed: the plain lead above already explains it — don't repeat.
      body = '';
    }
    const tanks = (f.tt != null || f.at != null)
      ? `<div><span class="k">Tanks:</span> ${f.tt != null ? f.tt + ' total' : ''}${f.at != null ? ` · ${f.at} active` : ''}</div>` : '';
    const pm = f.pm ? `<div><span class="k">EGLE project manager:</span> ${esc(f.pm)}</div>` : '';
    const dist = f.wu ? `<div><span class="k">EGLE district:</span> ${esc(f.wu)}</div>` : '';
    const xlink = f.xc
      ? `<button type="button" class="ust-xlink" data-lf-focus="contam" data-lat="${f.lat}" data-lng="${f.lng}">☣ Also a contamination / Superfund site · show on map →</button>` : '';
    const ride = (state.ust.legend && state.ust.legend.ride_url)
      ? `<a class="ust-cta" href="${esc(state.ust.legend.ride_url)}" target="_blank" rel="noopener">EGLE RIDE Mapper${f.id ? ` (facility ${esc(f.id)})` : ''} →</a>` : '';
    // Deep detail (contaminants + pathways) tucked behind progressive disclosure —
    // only for leaking sites, where "what could reach me" actually matters.
    const more = isLeaking
      ? `<details class="ust-more"><summary>What leaks from a fuel tank, and how it could reach you</summary>`
        + `<div class="ust-more-body">${_ustContaminantsHtml()}${_ustPathwaysHtml()}</div></details>`
      : '';
    return `<div class="ust-popup">
      <div class="ust-type ${f.c}" style="background:${meta.color}">${meta.glyph} ${esc(meta.short || meta.label)}</div>
      <h4>${esc(f.n)}</h4>
      <div class="ust-plain">${_ustPlainLead(f.c)}</div>
      ${prog ? `<div class="ust-meta">${esc(prog)}</div>` : ''}
      ${loc ? `<div class="ust-meta">${esc(loc)}${f.co ? ' · ' + esc(f.co) + ' Co.' : ''}</div>` : (f.co ? `<div class="ust-meta">${esc(f.co)} County</div>` : '')}
      <div class="ust-body">${body}${tanks}${pm}${dist}</div>
      ${more}
      ${xlink ? `<div class="ust-xlinks">${xlink}</div>` : ''}
      ${acc ? `<div class="ust-accuracy">📍 ${esc(acc)}</div>` : ''}
      ${ride}
      <div class="ust-src">Source: Michigan EGLE Remediation &amp; Redevelopment (RRD)${f.lu ? ` · updated ${esc(f.lu)}` : ''}. Registered tanks only — unregistered / abandoned tanks (incl. most home heating-oil tanks) are not included.</div>
    </div>`;
  }

  // "Request monitoring records (FOIA)" button inside a landfill popup: build a
  // facility-specific, type-adapted request and open the reusable FOIA modal.
  document.addEventListener('click', (e) => {
    const btn = e.target.closest && e.target.closest('[data-lf-foia]');
    if (!btn || typeof window.PMFoia === 'undefined') return;
    e.preventDefault();
    const s = state.landfill.sites.find((x) => x.site_key === btn.getAttribute('data-lf-foia'));
    if (!s) return;
    // The EGLE license_id means different things per program: Part 115 carries
    // the EGLE Site (WDS) ID; Part 111 carries the EPA/RCRA handler ID, with the
    // EGLE-internal WDS ID surfaced separately as alt_id.
    const licLabel = s.program === 'part111'
      ? 'Facility ID (EPA / RCRA handler ID)'
      : 'Facility ID (EGLE Site ID)';
    window.PMFoia.open({
      subject: s.name + (s.county ? ` · ${s.county} County` : ''),
      explainer: state.landfill.foiaAgency && state.landfill.foiaAgency.explainer,
      facility: {
        name: s.name, operator: s.operator, license_id: s.license_id,
        license_label: licLabel, alt_id: s.alt_id, alt_id_label: s.alt_id_label,
        address: s.address, city: s.city, zip: s.zip, county: s.county,
        type_label: s.type_label,
      },
      formNote: 'EGLE limits each request to one facility address. To request '
        + 'records for more than one facility, submit a separate request for each.',
      records: (s.foia && s.foia.records) || [],
      authority: s.foia && s.foia.authority,
      agency: state.landfill.foiaAgency,
    });
  });

  // Cross-link buttons inside landfill popups: enable the related overlay and
  // fly to the facility. Delegated so it works for dynamically-built popups.
  document.addEventListener('click', async (e) => {
    const el = e.target.closest && e.target.closest('[data-lf-focus]');
    if (!el) return;
    e.preventDefault();
    const kind = el.getAttribute('data-lf-focus');
    const lat = parseFloat(el.getAttribute('data-lat'));
    const lng = parseFloat(el.getAttribute('data-lng'));
    const zoom = Math.max(state.map.getZoom(), 10);
    if (kind === 'tri') {
      const id = el.getAttribute('data-id');
      const cb = $('tri-sites');
      if (cb && !cb.checked) { cb.checked = true; state.tri.showSites = true; await refreshTriSites(); }
      const m = state.tri.markerById && state.tri.markerById.get(id);
      if (m) { state.map.setView(m.getLatLng(), zoom); m.openPopup(); }
      else if (!Number.isNaN(lat)) state.map.setView([lat, lng], zoom);
    } else if (kind === 'contam') {
      const cb = $('contam-sites');
      if (cb && !cb.checked) {
        cb.checked = true; state.contam.showSites = true;
        await loadContamination(); renderContamMarkers(); renderMarkerKeys();
      }
      if (!Number.isNaN(lat)) state.map.setView([lat, lng], zoom);
    } else if (kind === 'landfill') {
      const cb = $('landfill-sites');
      if (cb && !cb.checked) {
        cb.checked = true; state.landfill.showSites = true;
        await loadLandfills(); renderLandfillMarkers();
      }
      if (!Number.isNaN(lat)) state.map.setView([lat, lng], zoom);
    }
  });

  // ---------- Spraying Programs directory overlay ----------
  // A curated directory of Michigan's organized spraying programs (spongy moth,
  // mosquito abatement, state arbovirus response). Each marker links out to the
  // official page for current schedules — this is NOT a live spray-date feed.
  function sprayingPane() {
    if (!state.map.getPane('spraying')) {
      state.map.createPane('spraying').style.zIndex = 655;  // above contam markers
    }
    return 'spraying';
  }

  function newSprayingClusterLayer() {
    if (typeof L.markerClusterGroup === 'function') {
      return L.markerClusterGroup({
        clusterPane: 'spraying', maxClusterRadius: 44, chunkedLoading: true,
        showCoverageOnHover: false, spiderfyOnMaxZoom: true,
        removeOutsideVisibleBounds: true,
      });
    }
    return L.layerGroup();   // graceful fallback if the cluster plugin didn't load
  }

  async function loadSprayingPrograms() {
    if (state.spraying.loaded) return;
    const d = await api('/api/spraying/programs');
    state.spraying.programs = d.programs || [];
    state.spraying.types = d.types || [];
    state.spraying.loaded = true;
  }

  function renderSprayingMarkers() {
    if (state.spraying.markers) { state.spraying.markers.remove(); state.spraying.markers = null; }
    if (!state.spraying.showMarkers) { renderMarkerKeys(); return; }
    const pane = sprayingPane();
    const grp = newSprayingClusterLayer();
    for (const p of state.spraying.programs) {
      if (p.lat == null || p.lon == null) continue;
      const size = 30;
      const m = L.marker([p.lat, p.lon], {
        pane,
        icon: L.divIcon({
          className: 'spraying-divicon',
          html: `<div class="spraying-marker" style="width:${size}px;height:${size}px;background:${p.color}"><span>${p.glyph}</span></div>`,
          iconSize: [size, size], iconAnchor: [size / 2, size / 2],
        }),
      });
      m.bindPopup(sprayingPopupHtml(p), { maxWidth: 340, className: 'spraying-popup-wrap' });
      grp.addLayer(m);
    }
    grp.addTo(state.map);
    state.spraying.markers = grp;
    renderMarkerKeys();
  }

  function sprayingPopupHtml(p) {
    const row = (k, v) => v ? `<div class="row"><span class="k">${k}</span> ${v}</div>` : '';
    // Chemical names are clickable → the shared PubChem chemical-info popup, so a
    // resident can learn what e.g. permethrin or Btk actually is.
    const chems = (p.pesticides || []).length
      ? (p.pesticides).map((c) => chemLink(c)).join(', ')
      : '<span class="muted">not specified — see official page</span>';
    return `<div class="spraying-popup">
      <div class="sp-type" style="background:${p.color}">${p.glyph} ${p.type_label}</div>
      <h4>${p.name}</h4>
      <div class="sp-meta">${p.area}</div>
      ${p.description ? `<p class="sp-desc">${p.description}</p>` : ''}
      ${row('Administered by:', p.administrator)}
      ${row('Pesticide(s) typically used:', chems)}
      ${row('Typical season:', p.season)}
      <a class="sp-official" href="${p.url}" target="_blank" rel="noopener">View official program page &amp; current schedule →</a>
      <div class="sp-source">Source: ${p.source}. Directory entry — confirm current dates on the official page.</div>
    </div>`;
  }

  // ---------- Coal ash (CCR) sites directory overlay ----------
  // A curated, essentially-complete directory of Michigan's coal combustion
  // residuals sites. The CCR rule is self-implementing (each utility posts its
  // own monitoring data), so each marker links to that operator's official CCR
  // page rather than showing live results. Color = closure status; the letter
  // = unit type (P/L/P+L); a ⚠ ring flags sites with a confirmed UNLINED unit.
  function coalAshPane() {
    if (!state.map.getPane('coalash')) {
      state.map.createPane('coalash').style.zIndex = 653;  // among the marker panes
    }
    return 'coalash';
  }

  function newCoalAshClusterLayer() {
    if (typeof L.markerClusterGroup === 'function') {
      // Only 17 sites statewide, so keep it simple and deterministic: no chunked
      // loading and no removeOutsideVisibleBounds. The latter matters because the
      // address report's "Show on map" flies to a site and opens its popup — with
      // markers culled off-screen mid-flight, that deep-link could miss its target
      // (seen on mobile). Keeping all markers rendered makes the deep-link reliable.
      return L.markerClusterGroup({
        clusterPane: 'coalash', maxClusterRadius: 44, chunkedLoading: false,
        showCoverageOnHover: false, spiderfyOnMaxZoom: true,
        removeOutsideVisibleBounds: false,
      });
    }
    return L.layerGroup();
  }

  async function loadCoalAsh() {
    if (state.coalAsh.loaded) return;
    const d = await api('/api/coal-ash/sites');
    state.coalAsh.sites = d.sites || [];
    state.coalAsh.statuses = d.statuses || [];
    state.coalAsh.unitTypes = d.unit_types || [];
    state.coalAsh.loaded = true;
  }

  function renderCoalAshMarkers() {
    if (state.coalAsh.markers) { state.coalAsh.markers.remove(); state.coalAsh.markers = null; }
    if (!state.coalAsh.showMarkers) { renderMarkerKeys(); return; }
    const pane = coalAshPane();
    const grp = newCoalAshClusterLayer();
    for (const s of state.coalAsh.sites) {
      if (s.lat == null || s.lon == null) continue;
      const size = 30;
      const cls = 'coalash-marker' + (s.unlined ? ' unlined' : '');
      const m = L.marker([s.lat, s.lon], {
        pane,
        icon: L.divIcon({
          className: 'coalash-divicon',
          html: `<div class="${cls}" style="background:${s.color}" title="${_rEsc(s.name)}">`
            + `<span class="ca-let">${s.unit_letter}</span>`
            + (s.unlined ? '<span class="ca-warn">⚠</span>' : '') + '</div>',
          iconSize: [size, size], iconAnchor: [size / 2, size / 2],
        }),
      });
      m.bindPopup(coalAshPopupHtml(s), { maxWidth: 360, className: 'coalash-popup-wrap' });
      grp.addLayer(m);
    }
    grp.addTo(state.map);
    state.coalAsh.markers = grp;
    renderMarkerKeys();
  }

  function _coalAshCrosslinks(xl) {
    if (!xl) return '';
    const seg = (arr, label) => (arr && arr.length)
      ? `<div class="ca-xl-row"><span class="ca-xl-k">${label}:</span> `
        + arr.map((x) => `${_rEsc(x.name)}`).join(' · ') + '</div>' : '';
    const body = seg(xl.tri, 'TRI') + seg(xl.landfill, 'Landfill') + seg(xl.contamination, 'Contamination');
    if (!body) return '';
    return `<div class="ca-xl"><div class="ca-xl-h">Also mapped in this app (same site):</div>${body}</div>`;
  }

  function coalAshPopupHtml(s) {
    const row = (k, v) => v ? `<div class="row"><span class="k">${k}</span> ${v}</div>` : '';
    // Contaminant names are clickable → the shared PubChem chemical-info popup.
    const chems = (s.contaminants || []).length
      ? (s.contaminants).map((c) => chemLink(c)).join(', ')
      : '<span class="muted">no third-party groundwater findings compiled for this site</span>';
    const units = (s.units || []).length
      ? '<ul class="ca-units">' + s.units.map((u) => `<li>${_rEsc(u)}</li>`).join('') + '</ul>' : '';
    const unlinedFlag = s.unlined
      ? '<div class="ca-unlined">⚠ Includes a confirmed UNLINED unit — the higher-risk kind the CCR rule most concerns.</div>' : '';
    const contamBlock = (s.contaminants || []).length
      ? `<div class="ca-contam"><div class="ca-h">Groundwater contaminants identified <span class="ca-disputed">(third-party — disputed)</span></div>`
        + `<div class="ca-chips">${chems}</div>`
        + (s.contaminant_source ? `<div class="ca-src">${_rEsc(s.contaminant_source)}</div>` : '')
        + '</div>'
      : `<div class="ca-contam"><div class="ca-chips">${chems}</div></div>`;
    const gap = s.data_gap
      ? `<div class="ca-gap"><span class="ca-gap-i">ⓘ</span> ${_rEsc(s.data_gap)}</div>` : '';
    const approx = s.approx ? ' <span class="muted small">(location approximate)</span>' : '';
    return `<div class="coalash-popup">
      <div class="ca-status" style="background:${s.color}">${s.status_label} · ${_rEsc(s.unit_type_label)}</div>
      <h4>${_rEsc(s.name)}</h4>
      <div class="ca-meta">${_rEsc(s.operator)}</div>
      <div class="ca-meta">${_rEsc(s.city)}, ${_rEsc(s.county)} County${approx}</div>
      ${s.plant_status ? `<p class="ca-desc">${_rEsc(s.plant_status)}</p>` : ''}
      ${units ? `<div class="ca-h">Coal-ash units</div>${units}` : ''}
      ${unlinedFlag}
      ${row('Closure:', s.closure ? _rEsc(s.closure) : '')}
      ${contamBlock}
      ${gap}
      ${_coalAshCrosslinks(s.crosslinks)}
      <a class="ca-official" href="${_rEsc(s.ccr_url)}" target="_blank" rel="noopener">View ${_rEsc(s.ccr_host)} CCR compliance page →</a>
      <div class="ca-source">Source: ${_rEsc(s.source)}. Directory entry — the legally-required monitoring data lives on the operator's CCR page.</div>
    </div>`;
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
      `<div class="tri-chem"><span class="cn">${chemLink(c.chemical, { fips: f.county_fips })}`
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
        if (ch) { openChemInfo(decodeURIComponent(ch.dataset.chem), { fips: el.dataset.fips }); }
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

  // ---------- reusable chemical-info popup ----------
  // A clickable chemical/compound name anywhere in the app. Encodes the raw name
  // (chem names can contain commas, e.g. "2,4-D"); the delegated handler decodes.
  function chemLink(name, opts) {
    opts = opts || {};
    if (!name) return '';
    const fips = opts.fips ? ` data-chem-fips="${opts.fips}"` : '';
    const site = opts.site ? ` data-chem-site="${encodeURIComponent(opts.site)}"` : '';
    const label = opts.label != null ? opts.label : name;
    return `<span class="chem-link" role="button" tabindex="0" data-chem="${encodeURIComponent(name)}"${fips}${site}`
      + ` title="What is ${name}? — tap for details">${label}</span>`;
  }

  // Open the shared chemical-info modal for any chemical/compound. Merges the
  // curated hazard profile with reported pesticide use and TRI releases; passing
  // a fips adds that county's TRI breakdown. Reused everywhere a name is shown.
  async function openChemInfo(name, opts) {
    opts = opts || {};
    const modal = $('tri-info-modal');
    const body = $('tri-info-body');
    if (!modal || !body) return;
    body.innerHTML = '<p class="muted">Loading…</p>';
    show(modal);
    let d;
    try { d = await api('/api/chemical', { name, fips: opts.fips || '', site: opts.site || '' }); }
    catch (e) { body.innerHTML = '<p class="muted">Could not load chemical info.</p>'; return; }
    if (!d || !d.found) { body.innerHTML = `<p class="muted">No information available for ${name}.</p>`; return; }
    body.innerHTML = chemInfoHtml(d);
  }

  function chemInfoHtml(d) {
    const p = d.profile || {};
    const flags =
      (d.carcinogen ? '<span class="tri-flag carc">carcinogen</span> ' : '')
      + (d.pfas ? '<span class="tri-flag pfas" data-gloss="PFAS">PFAS</span>' : '');
    const line = (label, val) => val
      ? `<div class="tci-row"><span class="tci-k">${label}</span><span class="tci-v">${val}</span></div>` : '';

    // Reported agricultural pesticide use, when this compound is one.
    let pestBlock = '';
    if (d.is_pesticide && d.pesticide) {
      const pe = d.pesticide;
      const cat = pe.category ? pe.category.replace(/_/g, ' ') : null;
      // When opened from a county context, lead with that county's applied
      // amount and keep the statewide figure beside it for scale.
      const pStats = [];
      if (pe.county != null && pe.county_lbs != null) {
        pStats.push(`<div><strong>${fmtLbs(pe.county_lbs)}</strong><span>applied in ${pe.county} Co. (${pe.latest_year})</span></div>`);
      }
      if (pe.statewide_lbs != null) {
        pStats.push(`<div><strong>${fmtLbs(pe.statewide_lbs)}</strong><span>applied statewide (${pe.latest_year})</span></div>`);
      }
      pestBlock =
        '<div class="tci-sub2">Agricultural pesticide use</div>'
        + (cat ? `<div class="tci-row"><span class="tci-k">Pesticide type</span><span class="tci-v">${cat}</span></div>` : '')
        + (pe.toxicity_class ? `<div class="tci-row"><span class="tci-k">Toxicity class</span><span class="tci-v">${pe.toxicity_class}</span></div>` : '')
        + (pStats.length ? `<div class="tci-stats">${pStats.join('')}</div>` : '');
    }

    // Reported industrial TRI releases, when this chemical is one.
    let triBlock = '';
    if (d.is_tri && d.tri) {
      const t = d.tri;
      const paths = (t.pathways || []).filter((x) => x.lbs > 0)
        .map((x) => `${x.label} ${fmtLbs(x.lbs)}`).join(' · ');
      const facs = (t.facilities || []).map((f) =>
        `<div class="tci-firow"><span class="n">${f.name}</span><span class="v">${fmtLbs(f.lbs)}</span></div>`).join('');
      triBlock =
        '<div class="tci-sub2">Industrial releases (TRI)</div>'
        + '<div class="tci-stats">'
        + (t.county != null ? `<div><strong>${fmtLbs(t.county_lbs)}</strong><span>released in ${t.county} Co. (${t.year})</span></div>` : '')
        + `<div><strong>${fmtLbs(t.statewide_lbs)}</strong><span>released statewide (${t.year})</span></div>`
        + '</div>'
        + (paths ? line('Released via', paths) : '')
        + (facs ? `<div class="tci-sub2">Facilities releasing it${t.county ? ' in ' + t.county + ' County' : ''}</div><div class="tci-facs">${facs}</div>` : '');
    }

    // Water monitoring detections at the specific site the popup was opened from.
    let waterBlock = '';
    if (d.water && d.water.samples) {
      const w = d.water;
      const where = w.site_name ? `at ${w.site_name}` : 'at this site';
      const county = w.county ? ` (${w.county} Co.)` : '';
      // Show the applicable limits, each clearly named — the human MCL and the
      // ecological aquatic-life benchmark are different standards.
      const limBits = [];
      if (w.mcl != null) limBits.push(`<span data-gloss="MCL">MCL ${w.mcl}</span>`);
      if (w.benchmark != null) limBits.push(`<span data-gloss="aquatic-life benchmark">aquatic-life ${w.benchmark}</span>`);
      const maxLine = (w.detections && w.max_value != null)
        ? `<div class="tci-row"><span class="tci-k">Highest detection</span><span class="tci-v">${w.max_value} ${w.unit || ''}${limBits.length ? ` · limits ${limBits.join(' / ')} µg/L` : ''}</span></div>`
        : '';
      const mclWarn = w.mcl_exceedances
        ? `<div class="tci-carc">⚠ Exceeded the human <b>drinking-water limit (MCL)</b> in ${w.mcl_exceedances} sample${w.mcl_exceedances === 1 ? '' : 's'}</div>` : '';
      const benchWarn = w.benchmark_exceedances
        ? `<div class="tci-bench-warn">⚠ Exceeded the <b data-gloss="aquatic-life benchmark">aquatic-life benchmark</b> in ${w.benchmark_exceedances} sample${w.benchmark_exceedances === 1 ? '' : 's'} — potential ecological harm, not a drinking-water violation</div>` : '';
      const benchNote = w.benchmark_exceedances
        ? `<p class="muted small tci-bench-note">Aquatic-life benchmarks measure risk to fish, insects, and aquatic organisms. They are different from — and often much lower than — human drinking-water limits (MCLs). Exceeding one does not mean drinking water is unsafe, but indicates potential ecological harm. Source: ${w.benchmark_source || 'USGS/EPA aquatic-life benchmark'}.</p>` : '';
      waterBlock =
        '<div class="tci-sub2">Water monitoring</div>'
        + `<div class="tci-row"><span class="tci-k">${w.detections} of ${w.samples} samples</span>`
        + `<span class="tci-v">detected ${where}${county}</span></div>`
        + mclWarn + benchWarn + maxLine + benchNote;
    }

    // Real PubChem enrichment (cached): description, formula/weight, synonyms, CID.
    const pc = d.pubchem || null;
    const subtitle = flags || (d.is_pesticide ? 'agricultural pesticide' : '');
    const syn = (pc && pc.synonyms && pc.synonyms.length)
      ? `<div class="tci-syn"><span class="tci-k">Also known as</span> ${pc.synonyms.slice(0, 4).join(', ')}</div>` : '';
    const chips = [];
    if (pc && pc.molecular_formula) chips.push(`<span class="tci-chip">${pc.molecular_formula}</span>`);
    if (pc && pc.molecular_weight) chips.push(`<span class="tci-chip">${(Math.round(pc.molecular_weight * 100) / 100)} g/mol</span>`);
    if (d.cas) chips.push(`<span class="tci-chip">CAS ${d.cas}</span>`);
    const chipRow = chips.length ? `<div class="tci-chips">${chips.join('')}</div>` : '';
    // Prefer PubChem's real plain-language description; fall back to the curated
    // hazard blurb if PubChem had none.
    const descText = (pc && pc.description) ? pc.description : (p.what || '');
    const pubLink = pc
      ? `<a href="${pc.url}" target="_blank" rel="noopener">Full profile on PubChem — CID ${pc.cid} ↗</a>` : '';
    const srcBits = ['Hazard classes: EPA / IARC', 'Pesticide use: USGS', 'Industrial releases: EPA TRI'];
    if (d.water) srcBits.push('Water monitoring: Water Quality Portal (USGS/EPA)');
    if (pc) srcBits.unshift('Description &amp; properties: PubChem (NCBI)'
      + (pc.description_source ? ` via ${pc.description_source}` : ''));
    const noInfo = !descText && !p.uses && !p.health && !p.carcinogen && !(pc && pc.molecular_formula);
    return `
      <div class="tci-head">
        <h3>${d.name}</h3>
        ${subtitle ? `<div class="tci-sub">${subtitle}</div>` : ''}
      </div>
      ${chipRow}
      ${syn}
      ${descText ? `<p class="tci-what">${descText}</p>` : ''}
      ${line('Used for', p.uses)}
      ${line('Health', p.health)}
      ${p.carcinogen ? `<div class="tci-carc">⚠ ${p.carcinogen}</div>` : ''}
      ${line('Typical pathways', p.pathways)}
      ${pestBlock}
      ${triBlock}
      ${waterBlock}
      ${pubLink ? `<div class="tci-pubchem">${pubLink}</div>` : ''}
      ${noInfo ? '<p class="muted small tci-nolookup">We couldn\'t find a public description for this chemical — the figures above are from the data we actually have (EPA / IARC / USGS). See PubChem for more.</p>' : ''}
      <div class="tri-note">${srcBits.join(' · ')}.</div>
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
    ['npl', 'state', 'deleted'].forEach((k) => {
      $(`contam-f-${k}`).addEventListener('change', (e) => {
        state.contam.filters[k] = e.target.checked;
        renderContamMarkers(); renderContamZones();
      });
    });

    // PFAS overlay (dedicated first-class layer) + per-kind sub-toggles.
    const pfasToggle = $('pfas-sites');
    if (pfasToggle) {
      pfasToggle.addEventListener('change', async (e) => {
        state.pfas.showSites = e.target.checked;
        if (e.target.checked) await loadPfas();
        renderPfas();
      });
    }
    ['site', 'aoi', 'surface_water', 'pws', 'fish', 'potw'].forEach((k) => {
      const cb = $(`pfas-f-${k}`);
      if (cb) cb.addEventListener('change', (e) => {
        state.pfas.filters[k] = e.target.checked;
        renderPfas();
      });
    });

    // Underground storage tanks (lazy per-category load) + sub-toggles.
    const ustToggle = $('ust-sites');
    if (ustToggle) {
      ustToggle.addEventListener('change', async (e) => {
        state.ust.showSites = e.target.checked;
        if (e.target.checked) { loading(true); await ensureUstLoaded(); loading(false); }
        renderUst();
      });
    }
    ['leaking_open', 'leaking_closed', 'licensed'].forEach((k) => {
      const cb = $(`ust-f-${k}`);
      if (cb) cb.addEventListener('change', async (e) => {
        state.ust.filters[k] = e.target.checked;
        if (e.target.checked && state.ust.showSites && !state.ust.loaded[k]) {
          loading(true); await loadUstCategory(k); loading(false);
        }
        renderUst();
      });
    });

    $('contam-zones').addEventListener('change', async (e) => {
      state.contam.showZones = e.target.checked;
      if (e.target.checked) await loadContamination();
      renderContamZones(); renderMarkerKeys();
    });

    // Spraying-programs directory (independent overlay).
    const sprayToggle = $('spraying-programs');
    if (sprayToggle) {
      sprayToggle.addEventListener('change', async (e) => {
        state.spraying.showMarkers = e.target.checked;
        if (e.target.checked) await loadSprayingPrograms();
        renderSprayingMarkers();
      });
    }

    // Coal ash (CCR) sites directory (independent overlay).
    const coalAshToggle = $('coal-ash-sites');
    if (coalAshToggle) {
      coalAshToggle.addEventListener('change', async (e) => {
        state.coalAsh.showMarkers = e.target.checked;
        if (e.target.checked) await loadCoalAsh();
        renderCoalAshMarkers();
      });
    }

    // TRI industrial-facility markers (independent overlay).
    $('tri-sites').addEventListener('change', async (e) => {
      state.tri.showSites = e.target.checked;
      await refreshTriSites();
    });

    // Landfills & waste facilities (independent overlay) + type filters.
    const lfToggle = $('landfill-sites');
    if (lfToggle) {
      lfToggle.addEventListener('change', async (e) => {
        state.landfill.showSites = e.target.checked;
        if (e.target.checked) await loadLandfills();
        renderLandfillMarkers();
      });
    }
    ['msw', 'industrial', 'coal_ash', 'hazardous'].forEach((k) => {
      const cb = $(`landfill-f-${k}`);
      if (cb) cb.addEventListener('change', (e) => {
        state.landfill.filters[k] = e.target.checked;
        renderLandfillMarkers();
      });
    });

    // Golf courses (independent overlay) + ownership filters.
    const golfToggle = $('golf-sites');
    if (golfToggle) {
      golfToggle.addEventListener('change', async (e) => {
        state.golf.showSites = e.target.checked;
        if (e.target.checked) await loadGolf();
        renderGolfCourses();
      });
    }
    ['municipal', 'private', 'unknown'].forEach((k) => {
      const cb = $(`golf-f-${k}`);
      if (cb) cb.addEventListener('change', (e) => {
        state.golf.filters[k] = e.target.checked;
        renderGolfCourses();
      });
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

    setupAddressReport();

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

  // ========================================================================
  // "Check an address" — homebuyer environmental report (see /api/address-report)
  // ========================================================================
  // Privacy: the address is POSTed in the request body (never a URL), used to
  // fetch the report, and never persisted client-side either — we keep only the
  // returned report (coordinates + findings), not the typed address beyond the
  // input box. Clearing the input on close removes it.
  let _report = null;          // last report payload (for the reopen button)
  let _reportLayer = null;     // L.layerGroup holding the pin + 1/3/5-mile rings

  // Filename-safe "Environmental Report for <address>" for the print/PDF title.
  // Strips characters invalid in filenames, collapses whitespace, caps length.
  function _reportPrintTitle() {
    const addr = _report && _report.location && _report.location.matched_address;
    if (!addr) return null;
    const clean = String(addr)
      .replace(/[\/\\:*?"<>|]/g, ' ')       // characters invalid in filenames
      .replace(/[\x00-\x1f\x7f]/g, ' ')       // control characters
      .replace(/\s+/g, ' ')                  // collapse whitespace
      .trim()
      .slice(0, 120)                         // reasonable length cap
      .trim();
    return clean ? `Environmental Report for ${clean}` : null;
  }

  const _rEsc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  function openAddressModal() {
    hide($('report-modal'));
    hide($('report-reopen'));
    show($('address-modal'));
    const inp = $('address-input');
    if (inp) { inp.value = ''; setTimeout(() => inp.focus(), 30); }
    hide($('address-error'));
  }

  function setupAddressReport() {
    $('open-address').addEventListener('click', openAddressModal);
    const countyBtn = $('county-check-address');
    if (countyBtn) countyBtn.addEventListener('click', openAddressModal);
    $('address-close').addEventListener('click', () => hide($('address-modal')));
    $('address-modal').addEventListener('click', (e) => {
      if (e.target.id === 'address-modal') hide($('address-modal'));
    });
    $('address-form').addEventListener('submit', submitAddress);
    $('report-close').addEventListener('click', closeReport);
    $('report-modal').addEventListener('click', (e) => {
      if (e.target.id === 'report-modal') closeReport();
    });
    $('report-print').addEventListener('click', () => window.print());
    // Collapsible caveats (e.g. the heating-oil-tank blind-spot note) default to
    // collapsed on screen but must appear in the printed / saved PDF. Force any
    // <details> in the report open for printing, then restore screen state.
    const _printOpened = [];
    let _savedTitle = null;
    // The browser derives the default PDF/print filename from document.title, so
    // give it a meaningful name for the duration of the print only. The matched
    // address lives client-side already (in the rendered report); this is a local
    // save on the user's own machine and the title is restored on afterprint, so
    // the address never lingers in the tab — and it is still never stored,
    // logged, or placed in any URL server-side.
    window.addEventListener('beforeprint', () => {
      _printOpened.length = 0;
      const t = _reportPrintTitle();
      if (t) { _savedTitle = document.title; document.title = t; }
      const body = $('report-body');
      if (!body) return;
      body.querySelectorAll('details:not([open])').forEach((d) => {
        d.open = true; _printOpened.push(d);
      });
    });
    window.addEventListener('afterprint', () => {
      _printOpened.forEach((d) => { d.open = false; });
      _printOpened.length = 0;
      if (_savedTitle != null) { document.title = _savedTitle; _savedTitle = null; }
    });
    $('report-reopen').addEventListener('click', () => {
      if (_report) { show($('report-modal')); hide($('report-reopen')); }
    });
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      if (!$('address-modal').classList.contains('hidden')) hide($('address-modal'));
      // Fully dismiss the report (and its map graphics) whether it's showing or
      // minimised to the floating "View report" button.
      else if (!$('report-modal').classList.contains('hidden')
               || !$('report-reopen').classList.contains('hidden')) closeReport();
    });
    // Delegated "Show on map →" buttons inside the report.
    document.addEventListener('click', (e) => {
      const b = e.target.closest && e.target.closest('.rpt-focus');
      if (!b) return;
      e.preventDefault();
      focusFinding(b.getAttribute('data-layer'), b.getAttribute('data-id'),
        parseFloat(b.getAttribute('data-lat')), parseFloat(b.getAttribute('data-lng')));
    });
  }

  async function submitAddress(e) {
    e.preventDefault();
    const inp = $('address-input');
    const address = (inp.value || '').trim();
    const errEl = $('address-error');
    hide(errEl);
    if (address.length < 3) {
      errEl.textContent = 'Please enter a street address, city, and ZIP.';
      show(errEl); return;
    }
    const go = $('address-go');
    go.disabled = true; go.textContent = 'Generating…';
    loading(true);
    try {
      const res = await apiPost('/api/address-report', { address });
      if (!res.ok) {
        const msg = (res.data && res.data.message)
          || (res.status === 429 ? 'Too many lookups — please wait a few minutes.'
              : "Couldn't generate a report. Please try again.");
        errEl.textContent = msg; show(errEl);
        return;
      }
      const d = res.data;
      if (d.in_michigan === false) {
        errEl.textContent = d.message || 'That address is outside Michigan.';
        show(errEl);
        return;
      }
      _report = d;
      hide($('address-modal'));
      renderReport(d);
    } catch (err) {
      errEl.textContent = 'Network error — please try again.'; show(errEl);
    } finally {
      loading(false);
      go.disabled = false; go.textContent = 'Generate report';
    }
  }

  // ---- map: pin + 1/3/5-mile rings -------------------------------------------
  // A single persistent layer group holds the pin + rings. We clear it (not
  // recreate it) before each draw and remove it entirely on close, so nothing
  // ever stacks or ghosts.
  function _reportGroup() {
    if (!_reportLayer) _reportLayer = L.layerGroup();
    if (!state.map.hasLayer(_reportLayer)) _reportLayer.addTo(state.map);
    return _reportLayer;
  }

  function clearReportGraphics() {
    if (_reportLayer) {
      _reportLayer.clearLayers();
      state.map.removeLayer(_reportLayer);
      _reportLayer = null;
    }
  }

  function drawReportMap(loc) {
    const g = _reportGroup();
    g.clearLayers();                                 // wipe any prior pin/rings
    const ringColors = ['#f85149', '#e8873c', '#d9b458'];
    [5, 3, 1].forEach((mi) => {
      L.circle([loc.lat, loc.lng], {
        radius: mi * 1609.34, color: ringColors[[5, 3, 1].indexOf(mi)],
        weight: 1.4, opacity: 0.8, fill: false, dashArray: '5 5',
      }).bindTooltip(`${mi} mi`, { permanent: false }).addTo(g);
    });
    L.marker([loc.lat, loc.lng], {
      icon: L.divIcon({ className: 'report-pin-icon',
        html: '<div class="report-pin">📍</div>', iconSize: [30, 30], iconAnchor: [15, 30] }),
      zIndexOffset: 1000,
    }).addTo(g);
    const bounds = L.latLng(loc.lat, loc.lng).toBounds(11000);   // ~5 mi + margin
    state.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 12 });
  }

  // Fully dismiss the report: hide the modal + floating button, remove the pin
  // and rings from the map, and reset the report state. The "Show on map →"
  // buttons only open existing overlay popups (they add no separate graphics),
  // so there is nothing extra to clean up beyond closing any open popup.
  function closeReport() {
    hide($('report-modal'));
    hide($('report-reopen'));
    clearReportGraphics();
    if (state.map && state.map.closePopup) state.map.closePopup();
    _report = null;
  }

  // ---- focus a finding: enable its layer, fly, open its popup ----------------
  const _FOCUS = {
    contamination: { cb: 'contam-sites', grp: () => state.contam.markers },
    tri: { cb: 'tri-sites', grp: () => state.tri.markers,
           byId: (id) => state.tri.markerById && state.tri.markerById.get(id) },
    landfill: { cb: 'landfill-sites', grp: () => state.landfill.markers },
    water: { cb: 'wq-sites', grp: () => state.water.sitesLayer },
    golf: { cb: 'golf-sites', grp: () => state.golf.markers },
    spraying: { cb: 'spraying-programs', grp: () => state.spraying.markers },
    coal_ash: { cb: 'coal-ash-sites', grp: () => state.coalAsh.markers },
    pfas: { cb: 'pfas-sites', grp: () => state.pfas.markers },
    pfas_water: { cb: 'pfas-sites', grp: () => state.pfas.markers },
    // UST: enabling the layer loads open-leaking; ust_other needs the closed &
    // licensed categories toggled on so their (lazy) markers exist to open.
    ust_open: { cb: 'ust-sites', grp: () => state.ust.markers },
    ust_other: { cb: 'ust-sites', grp: () => state.ust.markers,
                 subCbs: ['ust-f-leaking_closed', 'ust-f-licensed'] },
  };

  function _openInGroup(group, lat, lng) {
    if (!group || !group.eachLayer) return false;
    let best = null, bd = Infinity;
    group.eachLayer((m) => {
      const ll = m.getLatLng ? m.getLatLng()
        : (m.getBounds ? m.getBounds().getCenter() : null);
      if (!ll) return;
      const d = state.map.distance(ll, [lat, lng]);
      if (d < bd) { bd = d; best = m; }
    });
    if (best && bd < 150) {
      if (group.zoomToShowLayer) group.zoomToShowLayer(best, () => best.openPopup());
      else best.openPopup();
      return true;
    }
    return false;
  }

  async function focusFinding(layer, id, lat, lng) {
    const cfg = _FOCUS[layer];
    hide($('report-modal'));
    if (_report) show($('report-reopen'));
    if (!cfg || Number.isNaN(lat)) return;
    const cb = $(cfg.cb);
    if (cb && !cb.checked) { cb.checked = true; cb.dispatchEvent(new Event('change', { bubbles: true })); }
    for (const subId of (cfg.subCbs || [])) {
      const sub = $(subId);
      if (sub && !sub.checked) { sub.checked = true; sub.dispatchEvent(new Event('change', { bubbles: true })); }
    }
    // give the layer a moment to fetch + render its markers (lazy categories too)
    await new Promise((r) => setTimeout(r, cfg.subCbs ? 1100 : 650));
    state.map.setView([lat, lng], Math.max(state.map.getZoom(), 13));
    const direct = cfg.byId && id ? cfg.byId(id) : null;
    if (direct) {
      const grp = cfg.grp && cfg.grp();
      if (grp && grp.zoomToShowLayer) grp.zoomToShowLayer(direct, () => direct.openPopup());
      else direct.openPopup();
      return;
    }
    if (!_openInGroup(cfg.grp && cfg.grp(), lat, lng)) {
      // couldn't match a specific marker; leave the map centered on the pin
      setTimeout(() => _openInGroup(cfg.grp && cfg.grp(), lat, lng), 500);
    }
  }

  // ---- report rendering ------------------------------------------------------
  const _SEV_LABEL = {
    exceeds_mcl: 'exceeds drinking-water MCL (human health)',
    exceeds_benchmark: 'exceeds aquatic-life benchmark (ecological)',
    detected: 'pesticides detected, within limits',
    tested_no_detect: 'tested, none detected',
    no_data: 'no results on record',
  };
  const _TREND = { up: '▲ rising', down: '▼ falling', flat: '▬ stable' };

  function _mi(d) { return (d == null) ? '—' : `${d} mi`; }

  function _ringChips(rings) {
    return `<span class="rpt-rings">`
      + [1, 3, 5].map((r) => `<span class="rpt-ring"><b>${rings[String(r)] || 0}</b> within ${r} mi</span>`).join('')
      + `</span>`;
  }

  function _focusBtn(it) {
    if (it.lat == null || it.lng == null) return '';
    return `<button type="button" class="rpt-focus" data-layer="${it.layer}"`
      + ` data-id="${_rEsc(it.id)}" data-lat="${it.lat}" data-lng="${it.lng}">Show on map →</button>`;
  }

  function _itemFigures(layer, it) {
    if (layer === 'contamination') {
      return `${it.npl ? '<span class="rpt-tag npl">NPL Superfund</span> ' : ''}`
        + `${_rEsc(it.status || '')}${it.hrs_score ? ` · HRS ${it.hrs_score}` : ''}`;
    }
    if (layer === 'tri') {
      return `${it.latest_release_lbs != null ? `<b>${fmtLbs(it.latest_release_lbs)}</b> released`
        + `${it.latest_year ? ` (${it.latest_year})` : ''} · ${_TREND[it.trend] || ''}` : ''}`
        + `${it.sector ? ` · ${_rEsc(it.sector)}` : ''}`;
    }
    if (layer === 'landfill') {
      return `${_rEsc(it.type_label || it.category || '')}${it.status ? ` · ${_rEsc(it.status)}` : ''}`;
    }
    if (layer === 'coal_ash') {
      const unlined = it.unlined ? ' <span class="rpt-tag" style="background:#f85149;color:#0d1117">⚠ unlined unit</span>' : '';
      return `${_rEsc(it.status_label || '')} · ${_rEsc(it.unit_type_label || '')}`
        + `${it.operator ? ` · ${_rEsc(it.operator)}` : ''}${unlined}`;
    }
    if (layer === 'water') {
      const comps = (it.top_compounds || []).map((c) => chemLink(c)).join(', ');
      return `<span class="rpt-sev sev-${it.severity}">${_SEV_LABEL[it.severity] || it.severity}</span>`
        + `${it.mcl_exceedances ? ` · ${it.mcl_exceedances} MCL exceedance(s)` : ''}`
        + `${it.benchmark_exceedances ? ` · ${it.benchmark_exceedances} benchmark exceedance(s)` : ''}`
        + `${comps ? `<div class="rpt-comps">detected: ${comps}</div>` : ''}`;
    }
    if (layer === 'golf') {
      return `${_rEsc(it.ownership_class === 'municipal' ? 'public/municipal'
        : it.ownership_class || '')}${it.acres ? ` · ~${Math.round(it.acres)} acres` : ''}`
        + ` · <span class="muted">turf-pesticide land use</span>`;
    }
    if (layer === 'pfas') {
      const tag = it.kind === 'aoi'
        ? '<span class="rpt-tag" style="background:#e8873c;color:#0d1117">Area of Interest</span>'
        : '<span class="rpt-tag" style="background:#c62f34;color:#fff">Confirmed site</span>';
      const wells = it.residential_wells
        ? ` · residential wells sampled: <b>${_rEsc(it.residential_wells)}</b>` : '';
      return `${tag}${it.site_type ? ' ' + _rEsc(it.site_type) : ''}${wells}`;
    }
    if (layer === 'pfas_water') {
      const det = it.detected || {};
      const key = det.PFOS != null ? `PFOS ${det.PFOS} ppt` : (it.max_ppt != null ? `max ${it.max_ppt} ppt` : '');
      return `${_rEsc(it.waterbody || 'surface water')}${key ? ` · <b>${key}</b>` : ''}`
        + `${it.sample_date ? ` <span class="muted">(${_rEsc(it.sample_date)})</span>` : ''}`;
    }
    if (layer === 'ust_open') {
      const plain = _ustClassPlain(it.classification);
      const cls = it.classification
        ? ` · <b>${_rEsc(it.classification)}</b>${plain ? ` <span class="muted">(${_rEsc(plain)})</span>` : ''}` : '';
      const rel = it.open_release ? ` · ${it.open_release} open release${it.open_release > 1 ? 's' : ''}` : '';
      const approx = it.address_matched ? ' <span class="muted">(approx. location)</span>' : '';
      return `<span class="rpt-tag" style="background:#c62f34;color:#fff">Open leaking release</span>`
        + `${_rEsc(it.address || '')}${rel}${cls}${approx}`;
    }
    if (layer === 'ust_other') {
      const isClosed = it.category === 'leaking_closed';
      const tag = isClosed
        ? '<span class="rpt-tag" style="background:#c9973b;color:#0d1117">Closed / remediated release</span>'
        : '<span class="rpt-tag" style="background:#7f8b99;color:#0d1117">Licensed tank (no release)</span>';
      const approx = it.address_matched ? ' <span class="muted">(approx. location)</span>' : '';
      return `${tag}${_rEsc(it.address || '')}${approx}`;
    }
    return '';
  }

  function _nearBlock(key, label, icon, block, emptyNote) {
    if (!block) return '';
    const items = block.within || [];
    let body;
    if (items.length) {
      body = `<ul class="rpt-list">` + items.map((it) =>
        `<li><div class="rpt-item-h"><span class="rpt-item-name">${_rEsc(it.name)}</span>`
        + `<span class="rpt-dist">${it.distance_mi} mi ${it.direction || ''}</span></div>`
        + `<div class="rpt-item-fig">${_itemFigures(key, it)}</div>${_focusBtn(it)}</li>`).join('') + `</ul>`;
    } else if (block.nearest) {
      const n = block.nearest;
      body = `<p class="rpt-none">${emptyNote} Nearest is <b>${_rEsc(n.name)}</b>, `
        + `${n.distance_mi} mi ${n.direction || ''} away. `
        + `<span class="rpt-figinline">${_itemFigures(key, n)}</span> ${_focusBtn(n)}</p>`;
    } else {
      body = `<p class="rpt-none">None mapped in Michigan for this layer.</p>`;
    }
    return `<div class="rpt-layer"><div class="rpt-layer-h"><span>${icon} ${label}</span>`
      + `${_ringChips(block.rings)}</div>${body}</div>`;
  }

  // Plain-language explainer for the UST section of the report: what a leaking
  // release nearby actually means, the vapor-intrusion pathway (the one people
  // don't know about), and concrete next steps — framed as "what this is and what
  // to ask about", not alarmist. Expanded by default when an OPEN release is
  // mapped nearby; collapsed context otherwise.
  function _ustReportNote(near) {
    const open = near && near.ust_open;
    const other = near && near.ust_other;
    const hasOpen = !!(open && open.within && open.within.length);
    const hasAny = hasOpen || (open && open.nearest)
      || (other && ((other.within && other.within.length) || other.nearest));
    if (!hasAny) return '';
    const head = hasOpen
      ? 'A leaking storage-tank release is mapped near this address — here’s what that means'
      : 'About the storage tanks near this address';
    return `<details class="rpt-ustnote"${hasOpen ? ' open' : ''}>
      <summary><span class="rpt-ustnote-tag">${hasOpen ? 'Worth understanding' : 'Context'}</span> ${head}</summary>
      <div class="rpt-ustnote-body">
        <p>${hasOpen
          ? 'An <b>open</b> release means a buried fuel tank leaked and cleanup is <b>not finished</b>. '
            + 'Underground tanks are common at gas stations, auto shops, and industrial sites — when one '
            + 'leaks, petroleum enters the soil and can spread through groundwater.'
          : 'These are buried fuel tanks. A <b>closed</b> release leaked in the past and the state agreed '
            + 'cleanup criteria were met (though some sites close with residual contamination left under '
            + 'restrictions); a <b>licensed</b> tank has no reported leak.'}</p>
        <p><b>Why proximity matters — vapor intrusion.</b> Beyond drinking water, petroleum `
      + `<span data-gloss="vapor intrusion">vapors</span> can rise through soil into the basements and `
      + `crawlspaces of nearby buildings and affect indoor air — <b>even if the home is on municipal `
      + `water and no one touches the soil</b>. That is why a leaking release close to a property is worth `
      + `understanding, not just a private-well concern.</p>
        ${_ustContaminantsHtml()}
        <p class="rpt-ustnote-do"><b>What you can do:</b></p>
        <ul class="rpt-ustnote-actions">
          <li>Ask whether a <b>vapor intrusion</b> assessment has been done for the property or the release site.</li>
          <li>If the home is on a <b>private well</b>, ask about — or arrange — water testing for petroleum compounds like ${chemLink('Benzene')} and ${chemLink('MTBE')}.</li>
          <li>Consult an <b>environmental professional</b> for a property-specific evaluation — this map shows the release location, not the conditions at any one house.</li>
        </ul>
        <p class="rpt-note muted small">Source: Michigan EGLE. Distances are straight-line from the geocoded point; the actual plume direction and extent depend on site-specific geology and groundwater flow.</p>
      </div>
    </details>`;
  }

  // Prominent blind-spot caveat for the UST section: EGLE's tank data covers
  // REGULATED commercial tanks only. Unregistered residential heating-oil tanks
  // (buried in the yard or aboveground in a basement) were never required to be
  // registered, so a clean UST result above does NOT mean there is no tank on
  // this parcel. Always shown, precisely because empty UST findings are when the
  // wrong conclusion is easiest to draw. Collapsible on screen; forced open for
  // print/PDF via the beforeprint handler.
  function _heatingOilTankNote() {
    return `<details class="rpt-oiltank">
      <summary><span class="rpt-oiltank-tag">Data blind spot</span> `
      + `Residential heating-oil tanks are <b>not</b> in this data — a clean result above doesn't rule one out</summary>
      <div class="rpt-oiltank-body">
        <p><b>What the data can't see.</b> The storage-tank findings above come from EGLE's dataset of `
      + `<em>regulated commercial</em> tanks. Residential home-heating-oil tanks — whether buried in the yard `
      + `or sitting aboveground in a basement — generally were never required to be registered or regulated, `
      + `so they don't appear in that dataset or anywhere else in this app. <b>Seeing no tanks nearby does not `
      + `mean there is no tank on this property</b> — the most likely buried tank on a given parcel is exactly `
      + `the kind this data can't show.</p>
        <p><b>Why it matters.</b> Heating oil was common in Michigan homes built before natural-gas service `
      + `expanded, especially pre-1970s construction. When homes converted to gas, buried tanks were often `
      + `<b>abandoned in place</b> rather than removed — and over the decades they can corrode and leak. `
      + `Cleaning up a leaking residential tank can be expensive, and it is typically <b>not covered by a `
      + `standard homeowner's insurance policy</b>.</p>
        <p><b>What you can actually do:</b></p>
        <ul class="rpt-oiltank-actions">
          <li><b>Ask the seller directly</b> whether the property ever had — or still has — a heating-oil tank, `
      + `and whether one was removed or abandoned in place (ask for documentation if so).</li>
          <li><b>Look for physical signs:</b> a fill pipe or vent pipe poking out of the ground or an exterior `
      + `wall; capped or unexplained copper/steel lines in the basement; an unexplained patched or sunken area `
      + `in the yard; or an old furnace that was converted from oil.</li>
          <li><b>Consider a tank sweep.</b> Surveying a property for buried tanks with metal detection or `
      + `ground-penetrating radar is a standard service — environmental contractors, and some home inspectors, `
      + `offer it, and it can find a tank before you buy.</li>
          <li><b>Check the age of the home.</b> Risk tracks with pre-natural-gas-era construction, so older `
      + `houses warrant a closer look.</li>
        </ul>
        <p class="rpt-oiltank-src">Michigan guidance: `
      + `<a href="https://www.michigan.gov/egle/faqs/land-and-property/storage-tanks" target="_blank" rel="noopener">EGLE — FAQ: Home Heating Oil Tanks</a> `
      + `(see also EGLE's <a href="https://www.michigan.gov/egle/-/media/Project/Websites/egle/Documents/Programs/RRD/LUST/home-heating-oil-tank-brochure.pdf" target="_blank" rel="noopener">Home Heating Oil Tanks regulatory guide</a>).</p>
      </div>
    </details>`;
  }

  function _sprayingBlock(list) {
    if (!list || !list.length) {
      return `<div class="rpt-layer"><div class="rpt-layer-h"><span>🚁 Spraying programs</span></div>`
        + `<p class="rpt-none">No organized spraying programs are documented covering this area. `
        + `(Private agricultural spraying is not in any public directory.)</p></div>`;
    }
    const body = `<ul class="rpt-list">` + list.map((p) =>
      `<li><div class="rpt-item-h"><span class="rpt-item-name">${_rEsc(p.name)}</span>`
      + `<span class="rpt-dist">${p.scope === 'statewide' ? 'statewide'
        : (p.distance_mi != null ? `${p.distance_mi} mi ${p.direction || ''}` : _rEsc(p.area || ''))}</span></div>`
      + `<div class="rpt-item-fig">${_rEsc(p.area || '')}${p.url
        ? ` · <a href="${_rEsc(p.url)}" target="_blank" rel="noopener">details →</a>` : ''}</div></li>`).join('') + `</ul>`;
    return `<div class="rpt-layer"><div class="rpt-layer-h"><span>🚁 Spraying programs</span></div>`
      + `<p class="rpt-note">A directory of organized programs whose coverage includes this area — `
      + `not a live spray-date feed, and not a complete record of all spraying.</p>${body}</div>`;
  }

  function _pctSpan(pct) {
    if (pct == null) return '';
    const dir = pct > 0 ? 'above' : pct < 0 ? 'below' : 'at';
    const cls = pct > 0 ? 'hi' : pct < 0 ? 'lo' : '';
    return `<span class="rpt-vs ${cls}">${Math.abs(pct)}% ${dir} state avg</span>`;
  }

  function _countyContextHtml(ctx, county) {
    const p = ctx.pesticide || {};
    const rows = [];
    rows.push(`<div class="rpt-cc"><span class="k">Agricultural pesticide use (${ctx.pesticide_year || 'latest'})</span>`
      + `<span class="v">${p.total_lbs != null ? `${p.total_lbs.toLocaleString()} lbs` : 'n/a'}`
      + `${p.per_acre_lbs != null ? ` · ${p.per_acre_lbs} lbs/cropland acre` : ''}`
      + `${p.statewide_rank ? ` · rank #${p.statewide_rank} of ${p.counties_ranked}` : ''}</span>`
      + `<div class="rpt-cc-note muted small">${_rEsc(p.note || '')}</div></div>`);
    if (ctx.cancer_nhl) {
      const c = ctx.cancer_nhl;
      rows.push(`<div class="rpt-cc"><span class="k">${_rEsc(c.label)}</span>`
        + `<span class="v">${c.suppressed ? 'suppressed (too few cases to report)'
          : `${c.county_rate}/100k vs ${c.state_rate}/100k state`} ${_pctSpan(c.pct_vs_state)}</span></div>`);
    }
    if (ctx.respiratory_asthma) {
      const r = ctx.respiratory_asthma;
      rows.push(`<div class="rpt-cc"><span class="k">${_rEsc(r.label)} (${r.year})</span>`
        + `<span class="v">${r.county_rate} vs ${r.state_rate} state ${_pctSpan(r.pct_vs_state)}</span></div>`);
    }
    const dn = ctx.density || {};
    rows.push(`<div class="rpt-cc"><span class="k">Documented sites in county</span>`
      + `<span class="v">${dn.contamination_sites || 0} contamination (${dn.npl_sites || 0} Superfund NPL) · `
      + `${dn.landfills || 0} landfills (${dn.hazardous_landfills || 0} hazardous) · `
      + `${dn.tri_facilities || 0} TRI facilities${dn.tri_total_lbs != null
        ? `, ${fmtLbs(dn.tri_total_lbs)} released ${dn.tri_year || ''}` : ''}</span></div>`);
    return `<div class="rpt-section rpt-county"><h3>County-wide context `
      + `<span class="rpt-h-note">describes all of ${_rEsc(county)} County — NOT this specific address</span></h3>`
      + rows.join('') + `</div>`;
  }

  function _monitoringHtml(m) {
    let html = `<div class="rpt-cov">`;
    if (m.warning) html += `<div class="rpt-warn">⚠ ${_rEsc(m.warning)}</div>`;
    html += `<div class="rpt-cov-title">Monitoring coverage <span class="muted small">— how well-documented this area is</span></div>`;
    html += `<ul class="rpt-cov-list">`
      + `<li>Nearest water-monitoring site: <b>${_mi(m.nearest_water_site_mi)}</b>`
      + `${m.nearest_water_site_name ? ` (${_rEsc(m.nearest_water_site_name)})` : ''} · ${m.county_water_sites} in county</li>`
      + `<li>Nearest mapped contamination site: <b>${_mi(m.nearest_contamination_mi)}</b> · `
      + `nearest landfill: <b>${_mi(m.nearest_landfill_mi)}</b></li>`
      + `<li>County has TRI-reporting industrial facilities: <b>${m.county_has_tri ? 'yes' : 'no'}</b></li>`
      + `</ul>`;
    if (m.notes && m.notes.length) {
      html += `<ul class="rpt-cov-notes">` + m.notes.map((n) => `<li>${_rEsc(n)}</li>`).join('') + `</ul>`;
    }
    return html + `</div>`;
  }

  function _downwindHtml(dw) {
    if (!dw) return '';
    let body;
    if (dw.upwind && dw.upwind.length) {
      body = `<p>Prevailing growing-season (Apr–Sep) winds are from the <b>${dw.prevailing_from}</b>, `
        + `placing this address <b>downwind</b> of:</p><ul class="rpt-list">`
        + dw.upwind.map((u) => `<li><div class="rpt-item-h"><span class="rpt-item-name">${_rEsc(u.name)}</span>`
          + `<span class="rpt-dist">${u.distance_mi} mi</span></div>${_focusBtn(u)}</li>`).join('') + `</ul>`;
    } else {
      body = `<p>Prevailing growing-season winds are from the <b>${dw.prevailing_from}</b>. `
        + `No mapped TRI facilities or landfills within 5 miles sit directly upwind.</p>`;
    }
    return `<div class="rpt-section rpt-downwind"><h3>Downwind check</h3>${body}`
      + `<p class="rpt-note muted small">${_rEsc(dw.note)} Nearest wind station: `
      + `${_rEsc(dw.station || '')}${dw.station_mi != null ? ` (${dw.station_mi} mi)` : ''}.</p></div>`;
  }

  // Air toxics section of the homebuyer report. Framed hard as AREA-LEVEL context
  // with EPA's screening caveats up top — never a property-specific finding.
  function _airToxicsReportHtml(a) {
    if (!a) return '';
    const vs = a.vs_mi_pct;
    const vsTxt = vs != null
      ? `${Math.abs(vs)}% ${vs >= 0 ? 'above' : 'below'} the Michigan average` : '';
    const bars = (a.sources || []).map((s) => {   // all eight categories
      const pctTxt = (s.pct < 1 && s.risk > 0) ? '<1%' : s.pct + '%';
      const lbl = s.gloss
        ? `<span class="gloss-term" data-gloss="${_rEsc(s.gloss)}" tabindex="0">${_rEsc(s.label)}</span>`
        : _rEsc(s.label);
      return `<div class="atx-bar"><span class="atx-bar-l">${lbl}</span>`
        + `<span class="atx-bar-t"><span style="width:${s.pct}%;background:${s.color || '#8a94a3'}"></span></span>`
        + `<span class="atx-bar-v">${pctTxt}</span></div>`;
    }).join('');
    const polls = (a.pollutants || []).slice(0, 5).map((p) => chemLink(p[0])).join(', ');
    const caveats = (a.caveats || []).map((c) => `<li>${_rEsc(c)}</li>`).join('');
    return `<div class="rpt-section rpt-airtox">
      <h3>Modeled air toxics risk <span class="rpt-h-note">area-level screening estimate — NOT a measurement at this address</span></h3>
      <div class="rpt-warn">⚠ This is a <b>modeled screening estimate</b> for the surrounding census tract, <b>not measured air</b> at this property. EPA designed it to identify areas for further study, <b>not</b> to determine risk at a specific home or school. It assumes 70 years of continuous <b>outdoor</b> exposure; indoor air, where people spend most of their time, is not included.</div>
      <div class="rpt-airtox-fig"><b>${a.total_risk}</b> in a million${vsTxt ? ` <span class="rpt-vs ${vs >= 0 ? 'hi' : 'lo'}">${vsTxt}</span>` : ''}</div>
      <p class="muted small">Census tract ${_rEsc(a.tract_geoid)} · Michigan average ${a.mi_avg} · national average ${a.national_avg}. ${_rEsc(a.assessment)}.</p>
      ${a.dominant ? `<p>Risk here is modeled as driven mostly by <b>${_rEsc(a.dominant.label)}</b> (${a.dominant.pct}% of the total)${_atxDriverClause(a.dominant.key)}.</p>` : ''}
      <div class="atx-share-note">${ATX_SHARE_NOTE}</div>
      <div class="atx-bars">${bars}</div>
      ${polls ? `<p class="small"><span class="muted">Top modeled pollutants:</span> ${polls}</p>` : ''}
      <ul class="rpt-airtox-caveats">${caveats}</ul>
      <p class="rpt-note muted small">EPA cautions against comparing across assessment years (methods change), so this reflects one assessment, not a trend. Source: EPA NATA / AirToxScreen.</p>
    </div>`;
  }

  function renderReport(d) {
    const loc = d.location;
    const r = d.rating;
    const catOrder = [['contamination', 'Contamination'], ['industrial', 'Industrial (TRI)'],
      ['waste', 'Waste / landfills'], ['water', 'Water'], ['pesticides', 'Agric. pesticides']];
    const cats = catOrder.map(([k, lbl]) => {
      const c = r.categories[k];
      return `<div class="rpt-cat band-${c.band}"><span class="rpt-cat-lbl">${lbl}</span>`
        + `<span class="rpt-cat-band">${c.label}</span></div>`;
    }).join('');

    const near = d.near;
    const nearHtml =
      _nearBlock('contamination', 'Contamination / Superfund sites', '☣', near.contamination,
        'No contamination sites within 5 miles.')
      + _nearBlock('tri', 'TRI industrial facilities', '🏭', near.tri,
        'No TRI facilities within 5 miles.')
      + _nearBlock('landfill', 'Landfills & waste facilities', '🗑', near.landfill,
        'No active landfills within 5 miles.')
      + _nearBlock('coal_ash', 'Coal ash (CCR) sites', '⚫', near.coal_ash,
        'No coal ash (coal combustion residuals) sites within 5 miles.')
      + _nearBlock('water', 'Water monitoring sites', '💧', near.water,
        'No water-monitoring sites within 5 miles.')
      + _nearBlock('ust_open', 'Leaking storage tanks — OPEN releases', '⚠', near.ust_open,
        'No open leaking underground storage-tank releases within 5 miles.')
      + _nearBlock('ust_other', 'Other storage tanks (closed releases & licensed)', '⛽', near.ust_other,
        'No closed-release or licensed storage tanks within 5 miles.')
      + _ustReportNote(near)
      + _heatingOilTankNote()
      + _nearBlock('pfas', 'PFAS sites & Areas of Interest', '⚠', near.pfas,
        'No PFAS sites or Areas of Interest within 5 miles — but investigation is ongoing, so this does not mean absence of PFAS.')
      + _nearBlock('pfas_water', 'PFAS surface-water sampling', '💧', near.pfas_water,
        'No PFAS surface-water sampling within 5 miles.')
      + _nearBlock('golf', 'Golf courses (turf pesticide use)', '⛳', near.golf,
        'No golf courses within 5 miles.')
      + _sprayingBlock(near.spraying);

    const html =
      `<div class="rpt">
        <div class="rpt-head">
          <h2 id="report-title">Environmental report</h2>
          <div class="rpt-addr">${_rEsc(loc.matched_address || '')}</div>
          <div class="rpt-sub">${_rEsc(loc.county || '')} County · geocoded via ${_rEsc(loc.geocoder || '')} · ${_rEsc(d.generated || '')}</div>
        </div>

        <div class="rpt-rating band-${r.overall}">
          <div class="rpt-rating-top">Overall: <b>${_rEsc(r.overall_label)}</b></div>
          <div class="rpt-rating-adj">${_rEsc(r.adjacent_note)}</div>
        </div>
        <div class="rpt-catgrid">${cats}</div>

        ${_monitoringHtml(d.monitoring)}

        <div class="rpt-section">
          <h3>Near this address <span class="rpt-h-note">measured straight-line distances from the geocoded point</span></h3>
          ${nearHtml}
        </div>

        ${_downwindHtml(d.downwind)}

        ${_airToxicsReportHtml(d.air_toxics)}

        ${_countyContextHtml(d.county_context, loc.county)}

        <div class="rpt-disc">
          <h3>Important limitations</h3>
          <ul>${(d.disclaimers || []).map((x) => `<li>${_rEsc(x)}</li>`).join('')}</ul>
        </div>
        <div class="rpt-src">
          <h4>Data sources</h4>
          <ul>${(d.sources || []).map((x) => `<li>${_rEsc(x)}</li>`).join('')}</ul>
        </div>
      </div>`;

    $('report-body').innerHTML = html;
    $('report-body').scrollTop = 0;
    hide($('report-reopen'));
    show($('report-modal'));
    drawReportMap(loc);
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
      applyLayerFilterVisibility();   // hide non-active layers' filters at startup
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
    // Tap an info icon — or any tappable gloss term (e.g. air-toxics source
    // categories) — on touch devices to toggle its definition.
    document.addEventListener('click', (e) => {
      const el = e.target.closest('.info-i, .gloss-term');
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

    // First-time "how to use the map" hint (mobile only, dismissible + remembered).
    const HINT_KEY = 'pm_maphint_dismissed_v1';
    updateMapHint();
    let hintDismissed = false;
    try { hintDismissed = localStorage.getItem(HINT_KEY) === '1'; } catch (e) {}
    if (!hintDismissed) body.classList.add('show-map-hint');
    const hintX = $('map-hint-x');
    if (hintX) hintX.addEventListener('click', () => {
      body.classList.remove('show-map-hint');
      try { localStorage.setItem(HINT_KEY, '1'); } catch (e) {}
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

  // Any element with class "chem-link" (chemical/compound name) opens the shared
  // chemical-info modal. Delegated in the CAPTURE phase + stopPropagation so a
  // click inside a Leaflet popup or a filter row doesn't also trigger that
  // element's own handler (e.g. the statewide list's compound filter).
  function setupChemLinks() {
    const activate = (e) => {
      const link = e.target.closest && e.target.closest('.chem-link');
      if (!link) return;
      if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      e.stopPropagation();
      openChemInfo(decodeURIComponent(link.dataset.chem || ''), {
        fips: link.dataset.chemFips || '',
        site: link.dataset.chemSite ? decodeURIComponent(link.dataset.chemSite) : '',
      });
    };
    document.addEventListener('click', activate, true);
    document.addEventListener('keydown', activate, true);
  }

  document.addEventListener('DOMContentLoaded', () => {
    setupTooltips();
    setupMobileUI();
    setupChemLinks();
    wireIntro();
    maybeShowIntroOnFirstVisit();
    boot();
  });
})();
