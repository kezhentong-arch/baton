// Calendar popover: both the timeline and the day list open it to pick a day instead of typing one.
// No dependencies: one month per grid, weeks start on Monday, a dot under days with entries, today outlined,
// the selected day filled; click outside or press Esc to close.
// Usage: Calendar.open(anchorEl, { selected: 'YYYY-MM-DD', base: '/sample', onPick(iso) })
(() => {
  const T = window.T;
  const WD = T('cal_wd').split(',');
  let pop = null, state = null;
  const pad = n => String(n).padStart(2, '0');
  const isoOf = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}`;
  function close() { if (pop) { pop.remove(); pop = null; state = null; document.removeEventListener('pointerdown', onOutside, true); document.removeEventListener('keydown', onKey); } }
  function onOutside(ev) { if (pop && !pop.contains(ev.target) && ev.target !== state.anchor && !state.anchor.contains(ev.target)) close(); }
  function onKey(ev) { if (ev.key === 'Escape') close(); }
  async function counts(y, m) {
    const from = isoOf(y, m, 1), to = isoOf(y, m, new Date(y, m + 1, 0).getDate());
    try { const r = await fetch(`${state.base}/api/days?from=${from}&to=${to}`); if (!r.ok) throw new Error(await r.text()); return await r.json(); }
    catch (e) { console.warn('calendar: could not load entry counts', e); return { counts: {}, today: '' }; } // without counts there are just no dots; the calendar still works
  }
  async function render() {
    const { y, m, selected } = state;
    const data = await counts(y, m);
    if (!pop) return;
    const todayIso = data.today || '';
    const first = new Date(y, m, 1), lead = (first.getDay() + 6) % 7, days = new Date(y, m + 1, 0).getDate();
    let cells = '';
    for (let i = 0; i < lead; i++) cells += '<i></i>';
    for (let d = 1; d <= days; d++) {
      const iso = isoOf(y, m, d), n = data.counts[iso] || 0;
      cells += `<button type="button" data-day="${iso}" class="${iso === selected ? 'sel' : ''}${iso === todayIso ? ' today' : ''}${iso > todayIso && todayIso ? ' future' : ''}" title="${n ? T('cal_entries', { n }) : ''}">${d}${n ? '<b></b>' : ''}</button>`;
    }
    pop.innerHTML = `<div class="cal-head"><button type="button" class="chip ghost small" data-nav="-1" title="${T('cal_prev')}">‹</button><span>${T('cal_month', { y, m: String(m + 1).padStart(2, '0') })}</span><button type="button" class="chip ghost small" data-nav="1" title="${T('cal_next')}">›</button></div>` +
      `<div class="cal-wd">${WD.map(w => `<span>${w}</span>`).join('')}</div><div class="cal-grid">${cells}</div>` +
      `<div class="cal-foot"><button type="button" class="chip small" data-today="1">${T('today')}</button><span class="dim small">${T('cal_hint')}</span></div>`;
    pop.querySelectorAll('[data-nav]').forEach(b => b.addEventListener('click', () => { const nm = m + +b.dataset.nav; state.y = y + Math.floor(nm / 12); state.m = (nm + 12) % 12; render(); }));
    pop.querySelector('[data-today]').addEventListener('click', () => pick(todayIso || isoOf(new Date().getFullYear(), new Date().getMonth(), new Date().getDate())));
    pop.querySelectorAll('[data-day]').forEach(b => b.addEventListener('click', () => pick(b.dataset.day)));
  }
  function pick(iso) { const cb = state.onPick; close(); cb(iso); }
  function place(anchor) { // positioned once in document coordinates (right under the button) and then scrolls with the page; chasing the button made it jump
    const r = anchor.getBoundingClientRect(), w = 272;
    pop.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left)) + window.scrollX + 'px';
    pop.style.top = r.bottom + 6 + window.scrollY + 'px';
  }
  window.Calendar = {
    open(anchor, opts) {
      if (pop && state && state.anchor === anchor) return close();
      close();
      const sel = opts.selected || '';
      const [y, m] = sel ? [+sel.slice(0, 4), +sel.slice(5, 7) - 1] : [new Date().getFullYear(), new Date().getMonth()];
      state = { anchor, selected: sel, y, m, base: opts.base || '', onPick: opts.onPick };
      pop = document.createElement('div'); pop.className = 'cal'; document.body.appendChild(pop); place(anchor);
      document.addEventListener('pointerdown', onOutside, true); document.addEventListener('keydown', onKey);
      render();
    },
    close,
  };
})();
