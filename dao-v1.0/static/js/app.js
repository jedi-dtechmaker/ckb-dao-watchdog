function escapeHTML(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
}

function explorerURL(address) {
  return 'https://explorer.nervos.org/address/' + encodeURIComponent(address || '');
}

/**
 * CKB DAO Watchdog — Human-friendly Application Logic
 */

// Global State
const state = {
  lang: localStorage.getItem('watchdog_lang') || 'en',
  currentView: 'runner',
  currentAudit: null,
  activeOptionIndex: 0,
  filterStatus: 'all', // 'all' | 'review' | 'verified'
  viewMode: 'grouped', // 'grouped' | 'flat'
  searchQuery: '',
  archives: [],
  sseSource: null
};

// Conversational, natural translations
const i18n = {
  en: {
    subtitle_tag: "Governance Vote Verifier",
    nav_runner: "Audit a Proposal",
    nav_archives: "Past Reports",
    nav_cli: "How It Works",
    hero_title: "Check CKB DAO Voting Weights",
    hero_desc: "Make sure voting weight shown on Metaforo actually matches the voter's locked CKB deposits in Nervos DAO.",
    btn_inspect: "Inspect",
    btn_start_audit: "Verify On-Chain",
    presets_label: "Try a past proposal:",
    progress_verifying: "Checking Nervos DAO deposits on-chain...",
    drawer_terminal: "Show detailed verification log",
    thread_label: "Proposal",
    btn_export_csv: "Export CSV",
    btn_export_json: "Export JSON",
    tabs_options: "Voting Choices:",
    stat_total_voters: "Total Voters",
    stat_metaforo_weight: "Metaforo Recorded",
    stat_metaforo_sub: "Weight reported on forum",
    stat_chain_weight: "On-Chain Calculated",
    stat_chain_sub: "Sum of live Nervos DAO deposits",
    stat_discrepancies: "Discrepancies",
    stat_match_rate: "Match Rate",
    filter_all: "All",
    filter_review: "Needs Review",
    filter_verified: "Matches",
    mode_voters: "By Voter",
    mode_flat: "By Address",
    th_status: "Status",
    th_voter: "Voter",
    th_time: "Vote Timestamp",
    th_metaforo_wt: "Metaforo Weight",
    th_chain_wt: "On-Chain Weight",
    th_addresses: "Bound Addresses & Deposits",
    empty_no_voters: "No matching voters found",
    empty_try_filter: "Try searching for a different keyword or toggle the filter.",
    archives_title: "Past Proposal Audits",
    archives_desc: "Browse reports from previously audited CKB DAO governance votes stored in this repository.",
    docs_title: "How CKB DAO Watchdog Works",
    docs_calc_title: "⚖️ How Voting Weights Are Calculated",
    docs_calc_desc: "CKB DAO governance uses Nervos DAO locked CKB capacity to determine vote weight. The Watchdog tool independently checks every single vote:",
    docs_cli_title: "💻 Running from the Command Line",
    docs_cli_desc: "Prefer using a terminal? You can run the exact same logic with Python directly:",
    docs_docker_title: "🐳 Running in Docker",
    btn_got_it: "Got It",
    loading_archives: "Loading archived reports...",
    status_verified: "Matches",
    status_discrepancy: "Needs Review",
    lang_toggle_label: "中文"
  },
  zh: {
    subtitle_tag: "治理投票链上核验工具",
    nav_runner: "核验提案投票",
    nav_archives: "历史报告",
    nav_cli: "运作原理",
    hero_title: "验证 CKB DAO 治理投票权重",
    hero_desc: "核对 Metaforo 论坛上的投票权重是否与投票人在 Nervos DAO 链上的实际存单一致。",
    btn_inspect: "解析提案",
    btn_start_audit: "链上核验",
    presets_label: "试试历史提案：",
    progress_verifying: "正在核对链上存单...",
    drawer_terminal: "展开详细核对日志",
    thread_label: "提案",
    btn_export_csv: "导出 CSV",
    btn_export_json: "导出 JSON",
    tabs_options: "投票选项：",
    stat_total_voters: "总投票人",
    stat_metaforo_weight: "论坛记录权重",
    stat_metaforo_sub: "论坛投票记录的总权重",
    stat_chain_weight: "链上核算权重",
    stat_chain_sub: "实时活细胞统计总权重",
    stat_discrepancies: "异常票数",
    stat_match_rate: "一致率",
    filter_all: "全部",
    filter_review: "需复核",
    filter_verified: "一致",
    mode_voters: "按投票人",
    mode_flat: "按地址",
    th_status: "状态",
    th_voter: "投票人",
    th_time: "投票时间",
    th_metaforo_wt: "论坛权重",
    th_chain_wt: "链上权重",
    th_addresses: "绑定地址及各自权重",
    empty_no_voters: "没有找到匹配的投票记录",
    empty_try_filter: "请尝试更改搜索关键字或状态筛选器。",
    archives_title: "历史提案审计报告",
    archives_desc: "浏览本工具仓库内已收录的历史 CKB DAO 投票审计报告，可直接加载查验每一票链上明细与差异分析。",
    docs_title: "CKB DAO 审计原理与使用指南",
    docs_calc_title: "⚖️ 验证与权重计算原理",
    docs_calc_desc: "CKB DAO 治理投票以用户在 Nervos DAO 锁仓的 CKB 容量计算票权。Watchdog 工具通过 5 步流程逐一核实：",
    docs_cli_title: "💻 使用命令行 (CLI) 运行",
    docs_cli_desc: "更喜欢终端命令行？直接使用 Python 执行即可：",
    docs_docker_title: "🐳 使用 Docker 容器化运行",
    btn_got_it: "我知道了",
    loading_archives: "正在加载历史审计档案...",
    status_verified: "一致",
    status_discrepancy: "需复核",
    lang_toggle_label: "English"
  }
};

