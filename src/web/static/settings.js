// Settings UI — serialize any form.settings-form into JSON and POST to its data-settings-endpoint.
// Field type coercion is driven by input `type` + optional `data-array` / `data-json` attributes.
(function () {
  'use strict';

  function coerceValue(el) {
    if (el.type === 'checkbox') return el.checked;
    const raw = el.value;
    if (el.dataset.json === 'true') {
      const s = (raw || '').trim();
      if (!s) return null;
      return JSON.parse(s);
    }
    if (el.dataset.array === 'csv') {
      return raw.split(',').map(s => s.trim()).filter(Boolean);
    }
    if (el.dataset.array === 'csv-num') {
      return raw.split(',').map(s => s.trim()).filter(Boolean).map(Number);
    }
    if (el.dataset.array === 'multiselect' && el.multiple) {
      return Array.from(el.selectedOptions).map(o => o.value);
    }
    if (el.type === 'number') {
      if (raw === '' || raw === null) return null;
      return Number(raw);
    }
    return raw;
  }

  function serializeForm(form) {
    const payload = {};
    const seen = new Set();
    for (const el of form.elements) {
      if (!el.name) continue;
      if (el.disabled) continue;
      if (seen.has(el.name)) continue;
      seen.add(el.name);
      try {
        payload[el.name] = coerceValue(el);
      } catch (e) {
        throw new Error(`Invalid value for "${el.name}": ${e.message}`);
      }
    }
    return payload;
  }

  function toast(message, kind) {
    const container = document.getElementById('settings-toast-container');
    if (!container) { alert(message); return; }
    const div = document.createElement('div');
    div.className = `alert alert-${kind === 'error' ? 'danger' : 'success'} shadow-sm`;
    div.style.minWidth = '260px';
    div.textContent = message;
    container.appendChild(div);
    setTimeout(() => div.remove(), 3200);
  }

  async function submitForm(form) {
    let endpoint = form.dataset.settingsEndpoint;
    if (!endpoint && form.dataset.settingsEndpointTemplate) {
      const nameField = form.dataset.settingsNameField || 'name';
      const nameEl = form.querySelector(`[name="${nameField}"]`);
      const nameVal = nameEl ? String(nameEl.value || '').trim() : '';
      if (!nameVal) { toast(`Provide a ${nameField}`, 'error'); return; }
      endpoint = form.dataset.settingsEndpointTemplate.replace('{name}', encodeURIComponent(nameVal));
    }
    if (!endpoint) return;

    let payload;
    try {
      payload = serializeForm(form);
    } catch (e) {
      toast(e.message, 'error');
      return;
    }

    try {
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        const text = await resp.text();
        toast(`Save failed (${resp.status}): ${text.slice(0, 200)}`, 'error');
        return;
      }
      toast('Saved.', 'ok');
    } catch (e) {
      toast('Network error: ' + e.message, 'error');
    }
  }

  document.addEventListener('submit', function (ev) {
    const form = ev.target.closest('form.settings-form');
    if (!form) return;
    ev.preventDefault();
    submitForm(form);
  });

  document.addEventListener('click', async function (ev) {
    const btn = ev.target.closest('.delete-section-btn');
    if (!btn) return;
    const name = btn.dataset.sectionName;
    if (!name) return;
    if (!confirm(`Delete section "${name}"?`)) return;
    try {
      const resp = await fetch(`/settings/shop-sections/${encodeURIComponent(name)}`, { method: 'DELETE' });
      if (!resp.ok) {
        toast(`Delete failed (${resp.status})`, 'error');
        return;
      }
      const row = btn.closest('tr');
      if (row) row.remove();
      toast(`Deleted "${name}".`, 'ok');
    } catch (e) {
      toast('Network error: ' + e.message, 'error');
    }
  });
})();
