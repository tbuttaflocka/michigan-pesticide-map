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
    idLines.push(`  EGLE license / site ID:  ${f.license_id || '[not listed — see EGLE record]'}`);
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
        <div class="foia-guide" id="foia-guide"></div>
        <a class="foia-submit" id="foia-submit" target="_blank" rel="noopener"></a>
        <a class="foia-official small" id="foia-official" target="_blank" rel="noopener"></a>
      </div>`;
    document.body.appendChild(modal);
    els = {
      close: $('foia-close'), title: $('foia-title'), subject: $('foia-subject'),
      explainer: $('foia-explainer'), copy: $('foia-copy'), text: $('foia-text'),
      hint: $('foia-hint'), guide: $('foia-guide'), submit: $('foia-submit'),
      official: $('foia-official'),
    };
    els.close.addEventListener('click', close);
    modal.addEventListener('click', (e) => { if (e.target === modal) close(); });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !modal.classList.contains('hidden')) close();
    });
    els.copy.addEventListener('click', copyText);
  }

  function copyText() {
    const ta = els.text;
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, ta.value.length);   // iOS/mobile select-all
    const done = () => {
      const b = els.copy;
      const old = b.textContent;
      b.textContent = 'Copied ✓';
      b.classList.add('copied');
      setTimeout(() => { b.textContent = old; b.classList.remove('copied'); }, 1600);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(ta.value).then(done).catch(() => {
        try { document.execCommand('copy'); done(); } catch (e) { /* leave selected */ }
      });
    } else {
      try { document.execCommand('copy'); done(); } catch (e) { /* leave selected */ }
    }
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

  // open(opts):
  //   title?, explainer?, subject (facility name), facility, records, authority,
  //   agency (profile), periodYears?
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