// Formatting utilities
function formatCKB(num) {
  if (num === undefined || num === null || isNaN(num)) return '0 CKB';
  return Number(num).toLocaleString('en-US') + ' CKB';
}

function truncateAddress(addr) {
  if (!addr) return 'None';
  if (addr.length <= 20) return addr;
  return `${addr.slice(0, 10)}...${addr.slice(-8)}`;
}

function showToast(message, isError = false) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${isError ? 'toast-error' : ''}`;
  toast.innerHTML = `<span>${isError ? '⚠️' : '🐕'}</span><span>${escapeHTML(message)}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(8px)';
    setTimeout(() => toast.remove(), 250);
  }, 3500);
}

// Localization Handler
function updateLocalization() {
  const currentTexts = i18n[state.lang];
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (currentTexts[key]) {
      el.textContent = currentTexts[key];
    }
  });

  const langLabel = document.getElementById('current-lang-text');
  if (langLabel) {
    langLabel.textContent = currentTexts.lang_toggle_label;
  }
}

function toggleLanguage() {
  state.lang = state.lang === 'en' ? 'zh' : 'en';
  localStorage.setItem('watchdog_lang', state.lang);
  updateLocalization();
  if (state.currentAudit) {
    renderAuditData();
  }
}

// Navigation View Switcher
function switchView(viewName) {
  state.currentView = viewName;
  document.querySelectorAll('.view-panel').forEach(sec => sec.classList.add('hidden'));
  document.querySelectorAll('.menu-item').forEach(btn => btn.classList.remove('active'));

  if (viewName === 'runner') {
    document.getElementById('runner-view').classList.remove('hidden');
    document.getElementById('nav-runner-btn')?.classList.add('active');
  } else if (viewName === 'archives') {
    document.getElementById('archives-view').classList.remove('hidden');
    document.getElementById('nav-archives-btn')?.classList.add('active');
    loadArchives();
  }
}

