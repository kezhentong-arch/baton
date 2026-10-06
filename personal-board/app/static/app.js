/* Home page: header, the day's entries, the 7-day strip, to-dos, the dictation box. The timeline is in timeline.js. */
(function () {
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const B = window.__BASE__ || '', MODE = window.__MODE__ || '', T = window.T, CFG = window.__CFG__;
  let state = window.__STATE__, mode = 'day';
  const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
  // The day's entries default to newest first (during the day "what did I just log" is the usual question); switch to
  // chronological to read the story in order. The choice is remembered.
  let order = store.get('mb.order') === 'asc' ? 'asc' : 'desc';

  function renderHeader(h) {
    $('who').textContent = h.person_name || h.person;
    $('clock').textContent = h.clock;
    // With no team board connected nothing about pushing or pulling is shown — unless unpushed entries actually exist.
    $('pending-chip').hidden = !(h.team_board || h.pending_count > 0);
    $('pending-count').textContent = h.pending_count;
    $('pending-chip').classList.toggle('on', h.pending_count > 0 && mode === 'pending');
    $('pulled').textContent = h.team_pull_error ? T('pull_failed', { error: h.team_pull_error }) : h.team_pulled;
    $('pulled').title = h.team_pull_error || '';
    const label = { sample: T('mode_sample'), practice: T('mode_practice') }[MODE] || '';
    $('mode-badge').hidden = !label; $('mode-badge').textContent = label;
    for (const a of document.querySelectorAll('nav.modes a')) a.classList.toggle('on', a.dataset.mode === MODE);
    const note = $('mode-note'); note.hidden = !label && !h.demo && !h.case;
    if (!MODE && h.demo) note.innerHTML = T('note_demo');
    if (!MODE && h.case) note.innerHTML = T('note_case', { label: esc(h.case) });
    if (MODE === 'sample') note.innerHTML = T('note_sample');
    if (MODE === 'practice') note.innerHTML = T('note_practice', { button: `<button class="chip ghost small" id="reset-btn">${T('reset_practice')}</button>` });
    const rb = $('reset-btn'); if (rb) rb.onclick = async () => { if (!confirm(T('reset_confirm'))) return; const r = await fetch(B + '/api/reset', { method: 'POST' }).then(r => r.json()); if (r.ok) location.reload(); else alert(r.error); };
    $('pull-btn').hidden = !!MODE || !h.team_board;
    $('ver').textContent = h.version;
    document.title = (label ? label + ' · ' : '') + T('app_name');
  }
  function pill(cls, text) { return `<span class="pill ${cls}">${esc(text)}</span>`; }
  function entryHtml(e, withGoal) {
    const stage = e.stage ? `<span class="pill stage" style="background:${e.stage_color}">${esc(e.stage)}${e.stage_state ? `<span class="st"> · ${esc(e.stage_state)}</span>` : ''}</span>` : pill('', T('no_stage'));
    const sync = e.sync ? pill('sync-' + e.sync, e.sync_label + (e.synced_at ? ' ' + e.synced_at : '')) : '';
    const goal = withGoal ? `<a href="${B}/goal/${encodeURIComponent(e.gnum)}"><b>${esc(e.birth && e.birth !== e.gnum ? e.birth : e.gnum)}</b>${e.birth && e.birth !== e.gnum ? ` <span class="b">· ${esc(e.gnum)}</span>` : ''} ${esc(e.goal_title)}</a>` : '';
    const src = e.task ? `${esc(e.task)}${e.tool ? ' · ' + esc(e.tool) : ''}` : (e.tool ? esc(e.tool) : '');
    return `<li class="ent" data-gnum="${esc(e.gnum)}"><span class="at">${esc(e.at_local.slice(6))}</span><div class="m"><span class="kind k-${esc(e.kind)}">${esc(e.kind_label)}</span>${goal}${stage}${src ? '<span>' + src + '</span>' : ''}${sync}${e.backfilled ? pill('', T('backfilled')) : ''}</div><div class="txt">${esc(e.text)}</div></li>`;
  }
  function renderDay(s) {
    mode = 'day';
    $('day-title').textContent = T('day_title', { day: s.day.label + (s.day.is_today ? ' · ' + T('today') : ''), n: s.entry_count });
    const max = Math.max(1, ...s.week.map(w => w.total));
    $('week').innerHTML = s.week.map(w => `<a href="${B}/?day=${w.day}" data-day="${w.day}" class="${w.day === s.day.iso ? 'sel' : ''}">${w.label}<small>${esc(w.weekday)}</small><span class="bars">${w.counts.map((c, i) => `<i style="height:${Math.round(c / max * 14)}px;background:${s.lines[i].color}" title="${esc(s.lines[i].name)} ${c}"></i>`).join('')}</span></a>`).join('');
    // When the selected day is not today, offer "Today" at the far right; a calendar button reaches any day.
    $('week').insertAdjacentHTML('beforeend', `${s.day.is_today ? '' : `<button type="button" class="chip small" id="week-today">${T('today')}</button>`}<button type="button" class="chip ghost small" id="week-pick" title="${T('pick_date')}">📅</button>`);
    for (const a of $('week').querySelectorAll('a')) a.addEventListener('click', ev => { ev.preventDefault(); loadDay(a.dataset.day, true); });
    const wt = $('week-today'); if (wt) wt.addEventListener('click', () => loadDay(s.header.today, true));
    $('week-pick').addEventListener('click', () => window.Calendar.open($('week-pick'), { selected: s.day.iso, base: B, onPick: iso => loadDay(iso, true) }));
    renderEntries(s);
    $('todos').innerHTML = s.todos.length ? s.todos.map(t => `<li class="${t.done_at ? 'done' : ''}"><span>${t.done_at ? '☑' : '☐'}</span><span>${esc(t.text)}${t.gnum ? ` <span class="g">${esc(t.gnum)}</span>` : ''}</span></li>`).join('') : `<li class="dim">${T('no_todos')}</li>`;
    const open = s.notes.filter(n => !n.resolved_at), done = s.notes.filter(n => n.resolved_at);
    $('notes').innerHTML = open.map(noteHtml).join('') + (done.length ? `<details><summary>${T('notes_done', { n: done.length })}</summary><ul class="notes done-list">${done.map(noteHtml).join('')}</ul></details>` : '');
    for (const b of $('notes').querySelectorAll('button[data-id]')) b.addEventListener('click', () => copyPrompt(b.dataset.id, b.dataset.text));
  }
  function renderEntries(s) {
    $('order').hidden = false;
    for (const b of $('order').querySelectorAll('button')) b.classList.toggle('on', b.dataset.order === order);
    const hours = order === 'desc' ? [...s.hours].reverse().map(h => ({ hour: h.hour, entries: [...h.entries].reverse() })) : s.hours;
    $('entries').innerHTML = hours.length ? hours.map(h => `<div class="hour"><div class="h">${h.hour}:00</div><ul>${h.entries.map(e => entryHtml(e, true)).join('')}</ul></div>`).join('')
      : `<div class="empty">${T('empty_day')}</div>`;
  }
  function noteHtml(n) {
    return `<li><span class="dim small">${T('note_n', { id: n.id })} · ${n.created_local}${n.gnum ? ' · ' + T('note_about', { gnum: esc(n.gnum) }) : ''}${n.resolved_at ? ' · ' + T('note_resolved', { at: n.resolved_local, summary: esc(n.summary) }) : ''}</span>${n.resolved_at ? '' : ` <button class="chip ghost small" data-id="${n.id}" data-text="${esc(n.text)}">${T('copy_to_ai')}</button>`}<div class="txt">${esc(n.text)}</div></li>`;
  }
  async function loadDay(iso, scrollTimeline) {
    const s = await fetch(B + '/api/state?day=' + iso).then(r => r.json());
    state = s; renderHeader(s.header); renderDay(s);
    history.replaceState(null, '', (B || '') + (s.day.is_today ? '/' : '/?day=' + iso));
    if (window.Timeline) window.Timeline.selectDay(iso, !!scrollTimeline);
  }
  async function showPending() {
    const r = await fetch(B + '/api/pending').then(r => r.json());
    mode = 'pending'; $('pending-chip').classList.add('on'); $('order').hidden = true;
    $('day-title').textContent = T('pending_title', { n: r.entries.length });
    $('entries').innerHTML = (r.entries.length ? `<div class="hour"><div class="h"></div><ul>${r.entries.map(e => entryHtml(e, true)).join('')}</ul></div>` : `<div class="empty">${T('pending_none')}</div>`) +
      `<p class="dim small">${T('pending_help')} <a href="#" id="back-day">${T('back_to_day')}</a></p>`;
    $('back-day').addEventListener('click', ev => { ev.preventDefault(); loadDay(state.day.iso); });
  }
  function copyPrompt(id, text) {
    const p = T('dictation_prompt', { id }) + '\n\n' + text;
    const msg = $('note-msg');
    const fallback = () => { const f = $('note-fallback'); f.hidden = false; f.value = p; f.focus(); f.select(); msg.textContent = T('copy_fallback'); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(p).then(() => { msg.textContent = T('copied', { id }); }, fallback); else fallback();
  }
  $('note-save').addEventListener('click', async () => {
    const text = $('note').value.trim(); const msg = $('note-msg');
    if (!text) { msg.textContent = T('write_first'); return; }
    const r = await fetch(B + '/api/act', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'note_add', params: { text } }) }).then(r => r.json());
    if (!r.ok) { msg.textContent = T('save_failed', { error: r.error }); return; }
    $('note').value = ''; copyPrompt(r.ids[0], text); loadDay(state.day.iso);
  });
  $('pending-chip').addEventListener('click', () => mode === 'pending' ? loadDay(state.day.iso) : showPending());
  $('pull-btn').addEventListener('click', async () => {
    const label = $('pull-btn').textContent;
    $('pull-btn').textContent = T('pulling');
    const r = await fetch(B + '/api/pull', { method: 'POST' }).then(r => r.json());
    $('pull-btn').textContent = label;
    if (!r.ok) alert(T('pull_error', { error: r.error })); else { await loadDay(state.day.iso); if (window.Timeline) window.Timeline.refresh(); }
  });
  // Theme: light / dark / follow the system, remembered on this machine
  const themeBox = $('theme');
  function applyTheme(t) { try { localStorage.setItem('mb.theme', t); } catch (e) {} if (t === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t; for (const b of themeBox.querySelectorAll('button')) b.classList.toggle('on', b.dataset.theme === t); }
  themeBox.addEventListener('click', ev => { const b = ev.target.closest('button'); if (b) applyTheme(b.dataset.theme); });
  (function () { let t = 'auto'; try { t = localStorage.getItem('mb.theme') || 'auto'; } catch (e) {} for (const b of themeBox.querySelectorAll('button')) b.classList.toggle('on', b.dataset.theme === t); })();
  $('order').addEventListener('click', ev => { const b = ev.target.closest('button'); if (!b || b.dataset.order === order) return;
    order = b.dataset.order; store.set('mb.order', order); if (mode === 'day') renderEntries(state); });
  $('entries').addEventListener('mouseover', ev => { const li = ev.target.closest('.ent[data-gnum]'); if (li && window.Timeline) window.Timeline.highlight(li.dataset.gnum); });
  $('entries').addEventListener('mouseleave', () => { if (window.Timeline) window.Timeline.highlight(null); });
  window.App = { loadDay };
  renderHeader(state.header); renderDay(state);
  if (window.Timeline) window.Timeline.legend(state.stage_colors);
  setInterval(async () => { if (mode !== 'day' || document.hidden) return; await loadDay(state.day.iso); if (window.Timeline) window.Timeline.refresh(); }, 30000);
})();
