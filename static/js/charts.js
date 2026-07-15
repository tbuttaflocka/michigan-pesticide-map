// Chart.js global dark-theme defaults + small render helpers.
(function () {
  if (!window.Chart) { console.warn('Chart.js not loaded'); return; }
  Chart.defaults.color = '#9aa4b2';
  Chart.defaults.font.family =
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, "Helvetica Neue", Arial, sans-serif';
  Chart.defaults.font.size = 11.5;
  Chart.defaults.borderColor = 'rgba(154, 164, 178, 0.2)';
  Chart.defaults.plugins.legend.labels.boxWidth = 10;
  Chart.defaults.plugins.legend.labels.boxHeight = 10;

  const CATEGORY_COLORS = {
    herbicide:        '#3fb950',
    insecticide:      '#f85149',
    fungicide:        '#58a6ff',
    growth_regulator: '#bc8cff',
    other:            '#f0b429',
  };

  function fmtLbs(v) {
    if (v == null) return '—';
    const n = Number(v);
    if (n >= 1e9)  return (n / 1e9).toFixed(2) + ' B lbs';
    if (n >= 1e6)  return (n / 1e6).toFixed(2) + ' M lbs';
    if (n >= 1e3)  return (n / 1e3).toFixed(1) + ' k lbs';
    return n.toFixed(1) + ' lbs';
  }
  // Back-compat alias so older code paths still work.
  const fmtKg = fmtLbs;

  function destroyIfExists(chart) {
    if (chart && typeof chart.destroy === 'function') chart.destroy();
  }

  function horizontalBar(canvasId, labels, values, colors) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          data: values,
          backgroundColor: colors || '#3fb950',
          borderRadius: 4,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: { label: (c) => fmtKg(c.parsed.x) },
          },
        },
        scales: {
          x: { grid: { color: 'rgba(154,164,178,.12)' }, ticks: { callback: (v) => fmtKg(v) } },
          y: { grid: { display: false } },
        },
      },
    });
  }

  function doughnut(canvasId, labels, values, colors) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: labels,
        datasets: [{ data: values, backgroundColor: colors, borderColor: '#141a23', borderWidth: 2 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '58%',
        plugins: {
          legend: { position: 'bottom', labels: { padding: 8 } },
          tooltip: { callbacks: { label: (c) => `${c.label}: ${fmtKg(c.parsed)}` } },
        },
      },
    });
  }

  function lineChart(canvasId, labels, values, color) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          data: values,
          borderColor: color || '#3fb950',
          backgroundColor: 'rgba(63,185,80,.12)',
          fill: true,
          tension: 0.25,
          pointRadius: 2,
          pointHoverRadius: 5,
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (c) => fmtKg(c.parsed.y) } },
        },
        scales: {
          x: { grid: { color: 'rgba(154,164,178,.10)' } },
          y: { grid: { color: 'rgba(154,164,178,.10)' }, ticks: { callback: (v) => fmtKg(v) } },
        },
      },
    });
  }

  function fmtCount(v) {
    if (v == null) return '—';
    return Number(v).toLocaleString();
  }
  function fmtNum(v) {
    if (v == null) return '—';
    const n = Number(v);
    return (Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(1));
  }

  // Enhanced scatter.
  //   opts: {
  //     xLabel, yLabel   — plain-English axis titles (with units)
  //     xName, yName     — short names used inside the hover tooltip
  //     xFmt, yFmt       — value formatters (default lbs on x, number on y)
  //     yBeginAtZero     — default true
  //   }
  // Point objects may carry {x, y, label (county), ur ('Urban'/'Rural')} which
  // the hover tooltip surfaces. Datasets of type 'line' (the trend line) are
  // excluded from the point tooltip.
  function scatter(canvasId, datasets, opts) {
    opts = opts || {};
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    const xFmt = opts.xFmt || fmtLbs;
    const yFmt = opts.yFmt || fmtNum;
    const xName = opts.xName || 'Pesticide';
    const yName = opts.yName || 'Value';
    return new Chart(ctx, {
      type: 'scatter',
      data: { datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'top', labels: { boxWidth: 12, padding: 12, usePointStyle: true } },
          tooltip: {
            padding: 10,
            titleFont: { size: 12.5 },
            bodyFont: { size: 11.5 },
            callbacks: {
              title: (items) => {
                const it = items[0];
                if (!it || it.dataset.type === 'line') return '';
                const r = it.raw;
                return r && r.label ? r.label + ' County' : '';
              },
              label: (c) => {
                if (c.dataset.type === 'line') return null;   // hide trend endpoints
                const r = c.raw;
                const lines = [
                  `${xName}: ${xFmt(r.x)}`,
                  `${yName}: ${yFmt(r.y)}`,
                ];
                if (r.ur) lines.push(r.ur + ' county');
                return lines;
              },
            },
          },
        },
        scales: {
          x: { type: 'linear',
               title: { display: true, text: opts.xLabel || 'pesticide use (lbs)',
                        color: '#c7d0da', font: { size: 12 } },
               grid: { color: 'rgba(154,164,178,.10)' },
               ticks: { callback: (v) => xFmt(v) } },
          y: { title: { display: true, text: opts.yLabel || 'value',
                        color: '#c7d0da', font: { size: 12 } },
               grid: { color: 'rgba(154,164,178,.10)' },
               beginAtZero: opts.yBeginAtZero !== false,
               ticks: { callback: (v) => yFmt(v) } },
        },
      },
    });
  }

  function verticalBar(canvasId, labels, values, colors, yLabel) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{ data: values, backgroundColor: colors || '#f0862f', borderRadius: 4 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (c) => (c.parsed.y == null ? '—' : c.parsed.y.toFixed(1) + ' /100k') } },
        },
        scales: {
          x: { grid: { display: false } },
          y: { grid: { color: 'rgba(154,164,178,.10)' },
               title: { display: !!yLabel, text: yLabel || '' },
               ticks: { callback: (v) => Number(v).toFixed(0) } },
        },
      },
    });
  }

  function groupedBar(canvasId, labels, posValues, negValues, sigFlags) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    const starred = labels.map((l, i) => sigFlags[i] ? `★ ${l}` : l);
    return new Chart(ctx, {
      type: 'bar',
      data: {
        labels: starred,
        datasets: [
          { label: 'CWD-positive counties',
            data: posValues, backgroundColor: '#f85149', borderRadius: 4 },
          { label: 'CWD-negative counties',
            data: negValues, backgroundColor: '#3fb950', borderRadius: 4 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'top', labels: { boxWidth: 12, padding: 12 } },
          tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmtKg(c.parsed.y)}` } },
        },
        scales: {
          x: { grid: { display: false } },
          y: { grid: { color: 'rgba(154,164,178,.10)' },
               ticks: { callback: (v) => fmtKg(v) } },
        },
      },
    });
  }

  window.PMCharts = {
    fmtKg, fmtLbs, fmtCount, fmtNum, horizontalBar, doughnut, lineChart,
    scatter, groupedBar, verticalBar, destroyIfExists, CATEGORY_COLORS,
  };
})();