// Preset Loader
function loadPreset(url, threadId) {
  const input = document.getElementById('metaforo-url-input');
  input.value = url;
  switchView('runner');

  const archived = state.archives.find(p => String(p.thread_id) === String(threadId));
  if (archived && archived.files.length > 0) {
    showToast(`Loading report for #${threadId}...`);
    loadHistoricalProposal(archived);
  } else {
    handleInspectPoll();
  }
}

function clearInput() {
  document.getElementById('metaforo-url-input').value = '';
}

// Inspect Poll Handler (Preview)
async function handleInspectPoll() {
  const input = document.getElementById('metaforo-url-input');
  const url = input.value.trim();
  if (!url) {
    showToast('Please enter a proposal link or ID', true);
    return;
  }

  const btn = document.getElementById('inspect-btn');
  btn.disabled = true;
  btn.textContent = 'Inspecting...';

  try {
    const res = await fetch('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    const data = await res.json();

    if (!data.success) {
      showToast(data.error || 'Failed to inspect proposal', true);
      return;
    }

    const options = data.options.map(opt => ({
      option_id: opt.id,
      option_name: opt.html,
      option_weight: opt.weights,
      export_data: []
    }));

    state.currentAudit = {
      thread_id: data.thread_id,
      timestamp: 'Preview Mode',
      options: options,
      isPreview: true
    };
    state.activeOptionIndex = 0;

    renderAuditData();
    showToast(`Found ${options.length} voting options for #${data.thread_id}`);
  } catch (err) {
    showToast(`Network error: ${escapeHTML(err.message)}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = i18n[state.lang].btn_inspect;
  }
}

// Start Live Full On-Chain Audit
async function handleStartAudit() {
  const input = document.getElementById('metaforo-url-input');
  const url = input.value.trim();
  if (!url) {
    showToast('Please enter a proposal link or ID', true);
    return;
  }

  if (state.sseSource) {
    state.sseSource.close();
  }

  const startBtn = document.getElementById('start-audit-btn');
  startBtn.disabled = true;

  const progressCard = document.getElementById('live-progress-card');
  progressCard.classList.remove('hidden');
  updateProgress(0, 'Connecting to CKB blockchain...', 'Preparing to audit votes...');
  clearTerminal();

  try {
    const res = await fetch('/api/audit/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    const data = await res.json();

    if (!data.success) {
      showToast(data.error || 'Failed to start audit', true);
      progressCard.classList.add('hidden');
      startBtn.disabled = false;
      return;
    }

    const jobId = data.job_id;
    appendLog(`[Watchdog] Audit started for proposal #${data.thread_id}`, 'info');

    state.currentAudit = {
      thread_id: data.thread_id,
      timestamp: 'Auditing now...',
      isRunning: true,
      options: [],
      isPreview: false
    };

    const sse = new EventSource(`/api/audit/stream/${jobId}`);
    state.sseSource = sse;

    sse.addEventListener('poll_info', (e) => {
      const payload = JSON.parse(e.data);
      state.currentAudit.thread_id = payload.thread_id;
      state.currentAudit.timestamp = payload.timestamp;
      state.currentAudit.options = payload.options.map(opt => ({
        option_id: opt.id,
        option_name: opt.html,
        option_weight: opt.weights,
        export_data: []
      }));
      renderAuditData();
    });

    sse.addEventListener('option_start', (e) => {
      const payload = JSON.parse(e.data);
      updateProgress(10, `Auditing Choice: ${payload.option_name}`, `Reported Weight: ${formatCKB(payload.option_weight)}`);
      appendLog(`Checking choice: ${payload.option_name} (${payload.option_index}/${payload.total_options})`, 'info');
    });

    sse.addEventListener('voter_progress', (e) => {
      const payload = JSON.parse(e.data);
      updateProgress(
        payload.percent,
        `Checking ${payload.current_voter} (${payload.voter_index} of ${payload.total_voters})`,
        `Querying Nervos DAO live cells for UID ${payload.user_id}...`
      );
    });

    sse.addEventListener('voter_completed', (e) => {
      const voter = JSON.parse(e.data);
      const opt = state.currentAudit.options.find(o => o.option_id === voter.option_id);
      if (opt) {
        if (voter.weight_list && voter.weight_list.length > 0) {
          voter.weight_list.forEach(item => {
            opt.export_data.push({
              nickname: voter.nickname,
              userid: voter.user_id,
              voted_at: voter.voted_at,
              "total weight(metaforo)": voter.total_weight_metaforo,
              "total weight(on chain, floored)": voter.total_weight_onchain,
              address: item.address,
              "address weight(floored)": Math.floor(item.Weight),
              need_review: voter.need_review,
              explorer_url: `https://explorer.nervos.org/address/${item.address}`
            });
          });
        } else {
          opt.export_data.push({
            nickname: voter.nickname,
            userid: voter.user_id,
            voted_at: voter.voted_at,
            "total weight(metaforo)": voter.total_weight_metaforo,
            "total weight(on chain, floored)": voter.total_weight_onchain,
            address: "",
            "address weight(floored)": 0,
            need_review: voter.need_review,
            explorer_url: ""
          });
        }
        renderAuditData();
      }
    });

    sse.addEventListener('log', (e) => {
      const msg = JSON.parse(e.data);
      appendLog(msg);
    });

    sse.addEventListener('complete', (e) => {
      const payload = JSON.parse(e.data);
      updateProgress(100, 'Audit Complete', 'All ballots checked against Nervos DAO on-chain deposits.');
      appendLog('Audit finished successfully.', 'success');
      showToast('Audit complete!');
      sse.close();
      startBtn.disabled = false;
      state.currentAudit.options = payload.options;
      state.currentAudit.isRunning = false;
      state.currentAudit.timestamp = payload.timestamp;
      renderAuditData();
    });

    sse.addEventListener('error', (e) => {
      try {
        const err = JSON.parse(e.data);
        appendLog(`Error: ${err}`, 'error');
        showToast(`Audit failed: ${err}`, true);
      } catch (ex) {
        appendLog(`Connection closed.`, 'warn');
      }
      sse.close();
      startBtn.disabled = false;
    });

  } catch (err) {
    showToast(`Failed: ${escapeHTML(err.message)}`, true);
    startBtn.disabled = false;
  }
}

// Live Progress UI Updater
function updateProgress(percent, title, detail) {
  const bar = document.getElementById('progress-bar-fill');
  const pct = document.getElementById('progress-percentage');
  const stText = document.getElementById('progress-status-text');
  const dtText = document.getElementById('progress-detail-text');

  if (bar) bar.style.width = `${percent}%`;
  if (pct) pct.textContent = `${Math.round(percent)}%`;
  if (stText && title) stText.textContent = title;
  if (dtText && detail) dtText.textContent = detail;
}

// Live Terminal Console
function appendLog(line, type = '') {
  const term = document.getElementById('terminal-logs');
  if (!term) return;
  const div = document.createElement('div');
  div.className = `log-line ${type}`;
  div.textContent = line;
  term.appendChild(div);
  term.scrollTop = term.scrollHeight;
}

function clearTerminal() {
  const term = document.getElementById('terminal-logs');
  if (term) term.innerHTML = '';
}

function toggleTerminalDrawer() {
  const content = document.getElementById('terminal-drawer-content');
  const chevron = document.getElementById('terminal-chevron');
  if (!content) return;
  if (content.style.display === 'none') {
    content.style.display = 'block';
    chevron?.classList.add('open');
  } else {
    content.style.display = 'none';
    chevron?.classList.remove('open');
  }
}

// Render Current Audit
function renderAuditData() {
  const audit = state.currentAudit;
  if (!audit) return;

  const container = document.getElementById('audit-results-container');
  container.classList.remove('hidden');

  // Banner
  document.getElementById('banner-thread-id').textContent = audit.thread_id ? `#${audit.thread_id}` : 'Archived report';
  document.getElementById('banner-timestamp').textContent = `Audited: ${audit.timestamp || 'N/A'}`;

  const statusBadge = document.getElementById('banner-status-badge');
  if (audit.isPreview) {
    statusBadge.className = 'tag-alert';
    statusBadge.textContent = 'Preview';
  } else {
    statusBadge.className = 'tag-clean';
    statusBadge.textContent = audit.isRunning ? 'Running' : 'Report';
  }

  // Option Tabs
  const tabsContainer = document.getElementById('poll-options-tabs');
  tabsContainer.innerHTML = '';

  audit.options.forEach((opt, idx) => {
    const btn = document.createElement('button');
    btn.className = `option-tab-btn ${idx === state.activeOptionIndex ? 'active' : ''}`;
    btn.onclick = () => {
      state.activeOptionIndex = idx;
      renderAuditData();
    };

    const optWeight = opt.option_weight ? formatCKB(opt.option_weight) : '0 CKB';
    btn.innerHTML = `<span>${escapeHTML(opt.option_name)}</span> <span class="option-tab-badge">${optWeight}</span>`;
    tabsContainer.appendChild(btn);
  });

  const activeOption = audit.options[state.activeOptionIndex] || { export_data: [] };
  const allRows = activeOption.export_data || [];

  // Group by voter for metrics
  const voterMap = new Map();
  allRows.forEach(row => {
    const key = row.userid || row.nickname;
    if (!voterMap.has(key)) {
      voterMap.set(key, {
        nickname: row.nickname,
        userid: row.userid,
        voted_at: row.voted_at,
        metaforo_weight: Number(row["total weight(metaforo)"] || 0),
        onchain_weight: Number(row["total weight(on chain, floored)"] || 0),
        need_review: Boolean(row.need_review || row["⚠️need_review"]),
        addresses: []
      });
    }
    if (row.address) {
      voterMap.get(key).addresses.push({
        address: row.address,
        weight: Number(row["address weight(floored)"] || 0),
        explorer_url: row.explorer_url
      });
    }
  });

  const voters = Array.from(voterMap.values());
  const totalVoters = voters.length;
  const totalMetaforoWeight = voters.reduce((acc, v) => acc + v.metaforo_weight, 0);
  const totalOnChainWeight = voters.reduce((acc, v) => acc + v.onchain_weight, 0);
  const discrepancies = voters.filter(v => v.need_review).length;
  const matchRate = totalVoters > 0
    ? (((totalVoters - discrepancies) / totalVoters) * 100).toFixed(1)
    : '100.0';

  // Update Stats Cards
  document.getElementById('stat-voters-count').textContent = totalVoters;
  document.getElementById('stat-metaforo-weight').textContent = formatCKB(totalMetaforoWeight);
  document.getElementById('stat-chain-weight').textContent = formatCKB(totalOnChainWeight);

  const discCard = document.getElementById('discrepancy-metric-card');
  const discCount = document.getElementById('stat-discrepancies-count');
  const discSub = document.getElementById('stat-discrepancies-sub');
  discCount.textContent = discrepancies;

  if (discrepancies > 0) {
    discCard.classList.add('has-discrepancies');
    discSub.textContent = `${discrepancies} voter(s) need manual review`;
  } else {
    discCard.classList.remove('has-discrepancies');
    discSub.textContent = 'All weights match on-chain';
  }

  document.getElementById('stat-match-rate').textContent = `${matchRate}%`;

  // Update Filter Counters
  document.getElementById('count-all').textContent = totalVoters;
  document.getElementById('count-review').textContent = discrepancies;
  document.getElementById('count-verified').textContent = totalVoters - discrepancies;

  // Render Table
  renderTable(voters, allRows);
}

// Render Table
function renderTable(voters, allRows) {
  const tbody = document.getElementById('audit-table-body');
  const emptyState = document.getElementById('table-empty-state');
  tbody.innerHTML = '';

  const q = state.searchQuery.toLowerCase();

  if (state.viewMode === 'grouped') {
    let filtered = voters.filter(v => {
      if (state.filterStatus === 'review' && !v.need_review) return false;
      if (state.filterStatus === 'verified' && v.need_review) return false;

      if (q) {
        const matchNick = v.nickname.toLowerCase().includes(q);
        const matchId = String(v.userid).toLowerCase().includes(q);
        const matchAddr = v.addresses.some(a => a.address.toLowerCase().includes(q));
        if (!matchNick && !matchId && !matchAddr) return false;
      }
      return true;
    });

    if (filtered.length === 0) {
      emptyState.classList.remove('hidden');
      return;
    }
    emptyState.classList.add('hidden');

    filtered.forEach(v => {
      const tr = document.createElement('tr');
      if (v.need_review) tr.className = 'row-discrepancy';

      const isMatch = v.metaforo_weight === v.onchain_weight;
      const statusHtml = v.need_review
        ? `<span class="tag-alert">${i18n[state.lang].status_discrepancy}</span>`
        : `<span class="tag-clean">${i18n[state.lang].status_verified}</span>`;

      let addressListHtml = '<span style="color:var(--text-dim);">No bound addresses</span>';
      if (v.addresses.length > 0) {
        addressListHtml = `
          <div class="addresses-group">
            ${v.addresses.map(a => `
              <div class="address-pill">
                <a href="${explorerURL(a.address)}" target="_blank" rel="noopener" class="address-link" title="${escapeHTML(a.address)}">
                  ${escapeHTML(truncateAddress(a.address))}
                </a>
                <span class="address-wt">${formatCKB(a.weight)}</span>
              </div>
            `).join('')}
          </div>
        `;
      }

      tr.innerHTML = `
        <td>${statusHtml}</td>
        <td>
          <div class="voter-cell">
            <span class="voter-name">${escapeHTML(v.nickname)}</span>
            <span class="voter-id">ID: ${escapeHTML(v.userid)}</span>
          </div>
        </td>
        <td><span class="voter-time">${escapeHTML(v.voted_at || 'N/A')}</span></td>
        <td class="text-right weight-cell">${formatCKB(v.metaforo_weight)}</td>
        <td class="text-right weight-cell ${isMatch ? 'weight-match' : 'weight-diff'}">
          ${formatCKB(v.onchain_weight)}
        </td>
        <td>${addressListHtml}</td>
      `;

      tbody.appendChild(tr);
    });

  } else {
    // Flat View
    let filtered = allRows.filter(row => {
      const isReview = Boolean(row.need_review || row["⚠️need_review"]);
      if (state.filterStatus === 'review' && !isReview) return false;
      if (state.filterStatus === 'verified' && isReview) return false;

      if (q) {
        const matchNick = (row.nickname || '').toLowerCase().includes(q);
        const matchId = String(row.userid || '').toLowerCase().includes(q);
        const matchAddr = (row.address || '').toLowerCase().includes(q);
        if (!matchNick && !matchId && !matchAddr) return false;
      }
      return true;
    });

    if (filtered.length === 0) {
      emptyState.classList.remove('hidden');
      return;
    }
    emptyState.classList.add('hidden');

    filtered.forEach(row => {
      const tr = document.createElement('tr');
      const isReview = Boolean(row.need_review || row["⚠️need_review"]);
      if (isReview) tr.className = 'row-discrepancy';

      const statusHtml = isReview
        ? `<span class="tag-alert">${i18n[state.lang].status_discrepancy}</span>`
        : `<span class="tag-clean">${i18n[state.lang].status_verified}</span>`;

      const addrHtml = row.address
        ? `<a href="${explorerURL(row.address)}" target="_blank" rel="noopener" class="address-link" title="${escapeHTML(row.address)}">
             ${escapeHTML(truncateAddress(row.address))}
           </a> <span class="address-wt">(${formatCKB(row["address weight(floored)"] || 0)})</span>`
        : `<span style="color:var(--text-dim);">None</span>`;

      tr.innerHTML = `
        <td>${statusHtml}</td>
        <td>
          <div class="voter-cell">
            <span class="voter-name">${escapeHTML(row.nickname)}</span>
            <span class="voter-id">ID: ${escapeHTML(row.userid)}</span>
          </div>
        </td>
        <td><span class="voter-time">${escapeHTML(row.voted_at || 'N/A')}</span></td>
        <td class="text-right weight-cell">${formatCKB(row["total weight(metaforo)"] || 0)}</td>
        <td class="text-right weight-cell ${!isReview ? 'weight-match' : 'weight-diff'}">
          ${formatCKB(row["total weight(on chain, floored)"] || 0)}
        </td>
        <td>${addrHtml}</td>
      `;

      tbody.appendChild(tr);
    });
  }
}

// Table Search & Filters
function handleTableSearch() {
  const input = document.getElementById('table-search-input');
  state.searchQuery = input.value.trim();
  renderAuditData();
}

function setFilter(status) {
  state.filterStatus = status;
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-filter') === status);
  });
  renderAuditData();
}

