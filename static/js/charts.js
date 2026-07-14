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

  function scatter(canvasId, datasets) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
      type: 'scatter',
      data: { datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'top', labels: { boxWidth: 12, padding: 12 } },
          tooltip: {
            callbacks: {
              label: (c) => {
                const r = c.raw;
                return r.label
                  ? `${r.label}: x=${fmtKg(r.x)}, y=${r.y}`
                  : `x=${fmtKg(r.x)}, y=${r.y}`;
              },
            },
          },
        },
        scales: {
          x: { type: 'linear', title: { display: true, text: 'pesticide use (lbs)' },
               grid: { color: 'rgba(154,164,178,.10)' },
               ticks: { callback: (v) => fmtLbs(v) } },
          y: { title: { display: true, text: 'CWD positives' },
               grid: { color: 'rgba(154,164,178,.10)' },
               beginAtZero: true,
               ticks: { precision: 0 } },
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
    fmtKg, fmtLbs, horizontalBar, doughnut, lineChart, scatter, groupedBar,
    verticalBar, destroyIfExists, CATEGORY_COLORS,
  };
})();
