/* The timeline: one continuous strip you drag (with inertia), three zoom levels (a day by the hour / three days / a week),
   rows decided by the window. Lines are always present and can be folded but not hidden; rows indent by level and a parent
   folds its blocks; hovering lights a goal and everything under it; nearby dots merge into a cluster; a finished goal gets
   a check on its bar. It should feel as smooth as a native app. */
(function () {
  const CHEV = '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 3.5l3 3 3-3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'; // the arrow inside the fold toggle is drawn: a ▾ glyph is unreadable in a small circle
  const T = window.T, CFG = window.__CFG__;
  const H = 3600e3, D = 24 * H, TZ = CFG.tz;
  const ZOOMS = { day: 24, three: 72, week: 168 };
  const WD = { Mon: T('wd_mon'), Tue: T('wd_tue'), Wed: T('wd_wed'), Thu: T('wd_thu'), Fri: T('wd_fri'), Sat: T('wd_sat'), Sun: T('wd_sun') };
  const ROW = 60, LANE = 22, BAR = 18, DOT_ROW = 18;   // row height, lane per concurrent stage, bar thickness, the dot row; the bottom 14px hold the life line and the start / late labels
  const fmt = new Intl.DateTimeFormat('en-US', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false, weekday: 'short' });
  const fmtIso = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' });

  function wall(ms) {
    const p = {};
    for (const x of fmt.formatToParts(new Date(ms))) if (x.type !== 'literal') p[x.type] = x.value;
    return { y: +p.year, m: +p.month, d: +p.day, h: (+p.hour) % 24, mi: +p.minute, wd: p.weekday };
  }
  function dayIso(ms) { return fmtIso.format(new Date(ms)); }
  function dayStartOf(iso) { // midnight of a date in the main time zone: step back from that day's UTC noon by the local clock, then correct once more for DST days
    const noon = Date.parse(iso + 'T12:00:00Z');
    let t = noon - wall(noon).h * H - wall(noon).mi * 60e3;
    const w = wall(t); if (w.h !== 0 || w.mi !== 0) t -= w.h * H + w.mi * 60e3;
    return t;
  }
  function dayStart(ms) { return dayStartOf(dayIso(ms)); }
  function addDays(iso, n) { const d = new Date(iso + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); }
  function nextDay(ms) { return dayStartOf(addDays(dayIso(ms), 1)); }
  function dayLabel(ms) { const w = wall(ms); return { md: `${String(w.m).padStart(2, '0')}-${String(w.d).padStart(2, '0')}`, wd: WD[w.wd] }; }
  function fmtTime(ms) { const w = wall(ms); return `${String(w.m).padStart(2, '0')}-${String(w.d).padStart(2, '0')} ${String(w.h).padStart(2, '0')}:${String(w.mi).padStart(2, '0')}`; }
  const easeOut = t => 1 - Math.pow(1 - t, 3);
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  // Once pushed to the team board both numbers show, birth number first and the team number small after it (A24 · G1.3):
  // the number you knew before the push still finds the goal, and the top level sorts by it.
  const pushed = g => (g.birth && g.birth !== g.gnum);
  const numHtml = g => pushed(g) ? `${esc(g.birth)}<span class="b" title="${T('team_number')}"> · ${esc(g.gnum)}</span>` : esc(g.gnum);
  const numText = g => pushed(g) ? `${g.birth} · ${g.gnum}` : g.gnum;
  const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };

  const B = window.__BASE__ || '';
  const el = {
    tl: document.getElementById('tl'), head: document.getElementById('tl-head'), rows: document.getElementById('tl-rows'),
    bg: document.getElementById('tl-bg'), bgsheet: document.getElementById('tl-bgsheet'),
    zoom: document.getElementById('zoom'), legend: document.getElementById('legend'), date: document.getElementById('nav-date'),
  };
  // origin: the coordinate origin, fixed once when the page opens. Using the start of the fetched window instead made the
  // origin move on every 30-second refresh: the header was redrawn but unchanged rows were not, so bars jumped back after a drag.
  const S = { zoom: store.get('mb.zoom') || 'week', t0: 0, origin: 0, pxh: 6, now: Date.now(), rows: [], lines: [], fetched: null,
    sig: '', dataVer: 0, fam: null, visible: '', visibleIds: '', selDay: '', anim: null, byG: {},
    foldLine: new Set((store.get('mb.foldLine') || '').split('|').filter(Boolean)),
    foldGoal: new Set((store.get('mb.foldGoal') || '').split('|').filter(Boolean)) };

  function span() { return ZOOMS[S.zoom] * H; }
  function width() { return (el.tl.clientWidth - el.bg.offsetLeft) || 800; }
  function fitPxh() { return width() / ZOOMS[S.zoom]; }
  function x(ms) { return (ms - S.origin) / H * S.pxh; }
  function sheetShift() { return -(S.t0 - S.origin) / H * S.pxh; }

  // ---------- data ----------
  async function ensureData(force) {
    const need = { from: S.t0 - span() * 2, to: S.t0 + span() * 3 };
    if (!force && S.fetched && need.from >= S.fetched.from && need.to <= S.fetched.to) return false;
    const f = { from: S.t0 - span() * 4, to: S.t0 + span() * 5 };
    const q = new URLSearchParams({ from: new Date(f.from).toISOString(), to: new Date(f.to).toISOString() });
    const r = await fetch(B + '/api/timeline?' + q).then(r => r.json());
    S.rows = r.rows; S.lines = r.lines; S.now = Date.parse(r.now); S.fetched = f;
    const sig = JSON.stringify(r.rows) + JSON.stringify(r.lines); // a new version only when the content changed
    if (sig !== S.sig) { S.sig = sig; S.dataVer++; }
    S.byG = {}; for (const g of S.rows) S.byG[g.gnum] = g;
    return true;
  }
  function visibleRows() {
    const a = S.t0, b = S.t0 + span();
    return S.rows.filter(g => {
      if (g.point) return g.point.occ.some(o => Date.parse(o.at) < b && occEnd(o) >= a); // point task: shown only when the window covers an occurrence; an overdue one covers from its moment up to now (same as points.visible)
      const sp = g.spans.some(s => (s.end ? Date.parse(s.end) : S.now) > a && Date.parse(s.start) < b);
      const dt = g.dots.some(d => { const t = Date.parse(d.at); return t >= a && t < b; });
      if (g.status === 'active') return sp || dt || Date.parse(g.created_at) < b; // in progress is always there, except on days before the goal was created (same as view.timeline)
      const span0 = !g.has_stages && Date.parse(g.created_at) < b && (g.done_at ? Date.parse(g.done_at) : S.now) > a;
      return sp || dt || span0;
    });
  }
  function depthOf(g) { let d = 0, p = g.parent_gnum; while (p && S.byG[p] && d < 6) { d++; p = S.byG[p].parent_gnum; } return d + (p && !S.byG[p] ? 1 : 0); }
  function rootOf(g) { let cur = g, n = 0; while (cur.parent_gnum && S.byG[cur.parent_gnum] && n < 8) { cur = S.byG[cur.parent_gnum]; n++; } return cur.parent_gnum || cur.gnum; }
  function hiddenByFold(g) { let p = g.parent_gnum, n = 0; while (p && n < 8) { if (S.foldGoal.has(p)) return true; p = S.byG[p] ? S.byG[p].parent_gnum : null; n++; } return false; }
  function descendants(gnum, vis) { return vis.filter(g => { let p = g.parent_gnum, n = 0; while (p && n < 8) { if (p === gnum) return true; p = S.byG[p] ? S.byG[p].parent_gnum : null; n++; } return false; }); }
  const STAGE_ORDER = CFG.stages;
  function dueMs(due) { // planned finish: a bare date means the last second of that day (23:59:59, the team board's rule too); with a time it is that moment
    const [dd, tt] = due.split(/[ T]/);
    return tt ? dayStartOf(dd) + (+tt.slice(0, 2)) * H + (+tt.slice(3, 5)) * 60e3 : nextDay(dayStartOf(dd)) - 1e3;
  }
  function lateText(ms) { // how late: hours under a day, otherwise days (one decimal under ten); points.late_text matches this character for character — change both together
    if (ms < 3600e3) return '';
    return ms < D ? T('late_hours', { n: Math.round(ms / H) }) : T('late_days', { n: (ms / D).toFixed(ms / D >= 10 ? 0 : 1) });
  }
  function lateOf(g) { // delay: up to now for a goal in progress, up to completion for a finished one; measured from the first plan ever set, even after the plan was changed
    if (!g.baseline_due || g.long_term || g.status === 'abandoned') return 0;   // an abandoned goal is not late
    const end = g.done_at ? Date.parse(g.done_at) : S.now;
    return Math.max(0, end - dueMs(g.baseline_due));
  }
  // one occurrence of a point task: the server's state is as of the fetch; between 30-second refreshes an "upcoming" one may have passed, so judge again against S.now
  function occState(o) { return o.state === 'upcoming' && Date.parse(o.at) <= S.now ? 'overdue' : o.state; }
  function occLate(o) { const t = Date.parse(o.at), st = occState(o); return st === 'done' ? Math.max(0, Date.parse(o.done_at) - t) : st === 'overdue' ? S.now - t : 0; }
  function occEnd(o) { return Date.parse(o.at) + occLate(o); }
  function openStages(gs) { // the stages open right now across these goals (deduplicated, in stage order), shown on a folded header
    const set = new Map();
    for (const g of gs) for (const sp of g.spans) if (!sp.end) set.set(sp.stage, sp.color);
    return [...STAGE_ORDER.filter(st => set.has(st)), ...[...set.keys()].filter(st => !STAGE_ORDER.includes(st))].map(st => `<i class="stc" style="background:${set.get(st)}"></i>${esc(st)}`).join('');
  }
  function lanesOf(g) {
    const ends = [];
    return g.spans.map(s => {
      const st = Date.parse(s.start), en = s.end ? Date.parse(s.end) : S.now;
      let lane = ends.findIndex(e => e <= st);
      if (lane < 0) { lane = ends.length; ends.push(en); } else ends[lane] = en;
      return lane;
    });
  }

  // ---------- header (date labels) and background (day columns, weekends, today, the now line) ----------
  function renderHead() {
    const head = document.createDocumentFragment(), bg = document.createDocumentFragment();
    const f = S.fetched, today = dayStart(S.now);
    for (let t = dayStart(f.from); t < f.to; t = nextDay(t)) {
      const next = nextDay(t), w = wall(t);
      const col = document.createElement('div');
      col.className = 'tl-col' + ((w.wd === 'Sat' || w.wd === 'Sun') ? ' wk' : '') + (t === today ? ' today' : '');
      col.style.left = x(t) + 'px'; col.style.width = x(next) - x(t) + 'px';
      bg.appendChild(col);
      const lab = document.createElement('div'), l = dayLabel(t);
      lab.className = 'tl-dlabel' + (dayIso(t) === S.selDay ? ' sel' : '');
      lab.style.left = x(t) + 4 + 'px';
      lab.innerHTML = `${l.md}<small>${l.wd}${t === today ? ' · ' + T('today') : ''}</small>`;
      lab.dataset.day = dayIso(t);
      lab.addEventListener('click', ev => { ev.stopPropagation(); selectDay(lab.dataset.day); });
      head.appendChild(lab);
      if (S.zoom === 'day') for (let h = 2; h < 24; h += 2) {
        const hl = document.createElement('div');
        hl.className = 'tl-hlabel'; hl.style.left = x(t + h * H) + 2 + 'px'; hl.textContent = String(h).padStart(2, '0') + ':00';
        head.appendChild(hl);
        const hc = document.createElement('div'); hc.className = 'tl-col hour'; hc.style.left = x(t + h * H) + 'px'; bg.appendChild(hc);
      }
    }
    const now = document.createElement('div'); now.className = 'tl-now'; now.style.left = x(S.now) + 'px'; bg.appendChild(now);
    el.head.replaceChildren(head); el.bgsheet.replaceChildren(bg);
    el.head.style.width = el.bgsheet.style.width = x(S.fetched.to) + 'px';
  }

  // ---------- a goal row ----------
  function goalRow(g, lanes, vis) {
    const n = Math.max(1, lanes.length ? Math.max(...lanes) + 1 : 1);
    const h = ROW + (n - 1) * LANE + (g.dots.length ? DOT_ROW : 0);
    const kids = descendants(g.gnum, vis).length, folded = S.foldGoal.has(g.gnum);
    const name = document.createElement('div');
    name.className = 'row-goal d' + Math.min(depthOf(g), 4) + (kids ? ' has-kids' : '');
    name.style.height = h + 'px';
    const mine = openStages([g]);
    const line3 = g.done_at ? `<span class="done">${g.status === 'abandoned' ? T('st_abandoned') : T('st_done')} ${g.done_at_local}</span>${g.version_name ? ` <span class="vn">${esc(g.version_name)}</span>` : ''}`
      : (mine ? `<span class="stl">${mine}</span> ` : '') + (g.blocker ? `<span class="blk">⏸ ${esc(g.blocker_short || g.blocker)}</span> ` : '') + (g.version_name ? `<span class="vn">${esc(g.version_name)}</span> ` : '') + (g.next_step ? T('next_is', { text: esc(g.next_step) }) : `<span class="dim">${T('next_is', { text: '—' })}</span>`);
    const kidsOpen = folded && kids ? openStages(descendants(g.gnum, vis)) : '';
    name.innerHTML = `<div class="t">${kids ? `<span class="fold${folded ? ' closed' : ''}" title="${folded ? T('unfold_blocks') : T('fold_blocks')}">${CHEV}</span>` : '<span class="fold-ph"></span>'}<span class="g">${numHtml(g)}</span><a class="ttl" href="${B}/goal/${encodeURIComponent(g.gnum)}" title="${esc(g.title)}">${esc(g.title)}</a>` +
      (kids ? (folded ? `<span class="kids">${T('blocks_folded', { n: kids })}${kidsOpen ? ' · ' + T('open_inside') + ' ' : ''}</span>${kidsOpen ? `<span class="stl">${kidsOpen}</span>` : ''}` : `<span class="kids">${T('blocks_n', { n: kids })}</span>`) : '') + '</div>' +  // "N blocks" stays on even when unfolded: one glance tells that the row has something under it
      `<div class="n">${line3}</div>`;
    // the whole name cell toggles the fold (a tiny triangle is too small a target); clicking the title opens the detail page
    if (kids) name.addEventListener('click', ev => { if (ev.target.closest('a')) return; ev.preventDefault(); toggleGoal(g.gnum); });
    const line = document.createElement('div');
    line.className = 'tl-row goal' + (g.status !== 'active' ? ' over' : ''); line.dataset.gnum = g.gnum;
    const cell = document.createElement('div'); cell.className = 'tl-cell';
    const row = document.createElement('div'); row.className = 'sheet'; row.style.height = h + 'px';
    cell.appendChild(row); line.appendChild(name); line.appendChild(cell);
    const top0 = 18;
    let lastEnd = null, lastTop = top0;
    const future = (top, color) => { // still going: a faint dashed line from "now" to the visible right edge, so dragging into the future is not a blank
      const f = document.createElement('div'); f.className = 'seg-future'; f.style.top = top + BAR / 2 - 1 + 'px';
      f.style.setProperty('--l', x(S.now) + 'px'); if (color) f.style.borderTopColor = color; row.appendChild(f);
    };
    g.spans.forEach((s, i) => {
      const st = Date.parse(s.start), en = s.end ? Date.parse(s.end) : S.now;
      const b = document.createElement('div');
      b.className = 'seg-bar' + (s.end ? '' : ' open');
      b.style.left = x(st) + 'px'; b.style.width = Math.max(4, x(en) - x(st)) + 'px'; b.style.top = top0 + lanes[i] * LANE + 'px';
      b.style.background = s.color; b.innerHTML = `<span class="lbl">${esc(s.stage)}</span>`; b.style.setProperty('--l', x(st) + 'px'); b.style.setProperty('--w', Math.max(4, x(en) - x(st)) + 'px');
      b.dataset.tip = JSON.stringify({ title: `${numText(g)} ${g.title}`, items: [{ t: `${fmtTime(st)} → ${s.end ? fmtTime(en) : T('st_active')}`, k: T('stage_of', { stage: s.stage }), text: T('hours', { n: Math.round(((en - st) / H) * 10) / 10 }), stage: s.stage, color: s.color }] });
      row.appendChild(b);
      if (!s.end && g.status === 'active') future(top0 + lanes[i] * LANE, s.color);
      if (lastEnd === null || en >= lastEnd) { lastEnd = en; lastTop = top0 + lanes[i] * LANE; }
    });
    if (!g.has_stages) {
      const st = Date.parse(g.created_at), en = g.done_at ? Date.parse(g.done_at) : S.now;
      const b = document.createElement('div');
      b.className = 'seg-bar none'; b.style.left = x(st) + 'px'; b.style.width = Math.max(4, x(en) - x(st)) + 'px'; b.style.top = top0 + 'px';
      b.innerHTML = `<span class="lbl">${T('no_stage')}</span>`; b.style.setProperty('--l', x(st) + 'px'); b.style.setProperty('--w', Math.max(4, x(en) - x(st)) + 'px'); b.dataset.tip = JSON.stringify({ title: `${numText(g)} ${g.title}`, items: [{ t: `${fmtTime(st)} → ${g.done_at ? fmtTime(en) : T('st_active')}`, k: T('no_stage'), text: '' }] }); row.appendChild(b);
      if (!g.done_at && g.status === 'active') future(top0, '');
      lastEnd = en; lastTop = top0;
    }
    if (g.done_at && lastEnd !== null) { // the bar itself shows it is finished: a check at its end
      const ck = document.createElement('div'); ck.className = 'seg-done' + (g.status === 'abandoned' ? ' ab' : '');
      ck.style.left = x(Date.parse(g.done_at)) + 2 + 'px'; ck.style.top = lastTop - 1 + 'px'; ck.textContent = g.status === 'abandoned' ? '✕' : '✓';
      ck.title = (g.status === 'abandoned' ? T('st_abandoned') : T('st_done')) + ' ' + g.done_at_local; row.appendChild(ck);
    }
    // entry dots: neighbours merge into a cluster that lists them on hover (in the week view they would pile up unreadably)
    const dots = g.dots.slice().sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
    const groups = [];
    for (const d of dots) {
      const px = x(Date.parse(d.at)), last = groups[groups.length - 1];
      if (last && px - last.px < 12) { last.items.push(d); last.px2 = px; } else groups.push({ px, px2: px, items: [d] });
    }
    for (const gr of groups) {
      const dot = document.createElement('div');
      const one = gr.items.length === 1;
      dot.className = 'dot ' + (one ? gr.items[0].kind : 'multi' + (gr.items.some(d => d.kind === 'digest') ? ' gold' : '')) /* a cluster holding a digest turns gold */; dot.style.left = (gr.px + gr.px2) / 2 - (one ? 5 : 8) + 'px'; dot.style.top = h - DOT_ROW - 14 + 'px';
      dot.innerHTML = one ? '' : `<b>${gr.items.length}</b>`;
      dot.dataset.tip = JSON.stringify({ title: `${numText(g)} ${g.title}`, items: gr.items.map(d => ({ t: fmtTime(Date.parse(d.at)), k: d.kind_label, task: d.task, tool: d.tool, text: d.text, stage: d.stage, color: d.stage_color })) });
      row.appendChild(dot);
    }
    // life line: a thin line from creation to completion / now, showing at a glance when this started
    const st0 = Date.parse(g.created_at), en0 = g.done_at ? Date.parse(g.done_at) : S.now;
    const life = document.createElement('div'); life.className = 'life'; life.style.left = x(st0) + 'px'; life.style.width = Math.max(2, x(en0) - x(st0)) + 'px';
    life.title = `${T('started', { at: fmtTime(st0) })}${g.done_at ? ' → ' + fmtTime(en0) : ''}`; row.appendChild(life);
    if (g.status === 'active' && g.has_stages && !g.spans.some(s => !s.end)) { // unfinished with no stage open right now (waiting, paused): the life line continues as a grey dashed line
      const f = document.createElement('div'); f.className = 'seg-future life-f'; f.style.setProperty('--l', x(S.now) + 'px'); row.appendChild(f);
    }
    const sl = document.createElement('div'); sl.className = 'start-label'; sl.style.left = x(st0) + 'px'; sl.textContent = T('started', { at: fmtTime(st0).slice(0, 5) }); row.appendChild(sl);
    if (g.baseline_due && !g.long_term) { // the plan line stands at the first plan ever set, labelled "plan MM-DD"; past it a red run to now says how late
      const t = dueMs(g.baseline_due), late = lateOf(g);
      const dl = document.createElement('div'); dl.className = 'due-line' + (late ? ' late' : ''); dl.style.left = x(t) + 'px';
      dl.innerHTML = `<span>${T('plan_at', { at: g.baseline_due.slice(5) })}</span>`; row.appendChild(dl);
      if (g.due && g.due !== g.baseline_due) { // a changed plan: the new one gets its own faint line "moved to MM-DD"; delay is still measured from the line above
        const rl = document.createElement('div'); rl.className = 'due-line re'; rl.style.left = x(dueMs(g.due)) + 'px';
        rl.innerHTML = `<span>${T('moved_to', { at: g.due.slice(5) })}</span>`; row.appendChild(rl);
      }
      if (late && lateText(late)) {
        const seg = document.createElement('div'); seg.className = 'late-seg'; seg.style.left = x(t) + 'px'; seg.style.width = Math.max(2, x(t + late) - x(t)) + 'px';
        row.appendChild(seg);
        const ll = document.createElement('div'); ll.className = 'late-label'; ll.style.left = x(t + late) + 'px';
        ll.textContent = T(g.done_at ? 'late_done' : 'late', { late: lateText(late) }); row.appendChild(ll);
      }
    }
    return line;
  }

  // ---------- a point-task row: no stage bars, one big dot per occurrence; hollow = not done, solid = done.
  // An overdue one draws red from its moment to now ("N overdue"); a late tick draws red up to the tick (as goals do for delay) ----------
  const CHECK = '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 5.2l2 2 4-4.4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  function pointRow(g) {
    const h = ROW, occ = g.point.occ;
    const over = occ.filter(o => occState(o) === 'overdue').length;
    const name = document.createElement('div');
    name.className = 'row-goal d' + Math.min(depthOf(g), 4); name.style.height = h + 'px';
    name.innerHTML = `<div class="t"><span class="fold-ph"></span><span class="g">${numHtml(g)}</span><a class="ttl" href="${B}/goal/${encodeURIComponent(g.gnum)}" title="${esc(g.title)}">${esc(g.title)}</a></div>` +
      `<div class="n"><i class="ptleg"></i>${esc(g.point.rule)}${over ? ` <span class="late">${T('missed_n', { n: over })}</span>` : ''}${g.status === 'abandoned' ? ` <span class="dim">${T('cancelled')}</span>` : ''}</div>`;
    const line = document.createElement('div');
    line.className = 'tl-row goal point' + (g.status === 'abandoned' ? ' over' : ''); line.dataset.gnum = g.gnum;
    const cell = document.createElement('div'); cell.className = 'tl-cell';
    const row = document.createElement('div'); row.className = 'sheet'; row.style.height = h + 'px';
    cell.appendChild(row); line.appendChild(name); line.appendChild(cell);
    const STATE = { done: T('occ_done'), overdue: T('occ_overdue'), upcoming: T('occ_upcoming'), cancelled: T('occ_cancelled') };
    const firstOver = occ.find(o => occState(o) === 'overdue'); // several overdue: every red run ends at "now", so only the earliest carries the label
    for (const o of occ) {
      const t = Date.parse(o.at), st = occState(o), late = occLate(o);
      if (late && lateText(late) && (st !== 'overdue' || o === firstOver)) {
        const seg = document.createElement('div'); seg.className = 'late-seg'; seg.style.left = x(t) + 'px'; seg.style.width = Math.max(2, x(t + late) - x(t)) + 'px'; row.appendChild(seg);
        const ll = document.createElement('div'); ll.className = 'late-label'; ll.style.left = x(t + late) + 'px';
        ll.textContent = T(st === 'done' ? 'overdue_done' : 'overdue', { late: lateText(late) }) + (st === 'overdue' && over > 1 ? T('missed_total', { n: over }) : ''); row.appendChild(ll);
      } else if (late && st === 'overdue') { // later overdue ones draw the red run only
        const seg = document.createElement('div'); seg.className = 'late-seg'; seg.style.left = x(t) + 'px'; seg.style.width = Math.max(2, x(t + late) - x(t)) + 'px'; row.appendChild(seg);
      }
      const dot = document.createElement('div');
      dot.className = 'pt ' + st; dot.style.left = x(t) - 9 + 'px'; dot.style.top = '13px';
      if (st === 'done') dot.innerHTML = CHECK;
      const k = st === 'done' ? `${STATE.done} ${fmtTime(Date.parse(o.done_at))}${T('paren', { x: CFG.tz_label })}` : st === 'overdue' ? `${STATE.overdue}${lateText(late) ? ' ' + lateText(late) : ''}` : STATE[st];
      dot.dataset.tip = JSON.stringify({ title: `${numText(g)} ${g.title}`, items: [{ k, t: o.text, text: g.point.rule }] });
      row.appendChild(dot);
      const lab = document.createElement('div'); lab.className = 'pt-label'; lab.style.left = x(t) + 13 + 'px'; lab.textContent = o.label; row.appendChild(lab);
    }
    return line;
  }

  function buildRows(vis) { // the rows that belong, grouped by line, each with a key
    const out = [];
    for (const ln of S.lines) { // lines are always present: shown even when quiet, foldable but never hidden
      const gs = vis.filter(g => g.line === ln.name), folded = S.foldLine.has(ln.name);
      const line = document.createElement('div'); line.className = 'tl-row lineh' + (folded ? ' folded' : '') + (gs.length ? '' : ' noact');
      line.style.setProperty('--lc', ln.color); line.dataset.key = 'L:' + ln.name;
      line.innerHTML = `<div class="row-line"><i></i><span class="arr">${folded ? '▸' : '▾'}</span><b>${ln.mark} ${esc(ln.name)}</b><span class="cnt">${gs.length ? (folded ? T('items_folded', { n: gs.length }) + (openStages(gs) ? ` · ${T('st_active')} <span class="stl">${openStages(gs)}</span>` : '') : T('items_n', { n: gs.length })) : T('none_here')}</span></div><div class="tl-cell"></div>`;
      line.addEventListener('click', () => toggleLine(ln.name));
      out.push(line);
      if (folded) continue;
      for (const g of gs) {
        if (hiddenByFold(g)) continue;
        const r = g.point ? pointRow(g) : goalRow(g, lanesOf(g), vis); r.dataset.key = 'G:' + g.gnum;
        out.push(r);
      }
    }
    return out;
  }
  const EASE = 'cubic-bezier(.2,.8,.2,1)';
  const toast = document.createElement('div'); toast.className = 'toast'; toast.hidden = true; document.body.appendChild(toast);
  function notice(msg) { // a toast when rows enter or leave, gone after 2.6 s; it sits right under the date header, where the eye is
    const head = document.getElementById('tl-headrow'); if (head) toast.style.top = Math.round(head.getBoundingClientRect().bottom + 14) + 'px';
    toast.textContent = msg; toast.hidden = false; toast.classList.remove('show'); void toast.offsetWidth; toast.classList.add('show');
    clearTimeout(S.noticeT); S.noticeT = setTimeout(() => { toast.classList.remove('show'); setTimeout(() => { toast.hidden = true; }, 250); }, 2600);
  }
  function renderRows(force, opts) {
    const vis = visibleRows();
    const ids = vis.map(g => g.gnum).join('|') + '|' + [...S.foldLine].join(',') + '|' + [...S.foldGoal].join(',');
    const layout = S.pxh.toFixed(2) + S.zoom + '#' + S.dataVer; // zoom or data changed: redraw everything, no enter / leave animation
    const key = ids + '@' + layout + '@' + S.now; // what is drawn also depends on "now": open bars run to now, late runs are measured to now
    if (!force && key === S.visible) return;
    const rows = buildRows(vis);
    const animate = !(opts && opts.noFade) && S.layoutKey === layout && S.visibleIds !== ids && el.rows.children.length;
    S.visible = key; S.visibleIds = ids; S.layoutKey = layout;
    if (!animate) { el.rows.replaceChildren(...rows); }
    else {
      const oldKeys = new Set(Array.from(el.rows.children).map(r => r.dataset.key).filter(k => k && k.startsWith('G:')));
      const newKeys = new Set(rows.map(r => r.dataset.key).filter(k => k.startsWith('G:')));
      const added = [...newKeys].filter(k => !oldKeys.has(k)).length, gone = [...oldKeys].filter(k => !newKeys.has(k)).length;
      if (added || gone) notice(T('moved_notice', { day: dayLabel(S.t0).md }) + (added ? T('rows_in', { n: added }) : '') + (added && gone ? T('sep') : '') + (gone ? T('rows_out', { n: gone }) : '')); // a diff: unchanged rows stay put, new ones slide in, leaving ones collapse — dragging to old days does not flash the whole left column
      const old = new Map(Array.from(el.rows.children).map(r => [r.dataset.key, r]));
      const keep = new Set(rows.map(r => r.dataset.key));
      for (const [k, r] of old) if (!keep.has(k)) {
        const h = r.offsetHeight;
        r.style.overflow = 'hidden';
        r.animate([{ height: h + 'px', opacity: 1 }, { height: '0px', opacity: 0 }], { duration: 260, easing: EASE }).onfinish = () => r.remove();
        r.dataset.key = '';
      }
      let cursor = el.rows.firstChild;
      for (const r of rows) {
        const ex = old.get(r.dataset.key);
        if (ex) { // update in place (a line header's count changes); do not rebuild
          if (ex.className !== r.className || ex.innerHTML !== r.innerHTML) ex.replaceWith(r);
          cursor = (ex.isConnected ? ex : r).nextSibling;
          continue;
        }
        el.rows.insertBefore(r, cursor);
        const h = r.offsetHeight;
        r.style.overflow = 'hidden';
        r.animate([{ height: '0px', opacity: 0 }, { height: h + 'px', opacity: 1 }], { duration: 320, easing: EASE }).onfinish = () => { r.style.overflow = ''; };
      }
    }
    if (S.fam) setFamily(S.fam); // keep the hovered row lit after a redraw (auto-refresh redraws)
    el.bg.style.height = Math.max(el.tl.scrollHeight, el.tl.clientHeight) + 'px';
    el.bgsheet.style.width = x(S.fetched.to) + 'px';
  }
  window.Timeline_foldAll = function (fold) {
    S.foldLine = new Set(fold ? S.lines.map(l => l.name) : []);
    S.foldGoal = new Set(fold ? S.rows.filter(g => S.rows.some(r => r.parent_gnum === g.gnum)).map(g => g.gnum) : []);
    store.set('mb.foldLine', [...S.foldLine].join('|')); store.set('mb.foldGoal', [...S.foldGoal].join('|'));
    renderRows(true, { noFade: true }); place();
  };
  function toggleLine(name) { S.foldLine.has(name) ? S.foldLine.delete(name) : S.foldLine.add(name); store.set('mb.foldLine', [...S.foldLine].join('|')); renderRows(true, { noFade: true }); place(); }
  function toggleGoal(gnum) { S.foldGoal.has(gnum) ? S.foldGoal.delete(gnum) : S.foldGoal.add(gnum); store.set('mb.foldGoal', [...S.foldGoal].join('|')); renderRows(true, { noFade: true }); place(); }

  // hover lights the goal itself and the blocks under it (not the whole family: hovering a leaf must not light its siblings); the rest dims
  function familyOf(gnum) {
    if (!S.byG[gnum]) return null;
    const under = g => { let p = g.parent_gnum, n = 0; while (p && n < 8) { if (p === gnum) return true; p = S.byG[p] ? S.byG[p].parent_gnum : null; n++; } return false; };
    return new Set(S.rows.filter(r => r.gnum === gnum || under(r)).map(r => r.gnum));
  }
  // ancestors glow faintly, so from a block you can follow up to the goal it belongs to; siblings stay dim
  function ancestorsOf(gnum) { const out = new Set(); let p = S.byG[gnum] && S.byG[gnum].parent_gnum, n = 0; while (p && n < 8) { out.add(p); p = S.byG[p] ? S.byG[p].parent_gnum : null; n++; } return out; }
  function setFamily(gnum) {
    S.fam = gnum;
    const fam = gnum ? familyOf(gnum) : null, anc = gnum ? ancestorsOf(gnum) : new Set();
    for (const r of document.querySelectorAll('[data-gnum]')) {
      const g = r.dataset.gnum;
      r.classList.toggle('fam', !!fam && fam.has(g));
      r.classList.toggle('anc', !!fam && !fam.has(g) && anc.has(g));
      r.classList.toggle('dimmed', !!fam && !fam.has(g) && !anc.has(g));
    }
    el.rows.classList.toggle('hl', !!fam);
    // entries of the same goal in the day list light up too
    for (const e of document.querySelectorAll('#entries .ent[data-gnum]')) e.classList.toggle('hit', !!gnum && e.dataset.gnum === gnum);
  }
  // triggered by the name cell only: reacting to the whole row would light things up whenever the pointer crosses the chart
  el.rows.addEventListener('mouseover', ev => { const name = ev.target.closest('.row-goal'); const r = name && name.closest('[data-gnum]'); setFamily(r ? r.dataset.gnum : null); });
  el.rows.addEventListener('mouseleave', () => setFamily(null));

  // tooltip: a separate floating layer that follows the pointer, is never clipped by a cell and wraps its text
  const tip = document.createElement('div'); tip.className = 'tl-tip'; tip.hidden = true; document.body.appendChild(tip);
  function showTip(d, ev) {
    tip.innerHTML = `<div class="tt">${esc(d.title)}</div>` + d.items.map(it =>
      `<div class="ti">${it.color ? `<i class="stc" style="background:${it.color}"></i>` : ''}<span class="tk">${esc(it.k)}</span><span class="tm">${esc(it.t)}</span>${it.task ? `<span class="ts">${esc(it.task)}${it.tool ? ' · ' + esc(it.tool) : ''}</span>` : ''}${it.text ? `<div class="tx">${esc(it.text)}</div>` : ''}</div>`).join('');
    tip.hidden = false; moveTip(ev);
  }
  function moveTip(ev) {
    const w = tip.offsetWidth, h = tip.offsetHeight;
    let x = ev.clientX + 16, y = ev.clientY + 14;
    if (x + w > window.innerWidth - 8) x = ev.clientX - w - 12;
    if (y + h > window.innerHeight - 8) y = ev.clientY - h - 12;
    tip.style.left = Math.max(8, x) + 'px'; tip.style.top = Math.max(8, y) + 'px';
  }
  el.rows.addEventListener('mouseover', ev => { const t = ev.target.closest('[data-tip]'); if (t) showTip(JSON.parse(t.dataset.tip), ev); });
  el.rows.addEventListener('mousemove', ev => { if (!tip.hidden) moveTip(ev); });
  el.rows.addEventListener('mouseout', ev => { const t = ev.target.closest('[data-tip]'); if (t && !t.contains(ev.relatedTarget)) tip.hidden = true; });
  el.tl.addEventListener('pointerdown', () => { tip.hidden = true; });

  let placeQueued = false;
  function place() { // one frame writes two CSS variables: every .sheet's shift and the sticky stage labels read them, so the compositor does the work and dragging stays smooth
    if (placeQueued) return;
    placeQueued = true;
    requestAnimationFrame(() => {
      placeQueued = false;
      const shift = sheetShift();
      el.tl.style.setProperty('--shift', shift + 'px');
      el.tl.style.setProperty('--vis', (-shift) + 'px');
    });
  }
  async function settle() {
    const fetched = await ensureData(false);
    if (fetched) renderHead();
    place();
    el.date.textContent = '📅 ' + dayIso(S.t0 + span() / 2);
    // debounce: rows enter / leave only 450 ms after the motion settles; a quick peek does not reshuffle them
    clearTimeout(S.settleT);
    S.settleT = setTimeout(() => { if (!drag && !S.anim) renderRows(fetched); }, 450);
  }

  // ---------- drag + inertia ----------
  let drag = null;
  const inNames = t => !!t.closest('.row-goal, .row-line, .tl-corner');
  el.tl.addEventListener('pointerdown', ev => {
    if (ev.button !== 0 || inNames(ev.target)) return;
    cancelAnim(); clearTimeout(S.settleT);
    drag = { x: ev.clientX, t0: S.t0, v: 0, last: ev.clientX, lt: performance.now(), id: ev.pointerId, moved: false };
  });
  el.tl.addEventListener('pointermove', ev => {
    if (!drag) return;
    if (!drag.moved) { if (Math.abs(ev.clientX - drag.x) < 3) return; drag.moved = true; el.tl.classList.add('drag'); el.tl.setPointerCapture(drag.id); }
    const now = performance.now(), dt = Math.max(1, now - drag.lt);
    drag.v = 0.7 * drag.v + 0.3 * ((ev.clientX - drag.last) / dt);
    drag.last = ev.clientX; drag.lt = now;
    S.t0 = drag.t0 - (ev.clientX - drag.x) / S.pxh * H;
    place();
  });
  function endDrag() {
    if (!drag) return;
    const moved = drag.moved, v = (performance.now() - drag.lt > 80) ? 0 : drag.v;
    drag = null; el.tl.classList.remove('drag');
    if (moved) inertia(v);
  }
  el.tl.addEventListener('pointerup', endDrag);
  el.tl.addEventListener('pointercancel', endDrag);
  el.tl.addEventListener('wheel', ev => {
    if (Math.abs(ev.deltaX) < Math.abs(ev.deltaY)) return;
    ev.preventDefault(); cancelAnim();
    S.t0 += ev.deltaX / S.pxh * H; place();
    clearTimeout(S.wheelT); S.wheelT = setTimeout(settle, 120);
  }, { passive: false });
  function cancelAnim() { if (S.anim) { cancelAnimationFrame(S.anim); S.anim = null; } }
  function inertia(v) {
    let last = performance.now();
    const step = now => {
      const dt = now - last; last = now;
      S.t0 -= v * dt / S.pxh * H; v *= Math.pow(0.994, dt); place();
      if (Math.abs(v) > 0.02) S.anim = requestAnimationFrame(step); else { S.anim = null; settle(); }
    };
    if (Math.abs(v) > 0.05) S.anim = requestAnimationFrame(step); else settle();
  }
  function glideTo(t0) {
    cancelAnim();
    const from = S.t0, dist = t0 - from, start = performance.now(), dur = 420;
    const step = now => {
      const k = easeOut(Math.min(1, (now - start) / dur));
      S.t0 = from + dist * k; place();
      if (k < 1) S.anim = requestAnimationFrame(step); else { S.anim = null; settle(); }
    };
    S.anim = requestAnimationFrame(step);
  }
  function setZoom(z) {
    if (!ZOOMS[z]) return;
    cancelAnim(); store.set('mb.zoom', z);
    for (const b of el.zoom.querySelectorAll('button')) b.classList.toggle('on', b.dataset.zoom === z);
    const selT = S.selDay ? dayStartOf(S.selDay) : NaN;
    const anchor = (selT >= S.t0 && selT < S.t0 + span()) ? selT + D / 2 : S.t0 + span() / 2;
    const p0 = S.pxh; S.zoom = z; const p1 = fitPxh();
    const start = performance.now(), dur = 320;
    const step = now => {
      const k = easeOut(Math.min(1, (now - start) / dur));
      S.pxh = p0 + (p1 - p0) * k; S.t0 = anchor - (width() / 2) / S.pxh * H;
      renderHead(); renderRows(true, { noFade: true }); place();
      if (k < 1) S.anim = requestAnimationFrame(step); else { S.anim = null; settle(); }
    };
    S.anim = requestAnimationFrame(step);
  }
  function homeT0() { return S.zoom === 'day' ? dayStart(S.now) : dayStart(S.now) - span() + D; }

  // ---------- public ----------
  function selectDay(iso) {
    S.selDay = iso;
    for (const l of el.head.querySelectorAll('.tl-dlabel')) l.classList.toggle('sel', l.dataset.day === iso);
    if (window.App && window.App.loadDay) window.App.loadDay(iso);
  }
  window.Timeline = {
    highlight(gnum) { setFamily(gnum); }, // hovering the day list lights that row and the blocks under it
    selectDay(iso, scroll) {
      S.selDay = iso;
      for (const l of el.head.querySelectorAll('.tl-dlabel')) l.classList.toggle('sel', l.dataset.day === iso);
      if (scroll) { const t = dayStartOf(iso); if (t < S.t0 || t + D > S.t0 + span()) glideTo(S.zoom === 'day' ? t : t - span() + D); }
    },
    async refresh() { if (drag || S.anim) return; await ensureData(true); renderHead(); renderRows(false); place(); },
    legend(colors) {
      el.legend.innerHTML = Object.entries(colors).map(([k, c]) => `<span><i style="background:${c}"></i>${esc(k)}</span>`).join('') +
        `<span><i style="background:repeating-linear-gradient(90deg,var(--none-a) 0 3px,var(--none-b) 3px 6px)"></i>${T('no_stage')}</span><span><i class="futleg"></i>${T('leg_going')}</span><span><i class="dotleg"></i>${T('leg_entry')}</span><span><i class="dotleg gold"></i>${T('digest')}</span><span><i class="ptleg"></i>${T('leg_point')}</span><span><i class="ptleg done"></i>${T('occ_done')}</span>`;
    },
  };
  el.zoom.addEventListener('click', ev => { const b = ev.target.closest('button'); if (b) setZoom(b.dataset.zoom); });
  document.getElementById('fold-all').addEventListener('click', () => window.Timeline_foldAll(true));
  document.getElementById('unfold-all').addEventListener('click', () => window.Timeline_foldAll(false));
  document.getElementById('nav-today').addEventListener('click', () => { glideTo(homeT0()); selectDay(dayIso(S.now)); }); // the timeline and the day list go back to today together
  document.getElementById('nav-prev').addEventListener('click', () => glideTo(S.t0 - span()));
  document.getElementById('nav-next').addEventListener('click', () => glideTo(S.t0 + span()));
  el.date.addEventListener('click', () => window.Calendar.open(el.date, { selected: dayIso(S.t0 + span() / 2), base: B, onPick: iso => { // pick a day in the calendar: the timeline glides there and the day list switches too
    const t = dayStartOf(iso); glideTo(S.zoom === 'day' ? t : t - span() / 2 + D / 2); selectDay(iso); } }));
  window.addEventListener('resize', () => { S.pxh = fitPxh(); renderHead(); renderRows(true, { noFade: true }); place(); });

  (async function init() {
    for (const b of el.zoom.querySelectorAll('button')) b.classList.toggle('on', b.dataset.zoom === S.zoom);
    S.now = Date.now(); S.origin = dayStart(S.now); S.pxh = fitPxh(); S.t0 = homeT0(); S.selDay = (window.__STATE__ && window.__STATE__.day.iso) || dayIso(S.now);
    await ensureData(true); renderHead(); renderRows(true); place();
    el.date.textContent = '📅 ' + dayIso(S.t0 + span() / 2);
  })();
})();