function setViewMode(mode) {
  state.viewMode = mode;
  document.getElementById('view-grouped-btn')?.classList.toggle('active', mode === 'grouped');
  document.getElementById('view-flat-btn')?.classList.toggle('active', mode === 'flat');
  renderAuditData();
}

// Export CSV / JSON helpers
function exportCurrentCSV() {
  if (!state.currentAudit) return;
  const activeOpt = state.currentAudit.options[state.activeOptionIndex];
  if (!activeOpt || !activeOpt.export_data || activeOpt.export_data.length === 0) {
    showToast('No records to export', true);
    return;
  }

  const rows = activeOpt.export_data;
  const headers = ["nickname", "userid", "voted_at", "total weight(metaforo)", "total weight(on chain, floored)", "⚠️need_review", "address", "address weight(floored)", "explorer_url"];

  const csvCell = value => `"${String(value ?? '').replace(/"/g, '""')}"`;
  const lines = [headers.map(csvCell).join(',')];
  rows.forEach(row => {
    lines.push(headers.map(key => csvCell(key === '⚠️need_review'
      ? Boolean(row.need_review || row['⚠️need_review']) : row[key])).join(','));
  });
  const objectURL = URL.createObjectURL(new Blob([lines.join('\r\n')], {
    type: 'text/csv;charset=utf-8'
  }));
  const link = document.createElement('a');
  link.href = objectURL;
  link.download = `audit_${state.currentAudit.thread_id || 'archive'}_${activeOpt.option_name}.csv`;
  link.click();
  URL.revokeObjectURL(objectURL);
}

