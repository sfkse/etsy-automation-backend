// Live 3xN pricing matrix under the Pricing Strategy tab.
// Port of backend/src/modules/listings/variation_builder.py::_compute_price
// (finish offset -> optional per-inch scaling). Multi-count not shown here.
(function () {
  'use strict';

  const SAMPLE_LENGTHS = [16, 18, 20, 22, 24, 26, 28];

  function num(id, fallback) {
    const el = document.getElementById(id);
    if (!el) return fallback;
    const v = parseFloat(el.value);
    return Number.isFinite(v) ? v : fallback;
  }

  function parseFinishOffsets() {
    const el = document.getElementById('pf-finish-offsets');
    if (!el) return {};
    try {
      const parsed = JSON.parse(el.value || '{}');
      return (parsed && typeof parsed === 'object') ? parsed : {};
    } catch (_) {
      return {};
    }
  }

  function computeCell(costDollars, baseMultiplier, offsetsPct, finish, lengthBase, perInchPct, length) {
    let price = costDollars * baseMultiplier;
    const off = Number(offsetsPct[finish] || 0);
    price *= 1 + off / 100;
    if (length !== null && length !== undefined) {
      price *= 1 + ((length - lengthBase) * perInchPct) / 100;
    }
    return price;
  }

  function render() {
    const header = document.getElementById('pp-header-row');
    const body = document.getElementById('pp-body');
    if (!header || !body) return;

    const cost = num('pp-cost', 10);
    const baseMultiplier = num('pf-base-multiplier', 3.0);
    const lengthBase = num('pf-length-base', 18);
    const perInchPct = num('pf-per-inch-pct', 3);
    const offsets = parseFinishOffsets();
    const finishes = Object.keys(offsets);

    header.querySelectorAll('th.pp-length').forEach(n => n.remove());
    for (const L of SAMPLE_LENGTHS) {
      const th = document.createElement('th');
      th.className = 'pp-length text-end';
      th.textContent = `${L}"`;
      header.appendChild(th);
    }

    body.innerHTML = '';
    if (finishes.length === 0) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td colspan="${SAMPLE_LENGTHS.length + 1}" class="text-muted small">Add finishes to <code>finish_offsets_pct</code> to see a preview.</td>`;
      body.appendChild(tr);
      return;
    }

    for (const finish of finishes) {
      const tr = document.createElement('tr');
      const th = document.createElement('th');
      th.scope = 'row';
      th.textContent = finish;
      tr.appendChild(th);
      for (const L of SAMPLE_LENGTHS) {
        const td = document.createElement('td');
        td.className = 'text-end font-monospace';
        const price = computeCell(cost, baseMultiplier, offsets, finish, lengthBase, perInchPct, L);
        td.textContent = `$${price.toFixed(2)}`;
        tr.appendChild(td);
      }
      body.appendChild(tr);
    }
  }

  function attach() {
    const form = document.getElementById('pricing-form');
    if (!form) return;
    form.addEventListener('input', render);
    const cost = document.getElementById('pp-cost');
    if (cost) cost.addEventListener('input', render);
    render();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attach);
  } else {
    attach();
  }
})();
