(() => {
  const token = document.querySelector('meta[name="factory-token"]').content;
  const main = document.getElementById('main');
  const connection = document.getElementById('connection');
  const el = (tag, props = {}, ...kids) => {
    const node = Object.assign(document.createElement(tag), props);
    for (const kid of kids) if (kid != null) node.append(kid);
    return node;
  };
  const call = async (path, options = {}) => {
    const response = await fetch(path, { cache: 'no-store', ...options, headers: { 'Content-Type': 'application/json', 'X-Factory-Token': token, ...(options.headers || {}) } });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || response.statusText);
    return data;
  };

  // ---- plain-language vocabulary
  const ACTIONS = {
    pause: 'Stop handing out new work. Cards already running finish; nothing is lost and you can resume later.',
    resume: 'Let the factory continue handing out work on this run.',
    cancel: 'End this run for good. Open cards are blocked and the run cannot be revived.',
    archive: 'Move this finished or cancelled run out of the list. Its board is kept on disk.',
  };
  const actionsFor = { active: ['pause', 'cancel'], paused: ['resume', 'cancel'], provisioning: ['cancel'], cancelled: ['archive'], failed: ['archive'] };
  const BLOCK_KINDS = {
    needs_input: 'waiting for an answer or decision from you',
    capability: 'the worker said it lacked a tool, access or ability it needed',
    human_review: 'waiting for your review',
  };
  const PHASES = {
    project: 'Building: the team is working through the planned cards',
    plan: 'Planning: the orchestrator is writing the plan',
    human_review: 'Waiting for your approval',
    retro: 'Wrapping up: writing the retrospective',
    blocked: 'Stopped: a stage could not continue',
  };
  function stateOf(run) {
    if (run.awaiting) return { label: 'Waiting for you', kind: 'warn', why: 'The run stopped and needs a decision from you. Open it and pick an option under “Handle it”.' };
    if (run.stalled) return { label: 'Stalled', kind: 'bad', why: 'Nothing is running or queued and the run is not done. It needs a decision from you to move again.' };
    if (run.needs_intervention) return { label: 'Needs repair', kind: 'bad', why: 'Some cards are stuck and the factory cannot get past them by itself. Look at what’s stuck below.' };
    const map = {
      active: { label: 'Running', kind: 'good', why: 'The factory is working on this run. Nothing needed from you.' },
      provisioning: { label: 'Starting', kind: '', why: 'The run board, branch and worktree are being set up.' },
      paused: { label: 'Paused', kind: 'warn', why: 'Someone paused this run. Press resume to continue.' },
      cancelled: { label: 'Cancelled', kind: '', why: 'This run was ended. Archive it to clear it from the list.' },
      failed: { label: 'Failed', kind: 'bad', why: 'The run could not be set up or crashed. Archive it and start a new one.' },
      archived: { label: 'Archived', kind: '', why: 'Finished and put away.' },
    };
    return map[run.status] || { label: run.status, kind: '', why: '' };
  }
  const cleanTitle = t => String(t || '').replace(/^FACTORY:\s*/, '').replace(/\s*\(t_[0-9a-z]+\)\s*$/i, '');
  function stageText(s) {
    // task-scene-env-wiring.g16-implement:0  ->  scene env wiring (implement)
    const m = /^(?:task-)?(.+?)(?:\.g\d+)?-([a-z]+):\d+$/.exec(s);
    return m ? m[1].replace(/[-_]/g, ' ') + ' (' + m[2] + ')' : s.replace(/[-_]/g, ' ');
  }
  const badge = (text, kind) => el('span', { className: 'rb-badge ' + (kind || ''), textContent: text });

  async function operate(board, operation) {
    if (operation === 'cancel' && !confirm('Cancel ' + board + '?\n\n' + ACTIONS.cancel)) return;
    const reason = operation === 'pause' || operation === 'cancel' ? (prompt('Reason (optional)') || '') : '';
    try { await call('/api/runs/' + encodeURIComponent(board) + '/' + operation, { method: 'POST', body: JSON.stringify(reason ? { reason } : {}) }); }
    catch (error) { alert(error.message); }
    render();
  }

  const when = s => s ? new Date(s * 1000).toLocaleString() : '';
  function cardItem(b) {
    const [work, step] = cleanTitle(b.title || b.id).split(' · ');
    const why = b.outcome === 'crashed' || b.outcome === 'gave_up' ? 'the worker crashed' : (BLOCK_KINDS[b.block_kind] || 'stopped');
    const reason = String(b.reason || '').trim();
    return el('li', { className: 'rb-cardline' },
      el('div', { className: 'rb-legacy-head' }, el('strong', { textContent: work }), step ? badge(step.toLowerCase(), '') : null,
        b.superseded ? badge('replaced by a later success', 'good') : null),
      el('div', { className: 'rb-muted', textContent: (b.assignee ? b.assignee + ' · ' : '') + why + (b.created_at ? ' · ' + when(b.created_at) : '') }),
      reason ? el('details', {}, el('summary', { textContent: reason.length > 160 ? reason.slice(0, 160) + '…' : reason }), el('pre', { className: 'rb-reason', textContent: reason })) : el('div', { className: 'rb-muted', textContent: 'No reason recorded.' }),
      el('div', { className: 'rb-ids', textContent: b.id + (b.plan_task ? ' · plan task ' + b.plan_task : '') }),
      b.superseded && b.board_id ? el('div', {}, el('button', { className: 'button secondary', textContent: 'Remove from board', onclick: () => archiveCards(b.board_id, [b.id]) })) : null);
  }
  async function archiveCards(board, cards) {
    if (!confirm('Remove ' + cards.length + ' replaced attempt' + (cards.length > 1 ? 's' : '') + ' from the board?\n\nThey are archived, not deleted: their history stays in the database. Only attempts whose task a later attempt finished can be removed.')) return;
    try { await call('/api/runs/' + encodeURIComponent(board) + '/archive-cards', { method: 'POST', body: JSON.stringify({ cards }) }); }
    catch (error) { alert(error.message); }
    render();
  }

  const RECOVERY = [
    { action: 'retry_stage', label: 'Retry the stopped step', hint: 'Re-run only the step the run stopped on, as a fresh card. Earlier results stay as history. Limited to 2 per step.' },
    { action: 'resume', label: 'Resume as is', hint: 'Let the controller continue from where it stopped, without retrying anything. Use after you fixed the cause yourself (for example a provider key).' },
    { action: 'resume_task', label: 'Resume a parked task', hint: 'Bring one parked task back with its work and budget exactly as they were.', needsTask: true },
    { action: 'park', label: 'Park the stopped task', hint: 'Set the stopped task aside (nothing is lost) and carry on with tasks that don’t depend on it.' },
    { action: 'extra_repairs', label: 'Grant extra repair rounds', hint: 'Give the task in progress 1 or 2 more fix-and-review rounds, then resume.', needsCount: true },
    { action: 'reevaluate', label: 'Re-judge existing evidence', hint: 'Check the evidence already produced against the current rules, without running any step again.' },
  ];
  function recoveryPanel(run) {
    const note = el('textarea', { placeholder: 'What did you decide, and why? This is recorded with the run and passed to the next worker.', rows: 3 });
    const taskSel = el('select', {}, ...(run.parked || []).map(p => el('option', { value: p.task, textContent: p.task })));
    const countSel = el('select', {}, el('option', { value: '1', textContent: '1 more round' }), el('option', { value: '2', textContent: '2 more rounds' }));
    const status = el('div', { className: 'rb-muted' });
    let chosen = run.stalled ? 'retry_stage' : (run.parked || []).length ? 'resume_task' : 'retry_stage';
    const options = el('div', { className: 'rb-options' }, ...RECOVERY.filter(o => !o.needsTask || (run.parked || []).length).map(o => {
      const input = el('input', { type: 'radio', name: 'rec-' + run.board_id, value: o.action, checked: o.action === chosen, onchange: () => { chosen = o.action; } });
      return el('label', { className: 'rb-option' }, input, el('span', {}, el('strong', { textContent: o.label }), el('small', { className: 'rb-muted', textContent: o.hint }),
        o.needsTask ? taskSel : null, o.needsCount ? countSel : null));
    }));
    const apply = el('button', { className: 'button primary', textContent: 'Apply decision', onclick: async () => {
      const body = { action: chosen, note: note.value };
      if (chosen === 'resume_task') body.task = taskSel.value;
      if (chosen === 'extra_repairs') body.count = Number(countSel.value);
      if (!confirm('Apply “' + RECOVERY.find(o => o.action === chosen).label + '” to this run?')) return;
      apply.disabled = true; status.textContent = 'Applying… (this can take up to a minute)';
      try { const r = await call('/api/runs/' + encodeURIComponent(run.board_id) + '/recover', { method: 'POST', body: JSON.stringify(body) }); status.textContent = 'Done: ' + (r.result || 'applied'); note.value = ''; setTimeout(render, 1500); }
      catch (error) { status.textContent = ''; status.append(el('span', { className: 'error', textContent: error.message })); }
      finally { apply.disabled = false; }
    } });
    return el('div', { className: 'rb-recover' }, el('h4', { textContent: 'Handle it' }),
      el('p', { className: 'rb-muted', textContent: 'These go through the Factory controller, the same way an operator resumes a run from the terminal. Cards are never unblocked behind its back.' }),
      options, note, el('div', { className: 'rb-actions' }, apply), status);
  }

  function runCard(run) {
    const s = stateOf(run);
    const title = cleanTitle(run.root && run.root.title ? run.root.title : run.name) || run.ticket_id;
    const counts = run.counts || {};
    // Archived cards (removed attempts) are history: they don't count toward the board's progress.
    const total = Object.entries(counts).filter(([k]) => k !== 'archived').reduce((a, [, v]) => a + v, 0);
    const done = counts.done || 0;
    const blockedCount = counts.blocked || 0;
    const nReplaced = (run.blockers || []).filter(b => b.superseded).length;
    const mainBlocked = run.root && run.root.status === 'blocked' && !(run.blockers || []).some(b => b.id === run.root_id) ? 1 : 0;
    const parts = [];
    if (mainBlocked) parts.push('1 is the run’s main card, which always shows as blocked while the controller runs it');
    if (nReplaced) parts.push(nReplaced + ' replaced attempt' + (nReplaced > 1 ? 's' : ''));
    const progress = total ? el('div', { className: 'rb-progress' },
      el('div', { className: 'rb-bar' }, el('span', { style: 'width:' + Math.round(100 * done / total) + '%' })),
      el('span', { textContent: done + ' of ' + total + ' cards done' + Object.entries(counts).filter(([k]) => !['done', 'archived'].includes(k)).map(([k, v]) => ' · ' + v + ' ' + k).join('') +
        (blockedCount && parts.length ? ' (' + parts.join('; ') + ')' : '') + (counts.archived ? ' · ' + counts.archived + ' removed' : '') })) : null;
    const doing = (run.active_stages || []).map(stageText);
    const facts = el('dl', { className: 'rb-facts' },
      el('dt', { textContent: 'Where it is' }), el('dd', { textContent: PHASES[run.phase] || (run.phase ? run.phase : '—') }),
      doing.length ? el('dt', { textContent: 'Working on now' }) : null, doing.length ? el('dd', { textContent: doing.join(', ') }) : null,
      run.branch ? el('dt', { textContent: 'Branch' }) : null, run.branch ? el('dd', { className: 'rb-mono', textContent: run.branch }) : null,
      el('dt', { textContent: 'Board' }), el('dd', { className: 'rb-mono', textContent: run.board_id + (run.root_id ? ' · root ' + run.root_id : '') }),
      run.reason ? el('dt', { textContent: 'Last reason' }) : null, run.reason ? el('dd', { textContent: run.reason }) : null);
    const cards = (run.blockers || []).map(b => ({ ...b, board_id: run.status === 'active' || run.status === 'paused' ? run.board_id : '' }));
    const open = cards.filter(b => !b.superseded);
    const replaced = cards.filter(b => b.superseded);
    const stuck = el('div', {},
      run.stalled ? el('div', { className: 'rb-alert' }, el('strong', { textContent: 'Stalled. ' }),
        'No card is queued or running, but the run isn’t finished or waiting for approval, so it won’t move by itself. ' +
        (run.active_task ? 'It was last working on “' + run.active_task.replace(/-/g, ' ') + '”. ' : '') + 'Use “Handle it” below.') : null,
      open.length ? el('h4', { textContent: 'Cards that need attention (' + open.length + ')' }) : null,
      open.length ? el('ul', { className: 'rb-stuck' }, ...open.map(cardItem)) : null,
      (run.parked || []).length ? el('h4', { textContent: 'Parked tasks (' + run.parked.length + ')' }) : null,
      (run.parked || []).length ? el('ul', { className: 'rb-stuck' }, ...run.parked.map(p => el('li', {}, el('strong', { textContent: p.task.replace(/-/g, ' ') }),
        el('div', { className: 'rb-muted', textContent: 'Set aside while other tasks continue. ' + (p.at ? when(p.at) : '') }), el('pre', { className: 'rb-reason', textContent: p.reason || '' })))) : null,
      replaced.length ? el('details', {}, el('summary', { textContent: replaced.length + ' earlier failed attempt' + (replaced.length > 1 ? 's' : '') + ', already replaced by a later success (history only, nothing to do)' }),
        replaced[0].board_id ? el('div', { className: 'rb-actions' }, el('button', { className: 'button secondary', textContent: 'Remove all ' + replaced.length + ' from the board', onclick: () => archiveCards(run.board_id, replaced.map(b => b.id)) })) : null,
        el('ul', { className: 'rb-stuck' }, ...replaced.map(cardItem))) : null,
      run.status === 'active' && (run.needs_intervention || run.awaiting || (run.parked || []).length) ? recoveryPanel(run) : null);
    const buttons = el('div', { className: 'rb-actions' }, ...(actionsFor[run.status] || []).map(name =>
      el('div', {}, el('button', { className: 'button secondary', textContent: name, title: ACTIONS[name], onclick: () => operate(run.board_id, name) }),
        el('small', { className: 'rb-muted', textContent: ACTIONS[name] }))));
    return el('article', { className: 'rb-card' },
      el('header', {}, el('h2', {}, el('a', { href: '#' + run.board_id, textContent: title })), badge(s.label, s.kind)),
      el('p', { className: 'rb-why', textContent: s.why }), progress, facts, stuck, buttons);
  }

  function legacyItem(r) {
    const s = r.status === 'done' ? { label: 'Done', kind: 'good' } : r.awaiting ? { label: 'Waiting for you', kind: 'warn' } : { label: 'Stopped', kind: 'bad' };
    return el('li', {}, el('div', { className: 'rb-legacy-head' }, badge(s.label, s.kind), el('span', { textContent: cleanTitle(r.title) }), el('span', { className: 'rb-ids', textContent: r.id })),
      r.reason ? el('div', { className: 'rb-muted', textContent: 'Why: ' + r.reason }) : null);
  }

  async function detail(id) {
    const data = await call('/api/runs/' + encodeURIComponent(id));
    const usage = data.usage || {};
    const cost = usage.actual_usd != null ? '$' + usage.actual_usd.toFixed(2) : usage.estimated_usd != null ? '~$' + usage.estimated_usd.toFixed(2) + ' (estimate)' : 'unknown';
    const tokens = usage.input_tokens != null ? (usage.input_tokens + (usage.output_tokens || 0)).toLocaleString() : 'unknown';
    return el('section', {}, el('a', { href: '#', textContent: '← all runs' }), runCard(data),
      el('dl', { className: 'rb-facts' },
        el('dt', { textContent: 'Ticket' }), el('dd', { className: 'rb-mono', textContent: data.ticket_id }),
        el('dt', { textContent: 'Cost so far' }), el('dd', { textContent: cost }),
        el('dt', { textContent: 'Tokens' }), el('dd', { textContent: tokens }),
        el('dt', { textContent: 'Database' }), el('dd', { className: 'rb-mono', textContent: data.db_path })));
  }

  async function render() {
    try {
      const id = location.hash.slice(1);
      if (id) { main.replaceChildren(await detail(decodeURIComponent(id))); connection.textContent = 'Live'; return; }
      const data = await call('/api/runs');
      const t = data.totals;
      const current = data.runs.filter(r => r.status !== 'archived');
      const archived = data.runs.filter(r => r.status === 'archived');
      const chip = (n, label, hint) => el('div', { className: 'rb-chip' + (n ? '' : ' zero'), title: hint }, el('strong', { textContent: n }), el('span', { textContent: label }));
      const legacy = data.default_board.roots;
      const legacyOpen = legacy.filter(r => r.status !== 'done');
      main.replaceChildren(
        el('h1', { textContent: 'Factory runs' }),
        el('p', { className: 'rb-intro', textContent: 'A run is one request you gave the factory (for example “make room 1 look like Look D”). Each run gets its own kanban board, git branch and worktree, so runs never step on each other. Below: what each run is doing, whether it needs you, and what’s stuck.' }),
        el('div', { className: 'rb-chips' },
          chip(t.live, 'live', 'Runs that are running, starting or paused'),
          chip(t.awaiting_approval, 'waiting for you', 'Runs stopped at an approval gate'),
          chip(t.needs_intervention, 'need repair', 'Runs with stuck cards the factory cannot clear itself'),
          chip(t.paused, 'paused', 'Runs someone paused'),
          chip(t.failed, 'failed', 'Runs that could not start or crashed'),
          chip(t.archived, 'archived', 'Finished runs put away')),
        el('h3', { textContent: 'Current runs' }),
        current.length ? el('div', { className: 'rb-list' }, ...current.map(runCard)) : el('p', { className: 'rb-muted', textContent: 'No runs right now. Start one with “New task” on the Timeline page.' }),
        el('h3', { textContent: 'Older runs on the shared board' }),
        el('p', { className: 'rb-muted', textContent: 'Before each run got its own board, every run lived on the shared “default” board. These are those runs. Retries of the same request show up as separate entries. Nothing here is running; the ones marked “waiting for you” were left at an approval gate and are superseded by newer attempts.' }),
        el('details', {}, el('summary', { textContent: legacyOpen.length + ' stopped or waiting · ' + (legacy.length - legacyOpen.length) + ' done' }),
          el('ul', { className: 'rb-legacy' }, ...legacy.map(legacyItem))),
        archived.length ? el('details', {}, el('summary', { textContent: archived.length + ' archived run' + (archived.length > 1 ? 's' : '') }),
          el('div', { className: 'rb-list' }, ...archived.map(runCard))) : null);
      connection.textContent = 'Live';
    } catch (error) {
      connection.textContent = 'Unavailable';
      main.replaceChildren(el('p', { textContent: error.message }));
    }
  }
  window.addEventListener('hashchange', render);
  render();
  // Don't redraw under someone reading a reason or writing a note.
  setInterval(() => { if (!document.querySelector('details[open]') && !main.contains(document.activeElement) && !document.querySelector('.rb-recover textarea')?.value) render(); }, 10000);
})();
