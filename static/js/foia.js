// Reusable "request records via FOIA" helper, exposed as window.PMFoia.
//
// Some data the app maps (e.g. landfill groundwater/leachate/air monitoring) is
// collected by an agency but not published online — it's obtainable by public-
// records request. This component turns any such record into an actionable,
// copy-pasteable FOIA request plus the real, verified filing instructions for
// the agency. It is deliberately layer-agnostic: the caller supplies the
// facility fields, the record categories to request, and an agency profile, so
// the same modal can be reused by future layers.
//
// Loaded before app.js. No dependencies.
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  let modal = null;      // built once, reused
  let els = null;        // cached child refs

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Default record window: the most recent N calendar years through today.
  function defaultPeriod(years) {
    const now = new Date();
    const start = now.getFullYear() - (years || 5);
    return `January ${start} to the present (${now.getFullYear()})`;
  }

  function today() {
    try {
      return new Date().toLocaleDateString('en-US',
        { year: 'numeric', month: 'long', day: 'numeric' });
    } catch (e) { return ''; }
  }

  // Build a ready-to-send FOIA letter from structured inputs. Generic: the
  // facility block and record list adapt to whatever the caller passes.
  //   facility: {name, operator, license_id, address, city, county, type_label}
  //   records:  [string, ...]   authority: string   agency: profile
  //   period:   string (editable by the user afterwards)
  function buildRequest(opts) {
    const f = opts.facility || {};
    const agency = opts.agency || {};
    const records = opts.records || [];
    const period = opts.period || defaultPeriod(opts.periodYears || 5);
    const statute = agency.statute || 'the state Freedom of Information Act';

    const locBits = [f.address, f.city,
      (f.county ? f.county + ' County' : ''), 'MI'].filter(Boolean);
    const idLines = [];
    idLines.push(`  Facility:  ${f.name || '[facility name]'}`);
    if (f.operator && f.operator !== f.name) idLines.push(`  Operator:  ${f.operator}`);
    const licLabel = f.license_label || 'EGLE license / site ID';
    idLines.push(`  ${licLabel}:  ${f.license_id || '[not listed — see EGLE record]'}`);
    if (f.alt_id) idLines.push(`  ${f.alt_id_label || 'Additional facility ID'}:  ${f.alt_id}`);
    if (locBits.length > 1) idLines.push(`  Address:  ${locBits.join(', ')}`);
    if (f.type_label) idLines.push(`  Facility type:  ${f.type_label}`);

    const recLines = records.map((r, i) => `  ${i + 1}. ${r}`).join('\n');

    const to = agency.mail_block ||
      'Michigan Department of Environment, Great Lakes, and Energy\nATTN: FOIA Coordinator';

    return [
      today(),
      '',
      to,
      '',
      `Re: Freedom of Information Act request — ${f.name || 'facility records'}` +
        (f.license_id ? ` (EGLE ID ${f.license_id})` : ''),
      '',
      'To the FOIA Coordinator,',
      '',
      `Under ${statute}, I request copies of the following public records for ` +
        `the facility identified below` +
        (opts.authority ? `, which is regulated under ${opts.authority}` : '') + ':',
      '',
      idLines.join('\n'),
      '',
      `Records requested, for the period ${period}:`,
      recLines,
      '',
      'Please provide records in electronic format (PDF) where available. I ' +
        'request a waiver or reduction of any fees under MCL 15.234(1) because ' +
        'these records concern public health and the environment and their ' +
        'disclosure primarily benefits the general public. If fees cannot be ' +
        'waived and will exceed $25, please contact me with an itemized ' +
        'estimate before proceeding.',
      '',
      'If any portion of this request is denied, please cite the specific FOIA ' +
        'exemption relied upon.',
      '',
      'Thank you for your assistance.',
      '',
      'Sincerely,',
      '[Your name]',
      '[Your email address]',
      '[Your mailing address]',
      '[Your phone number]',
    ].join('\n');
  }

  function ensureModal() {
    if (modal) return;
    modal = document.createElement('div');
    modal.id = 'foia-modal';
    modal.className = 'modal hidden';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-labelledby', 'foia-title');
    modal.innerHTML = `
      <div class="modal-card foia-card">
        <button class="close" id="foia-close" aria-label="Close">×</button>
        <h2 id="foia-title">Request monitoring records (FOIA)</h2>
        <p class="foia-subject" id="foia-subject"></p>
        <p class="foia-explainer muted small" id="foia-explainer"></p>
        <div class="foia-req-head">
          <label for="foia-text" class="foia-req-label">Your request <span class="muted">(editable)</span></label>
          <button class="foia-copy" id="foia-copy" type="button">Copy request text</button>
        </div>
        <textarea class="foia-text" id="foia-text" spellcheck="false" aria-label="FOIA request text"></textarea>
        <p class="foia-hint muted small" id="foia-hint"></p>
        <div class="foia-fields hidden" id="foia-fields">
          <h3 class="foia-fields-h">Other required form fields</h3>
          <p class="foia-fields-lead muted small">EGLE's Public Records Center asks for the site's
            address, city, ZIP, and county in separate boxes. Copy each straight into its field.</p>
          <div class="foia-field-list" id="foia-field-list"></div>
          <p class="foia-fields-note small" id="foia-fields-note"></p>
        </div>
        <div class="foia-guide" id="foia-guide"></div>
        <a class="foia-submit" id="foia-submit" target="_blank" rel="noopener"></a>
        <a class="foia-official small" id="foia-official" target="_blank" rel="noopener"></a>
      </div>`;
    document.body.appendChild(modal);
    els = {
      close: $('foia-close'), title: $('foia-title'), subject: $('foia-subject'),
      explainer: $('foia-explainer'), copy: $('foia-copy'), text: $('foia-text'),
      hint: $('foia-hint'), fields: $('foia-fields'),
      fieldList: $('foia-field-list'), fieldsNote: $('foia-fields-note'),
      guide: $('foia-guide'), submit: $('foia-submit'), official: $('foia-official'),
    };
    els.fieldValues = [];   // copy-payloads for the per-field buttons, by index
    els.close.addEventListener('click', close);
    modal.addEventListener('click', (e) => { if (e.target === modal) close(); });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !modal.classList.contains('hidden')) close();
    });
    els.copy.addEventListener('click', copyText);
    // Delegated so it covers the per-field buttons rebuilt on every open().
    els.fieldList.addEventListener('click', (e) => {
      const b = e.target.closest && e.target.closest('.foia-field-copy');
      if (!b) return;
      const idx = parseInt(b.getAttribute('data-fidx'), 10);
      copyString(els.fieldValues[idx] || '', b);
    });
  }

  // Flash a button to "Copied ✓" then restore. Remembers the original label so
  // repeated clicks don't stick on the checkmark.
  function flashCopied(btn) {
    if (!btn) return;
    if (btn.getAttribute('data-label') == null) btn.setAttribute('data-label', btn.textContent);
    const label = btn.getAttribute('data-label');
    btn.textContent = 'Copied ✓';
    btn.classList.add('copied');
    clearTimeout(btn._t);
    btn._t = setTimeout(() => { btn.textContent = label; btn.classList.remove('copied'); }, 1600);
  }

  // Copy an arbitrary string. Uses the async Clipboard API where available and
  // falls back to a temporary <textarea> + execCommand so it also works on older
  // mobile browsers and non-secure contexts (where navigator.clipboard is absent).
  function copyString(str, btn) {
    const done = () => flashCopied(btn);
    const fallback = () => {
      const t = document.createElement('textarea');
      t.value = str;
      t.setAttribute('readonly', '');
      // Keep it in-viewport but invisible: iOS won't copy off-screen selections.
      t.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;'
        + 'padding:0;border:0;opacity:0;';
      document.body.appendChild(t);
      t.focus();
      t.select();
      t.setSelectionRange(0, str.length);
      let ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      document.body.removeChild(t);
      if (ok) done();
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(str).then(done).catch(fallback);
    } else {
      fallback();
    }
  }

  function copyText() {
    const ta = els.text;
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, ta.value.length);   // iOS/mobile select-all
    copyString(ta.value, els.copy);
  }

  // Render the per-field quick-copy block from [{label, value}, ...]. Fields with
  // an empty value are dropped (e.g. Part 111 sites carry no ZIP in the EGLE feed).
  function renderFields(fields, note) {
    els.fieldValues = [];
    const rows = (fields || []).filter((f) => f && f.value != null
      && String(f.value).trim() !== '');
    if (!rows.length) {
      els.fields.classList.add('hidden');
      els.fieldList.innerHTML = '';
      return;
    }
    els.fieldList.innerHTML = rows.map((f, i) => {
      els.fieldValues.push(String(f.value));
      return `<div class="foia-field">
        <div class="foia-field-main">
          <span class="foia-field-label">${esc(f.label)}</span>
          <span class="foia-field-value">${esc(f.value)}</span>
        </div>
        <button class="foia-field-copy" type="button" data-fidx="${i}"
          aria-label="Copy ${esc(f.label)}">Copy</button>
      </div>`;
    }).join('');
    els.fieldsNote.textContent = note || '';
    els.fieldsNote.style.display = note ? '' : 'none';
    els.fields.classList.remove('hidden');
  }

  function guideHtml(agency) {
    if (!agency) return '';
    const parts = [`<h3>How to file with ${esc(agency.agency || 'the agency')}</h3>`];
    if (agency.methods && agency.methods.length) {
      parts.push('<div class="foia-gb"><span class="k">Submit:</span><ul>' +
        agency.methods.map((m) => `<li>${esc(m)}</li>`).join('') + '</ul></div>');
    }
    if (agency.timeline) {
      parts.push(`<div class="foia-gb"><span class="k">Response time:</span> ${esc(agency.timeline)}</div>`);
    }
    if (agency.fees) {
      parts.push(`<div class="foia-gb"><span class="k">Fees:</span> ${esc(agency.fees)}</div>`);
    }
    if (agency.contact_email) {
      parts.push(`<div class="foia-gb"><span class="k">Questions:</span> ` +
        `<a href="mailto:${esc(agency.contact_email)}">${esc(agency.contact_email)}</a></div>`);
    }
    parts.push('<p class="foia-verify muted small">Filing details are from ' +
      `${esc(agency.agency || 'the agency')}'s official FOIA page — confirm the ` +
      'current specifics there before filing.</p>');
    return parts.join('');
  }

  // Sensible per-field quick-copy list derived from a facility, so a caller can
  // just pass `facility` and get address/city/zip/county/ID fields for free.
  // Labels match EGLE's Public Records Center form boxes. A caller can override
  // by passing an explicit `fields` array instead.
  function defaultFields(f) {
    f = f || {};
    const out = [
      { label: 'Address of Requested Site', value: f.address },
      { label: 'City', value: f.city },
      { label: 'Zip Code', value: f.zip },
      { label: 'County (Select County)', value: f.county },
    ];
    if (f.license_id) {
      out.push({ label: f.license_label || 'Facility ID', value: f.license_id });
    }
    if (f.alt_id) {
      out.push({ label: f.alt_id_label || 'Additional facility ID', value: f.alt_id });
    }
    return out;
  }

  // open(opts):
  //   title?, explainer?, subject (facility name), facility, records, authority,
  //   agency (profile), periodYears?, fields? (override), formNote?
  function open(opts) {
    ensureModal();
    const agency = opts.agency || {};
    els.title.textContent = opts.title || 'Request monitoring records (FOIA)';
    els.subject.textContent = opts.subject || '';
    els.subject.style.display = opts.subject ? '' : 'none';
    els.explainer.textContent = opts.explainer || agency.explainer || '';
    els.text.value = opts.requestText || buildRequest(opts);
    els.hint.textContent = 'The request above is a starting point — edit the time ' +
      'period, the records listed, and your contact details before sending.';
    renderFields(opts.fields || defaultFields(opts.facility),
      opts.formNote || (agency && agency.form_note));
    els.guide.innerHTML = guideHtml(agency);
    if (agency.submit_url) {
      els.submit.href = agency.submit_url;
      els.submit.textContent = `Open ${agency.submit_label || 'the FOIA request portal'} →`;
      els.submit.style.display = '';
    } else { els.submit.style.display = 'none'; }
    if (agency.source_url) {
      els.official.href = agency.source_url;
      els.official.textContent = `${agency.agency || 'Agency'} FOIA page & procedures →`;
      els.official.style.display = '';
    } else { els.official.style.display = 'none'; }
    modal.classList.remove('hidden');
    els.text.scrollTop = 0;
  }

  function close() { if (modal) modal.classList.add('hidden'); }

  window.PMFoia = { open, close, buildRequest, defaultPeriod };
})();
