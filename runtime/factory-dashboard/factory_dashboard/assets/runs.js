(() => {
  const token = document.querySelector('meta[name="factory-token"]').content;
  const main = document.getElementById('main');
  const connection = document.getElementById('connection');
  const el = (tag, props = {}, ...kids) => {
    const node = Object.assign(document.createElement(tag), props);
    for (const kid of kids) node.append(kid);
    return node;
  };
  const badge = (text, kind) => el('span', { className: 'badge ' + (kind || ''), textContent: text });
  const call = async (path, options = {}) => {
    const response = await fetch(path, { cache: 'no-store', ...options, headers: { 'Content-Type': 'application/json', 'X-Factory-Token': token, ...(options.headers || {}) } });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || response.statusText);
    return data;
  };
  const actions = {
    active: ['pause', 'cancel'],
    paused: ['resume', 'cancel'],
    provisioning: ['cancel'],
    cancelled: ['archive'],
    failed: ['archive'],
  };
  async function operate(board, operation) {
    if (operation === 'cancel' && !confirm('Cancel ' + board + '? Its open cards are blocked and the run cannot be revived.')) return;
    const reason = operation === 'pause' || operation === 'cancel' ? (prompt('Reason (optional)') || '') : '';
    try { await call('/api/runs/' + encodeURIComponent(board) + '/' + operation, { method: 'POST', body: JSON.stringify(reason ? { reason } : {}) }); }
    catch (error) { alert(error.message); }
    render();
  }
  function row(run) {
    const state = run.awaiting ? badge('awaiting approval', 'warn') : run.needs_intervention ? badge('needs repair', 'bad') : badge(run.status);
    const blockers = el('td', {}, ...(run.blockers || []).slice(0, 3).map(b => el('div', { textContent: (b.title || b.id) + (b.result ? ' — ' + String(b.result).slice(0, 120) : '') })));
    const buttons = el('td', {}, ...(actions[run.status] || []).map(name => el('button', { textContent: name, onclick: () => operate(run.board_id, name) })));
    const title = (run.root && run.root.title ? run.root.title.replace(/^FACTORY:\s*/, '') : run.name) || run.ticket_id;
    return el('tr', {}, el('td', {}, el('a', { href: '#' + run.board_id, textContent: title })), el('td', {}, state),
      el('td', { textContent: [run.phase, (run.active_stages || []).join(', ')].filter(Boolean).join(' · ') || '—' }), blockers,
      el('td', { textContent: Object.entries(run.counts || {}).map(([k, v]) => v + ' ' + k).join(', ') }), buttons);
  }
  async function detail(id) {
    const data = await call('/api/runs/' + encodeURIComponent(id));
    const usage = data.usage || {};
    const cost = usage.actual_usd != null ? '$' + usage.actual_usd.toFixed(2) : usage.estimated_usd != null ? '~$' + usage.estimated_usd.toFixed(2) : 'unknown';
    const tokens = usage.input_tokens != null ? (usage.input_tokens + (usage.output_tokens || 0)).toLocaleString() + ' tokens' : 'tokens unknown';
    return el('section', {}, el('h2', { textContent: data.board_id + ' · ' + data.status }),
      el('p', { textContent: 'Ticket ' + data.ticket_id + ' · root ' + (data.root_id || '—') + ' · ' + cost + ' · ' + tokens }),
      el('p', { textContent: 'Database: ' + data.db_path }), el('a', { href: '#', textContent: '← all runs' }));
  }
  async function render() {
    try {
      const id = location.hash.slice(1);
      if (id) { main.replaceChildren(await detail(decodeURIComponent(id))); connection.textContent = 'Live'; return; }
      const data = await call('/api/runs');
      const t = data.totals;
      const head = el('tr', {}, ...['Run', 'State', 'Stage', 'Blockers', 'Cards', ''].map(h => el('th', { textContent: h })));
      const table = el('table', {}, el('thead', {}, head), el('tbody', {}, ...data.runs.map(row)));
      const defaults = data.default_board.roots.slice(0, 20).map(r => el('li', { textContent: r.title + ' — ' + r.status + (r.phase ? ' (' + r.phase + ')' : '') + (r.awaiting ? ' · awaiting approval' : '') }));
      main.replaceChildren(
        el('h2', { textContent: 'Factory runs' }),
        el('p', { textContent: t.live + ' live · ' + t.awaiting_approval + ' awaiting approval · ' + t.needs_intervention + ' need repair · ' + t.paused + ' paused · ' + t.failed + ' failed · ' + t.archived + ' archived' }),
        table, el('h3', { textContent: 'Default board (earlier runs)' }), el('ul', {}, ...defaults));
      connection.textContent = 'Live';
    } catch (error) {
      connection.textContent = 'Unavailable';
      main.replaceChildren(el('p', { textContent: error.message }));
    }
  }
  window.addEventListener('hashchange', render);
  render();
  setInterval(render, 10000);
})();
