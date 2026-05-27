// Trading Bot Dashboard — SSE client + htmx helpers

// ── Status bar updater (called by htmx after-request on #status-bar) ──────
window.updateStatusBar = function(event) {
  let data;
  try {
    data = JSON.parse(event.detail.xhr.responseText);
  } catch(e) { return; }

  const flags = data.flags || {};
  const dot = document.getElementById('sb-dot');
  const cronLabel = document.getElementById('sb-cron-label');
  const haltEl = document.getElementById('sb-halt');
  const balanceEl = document.getElementById('sb-balance');
  const pnlEl = document.getElementById('sb-pnl');
  const posEl = document.getElementById('sb-positions');
  const apiEl = document.getElementById('sb-api');
  const ts = document.getElementById('last-updated');

  // Cron dot
  if (dot) {
    dot.className = 'live-dot' + (flags.cron_alive ? '' : ' stale');
  }
  if (cronLabel) {
    const age = (data.cron_status?.market_scan?.age_minutes ?? null);
    cronLabel.textContent = 'cron ' + (age !== null ? Math.round(age) + 'm ago' : '?');
  }

  // Halt
  if (haltEl) {
    haltEl.textContent = flags.trading_halted ? '🔴 HALTED' : '🟢 trading';
    haltEl.style.color = flags.trading_halted ? 'var(--red)' : 'var(--green)';
  }

  // Balance
  if (balanceEl) {
    const bal = data.pnl?.paper_balance_usd ?? 0;
    balanceEl.textContent = '$' + bal.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
  }

  // MTD P&L
  if (pnlEl) {
    const pnl = data.pnl?.mtd_realized_pnl ?? 0;
    const sign = pnl >= 0 ? '+' : '';
    pnlEl.textContent = 'P&L ' + sign + '$' + (pnl||0).toFixed(2);
    pnlEl.style.color = pnl >= 0 ? 'var(--green)' : 'var(--red)';
  }

  // Positions
  if (posEl) {
    const n = data.open_positions?.count ?? 0;
    posEl.textContent = n + ' open';
  }

  // API spend
  if (apiEl) {
    const usd = data.api_spend_mtd?.total_usd ?? 0;
    apiEl.textContent = 'API $' + usd.toFixed(4);
  }

  // Timestamp
  if (ts) {
    ts.textContent = new Date().toLocaleTimeString();
  }
};

// ── Kill-switch ────────────────────────────────────────────────────────────
window.haltTrading = function() {
  if (!confirm('Emergency halt — stop all new trades?')) return;
  fetch('/api/halt', {method: 'POST'})
    .then(r => r.json())
    .then(d => {
      if (d.ok) {
        document.getElementById('sb-halt').textContent = '🔴 HALTED';
        document.getElementById('sb-halt').style.color = 'var(--red)';
        alert('Trading halted. Refresh to confirm.');
      }
    })
    .catch(e => alert('Halt failed: ' + e));
};

// ── SSE live positions ─────────────────────────────────────────────────────
window.startLivePositions = function(tableBodyId) {
  const tbody = document.getElementById(tableBodyId);
  if (!tbody) return;

  const es = new EventSource('/api/positions/live.sse');
  const rows = {};

  es.onmessage = function(e) {
    try {
      const d = JSON.parse(e.data);
      if (d.type === 'ping') return;
      const id = d.id;
      rows[id] = d;
      renderLiveRow(tbody, d);
    } catch(err) { /* ignore */ }
  };

  es.onerror = function() {
    // auto-reconnects; update dot to warn
    const dot = document.getElementById('sb-dot');
    if (dot) dot.className = 'live-dot warn';
  };
};

function renderLiveRow(tbody, d) {
  let tr = tbody.querySelector(`tr[data-id="${d.id}"]`);
  if (!tr) {
    tr = document.createElement('tr');
    tr.dataset.id = d.id;
    tbody.prepend(tr);
  }
  const pnl = d.unrealized_pnl ?? 0;
  const mark = d.mark_price ?? d.entry_price ?? 0;
  const pnlClass = pnl >= 0 ? 'up' : 'down';
  const dirClass = d.direction === 'long' ? 'long' : 'short';
  tr.innerHTML = `
    <td><a href="/trades/${d.id}">${d.id}</a></td>
    <td>${d.asset}</td>
    <td><span class="badge ${dirClass}">${(d.direction||'').toUpperCase()}</span></td>
    <td>$${(d.entry_price||0).toFixed(4)}</td>
    <td class="pnl-live ${pnlClass}">$${mark.toFixed(4)}</td>
    <td class="pnl-live ${pnlClass}">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}</td>
    <td>${d.distance_to_sl_pct != null ? d.distance_to_sl_pct.toFixed(1)+'%' : '—'}</td>
    <td>${d.distance_to_tp_pct != null ? d.distance_to_tp_pct.toFixed(1)+'%' : '—'}</td>
    <td>${d.leverage ?? 1}x</td>
  `;
}

// ── Chart helpers ──────────────────────────────────────────────────────────
window.makeLineChart = function(canvasId, labels, data, label, color) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  return new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label,
        data,
        borderColor: color || '#d4af37',
        backgroundColor: (color || '#d4af37') + '22',
        borderWidth: 2,
        pointRadius: 2,
        fill: true,
        tension: 0.2,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#888', maxTicksLimit: 12 }, grid: { color: '#2a2a32' } },
        y: { ticks: { color: '#888' }, grid: { color: '#2a2a32' } }
      }
    }
  });
};

window.makeBarChart = function(canvasId, labels, data, label, colors) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  const bg = colors || data.map(v => v >= 0 ? '#5aa85a88' : '#d05a5a88');
  const border = colors || data.map(v => v >= 0 ? '#5aa85a' : '#d05a5a');
  return new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{ label, data, backgroundColor: bg, borderColor: border, borderWidth: 1 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#888' }, grid: { color: '#2a2a32' } },
        y: { ticks: { color: '#888' }, grid: { color: '#2a2a32' } }
      }
    }
  });
};