function exportCurrentJSON() {
  if (!state.currentAudit) return;
  const activeOpt = state.currentAudit.options[state.activeOptionIndex];
  if (!activeOpt || !activeOpt.export_data || activeOpt.export_data.length === 0) {
    showToast('No records to export', true);
    return;
  }

  const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(activeOpt.export_data, null, 2));
  const link = document.createElement("a");
  link.setAttribute("href", dataStr);
  link.setAttribute("download", `audit_${state.currentAudit.thread_id}_${activeOpt.option_name}.json`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

// Historical Archives
async function loadArchives() {
  const grid = document.getElementById('archives-grid');
  try {
    const res = await fetch('/api/history');
    const data = await res.json();
    if (!data.success) {
      grid.innerHTML = `<div class="empty-desc">Error loading archives: ${escapeHTML(data.error)}</div>`;
      return;
    }

    state.archives = data.proposals || [];
    renderArchivesGrid();
  } catch (err) {
    grid.innerHTML = `<div class="empty-desc">Failed to fetch archives: ${escapeHTML(err.message)}</div>`;
  }
}

function renderArchivesGrid() {
  const grid = document.getElementById('archives-grid');
  grid.innerHTML = '';

  const q = (document.getElementById('archives-search')?.value || '').toLowerCase();
  const filtered = state.archives.filter(p => {
    if (!q) return true;
    return p.title.toLowerCase().includes(q) || String(p.thread_id).includes(q);
  });

  if (filtered.length === 0) {
    grid.innerHTML = `<div class="table-empty-state"><div class="empty-title">No archived reports match your search</div></div>`;
    return;
  }

  filtered.forEach(proposal => {
    const card = document.createElement('div');
    card.className = 'archive-card';

    const jsonFiles = proposal.files.filter(f => f.type === 'json');

    card.innerHTML = `
      <div class="archive-card-header">
        <h3 class="archive-card-title">${escapeHTML(proposal.title)}</h3>
        <span class="archive-card-badge">${proposal.thread_id ? '#' + escapeHTML(proposal.thread_id) : 'Archive'}</span>
      </div>
      <div class="archive-files-list" style="display:flex; flex-direction:column; gap:6px;">
        ${jsonFiles.map((f, index) => `
          <div class="archive-file-row">
            <span><strong>${escapeHTML(f.option_name)}</strong> (${f.weight ? formatCKB(f.weight) : 'Report'})</span>
            <button class="btn-outline" style="padding:3px 9px; font-size:11.5px;" data-report-index="${index}">
              View Report
            </button>
          </div>
        `).join('')}
      </div>
    `;

    card.querySelectorAll('[data-report-index]').forEach(button => {
      const file = jsonFiles[Number(button.dataset.reportIndex)];
      button.addEventListener('click', () => loadArchiveFile(
        file.rel_path, proposal.thread_id, file.option_name, file.weight || 0));
    });
    grid.appendChild(card);
  });
}

function handleArchivesSearch() {
  renderArchivesGrid();
}

async function loadHistoricalProposal(proposal) {
  const jsonFile = proposal.files.find(f => f.type === 'json');
  if (jsonFile) {
    await loadArchiveFile(jsonFile.rel_path, proposal.thread_id, jsonFile.option_name, jsonFile.weight || 0);
  } else {
    showToast(`No records found for #${escapeHTML(proposal.thread_id)}`, true);
  }
}

async function loadArchiveFile(relPath, threadId, optionName, optionWeight) {
  showToast(`Loading report for #${threadId}...`);
  try {
    const res = await fetch(`/api/history/file?path=${encodeURIComponent(relPath)}`);
    const result = await res.json();
    if (!result.success) {
      showToast(result.error || 'Failed to read file', true);
      return;
    }

    state.currentAudit = {
      thread_id: threadId,
      timestamp: relPath.split('/').pop(),
      options: [
        {
          option_id: threadId,
          option_name: optionName || 'Poll Choice',
          option_weight: optionWeight || 0,
          export_data: result.data || []
        }
      ],
      isPreview: false
    };
    state.activeOptionIndex = 0;

    switchView('runner');
    renderAuditData();
  } catch (err) {
    showToast(`Error: ${escapeHTML(err.message)}`, true);
  }
}

// Docs Modal Controls
function openDocsModal() {
  document.getElementById('docs-modal')?.classList.remove('hidden');
}

function closeDocsModal(e) {
  if (!e || e.target.id === 'docs-modal' || e.target.classList.contains('modal-btn-close') || e.target.tagName === 'BUTTON') {
    document.getElementById('docs-modal')?.classList.add('hidden');
  }
}

// Initialization
document.addEventListener('DOMContentLoaded', () => {
  updateLocalization();
  loadArchives();

  const input = document.getElementById('metaforo-url-input');
  if (input) {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        handleInspectPoll();
      }
    });
  }
});
