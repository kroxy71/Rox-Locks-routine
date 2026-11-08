/* Sharp Sheet - app.js : UI only. All numbers come from model.js and the CSV files in /data. */
(function () {
  'use strict';
  const K = window.KCModel;
  const $ = (s, el) => (el || document).querySelector(s);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const S = { sp: 'nfl', tab: 'slate', M: {}, U: {}, meta: {}, lab: {}, parlay: [], players: { cat: {}, q: '', sort: {}, sel: null }, games: { team: '' } };
  const TABS = [['slate', 'Slate'], ['props', 'Bets'], ['lab', 'Bet Lab'], ['parlay', 'Parlay'], ['teams', 'Teams'], ['players', 'Players'], ['games', 'Games'], ['track', 'Model Bets'], ['acc', 'Accuracy']];
  const fmtET = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  const fmtDay = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'long', month: 'long', day: 'numeric' });
  const fmtShort = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric' });
  const fmtTime = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' });
  const dayKey = (iso) => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date(iso));
  const pc = (p, d) => K.pct(p, d);
  const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } } };

  /* ---------- loading ---------- */
  async function loadAll() {
    const tables = ['games', 'team_games', 'player_games', 'upcoming'];
    const jobs = [];
    for (const sp of ['nfl', 'nhl']) for (const t of tables) jobs.push(fetch('data/' + sp + '_' + t + '.csv').then((r) => { if (!r.ok) throw new Error(sp + ' ' + t + ' ' + r.status); return r.text(); }).then((x) => [sp, t, K.parseCSV(x)]));
    jobs.push(fetch('data/meta.json').then((r) => r.json()).then((m) => ['meta', 'meta', m]));
    const optCsv = (name) => fetch('data/' + name).then((r) => (r.ok ? r.text() : '')).then((x) => (x ? K.parseCSV(x) : [])).catch(() => []);
    jobs.push(optCsv('injuries.csv').then((rows) => ['inj', 'inj', rows]));
    jobs.push(optCsv('goalies.csv').then((rows) => ['gk', 'gk', rows]));
    jobs.push(optCsv('dk_props.csv').then((rows) => ['dk', 'dk', rows]));
    jobs.push(fetch('data/teams.csv').then((r) => (r.ok ? r.text() : '')).then((x) => ['teams', 'teams', x ? K.parseCSV(x) : []]).catch(() => ['teams', 'teams', []]));
    const out = await Promise.all(jobs); const raw = { nfl: {}, nhl: {} };
    S.colors = { nfl: {}, nhl: {} }; S.inj = { nfl: {}, nhl: {} }; let gkRows = [];
    out.forEach(([sp, t, rows]) => {
      if (sp === 'meta') S.meta = rows;
      else if (sp === 'inj') rows.forEach((r) => { if (S.inj[r.sport]) S.inj[r.sport][K.normName(r.name) + '|' + r.team] = r; });
      else if (sp === 'gk') gkRows = rows;
      else if (sp === 'dk') {
        // DraftKings props: one-sided "X or more" and anytime odds, plus each player's main over/under line
        S.dk = { nfl: { ms: {}, ladder: {}, ou: {} }, nhl: { ms: {}, ladder: {}, ou: {} } };
        rows.forEach((r) => {
          const D = S.dk[r.sport]; if (!D) return; const gid = String(r.game_id), aid = String(r.athlete_id);
          if (r.kind === 'ou') { if (r.line !== '') D.ou[gid + '|' + aid + '|' + r.key] = +r.line; return; }
          const ms = r.kind === 'any' ? 'any' : +r.line; const k = gid + '|' + aid + '|' + r.key + '|' + ms;
          if (r.odds !== '' && r.odds != null) { D.ms[k] = +String(r.odds).replace('+', ''); if (ms !== 'any') { const lk = gid + '|' + aid + '|' + r.key; (D.ladder[lk] = D.ladder[lk] || []).push(ms); } }
        });
      }
      else if (sp === 'teams') rows.forEach((r) => { if (S.colors[r.sport]) S.colors[r.sport][r.name] = r; });
      else raw[sp][t] = rows;
    });
    S.raw = raw;
    // upcoming slate: drop games from earlier days (Eastern) and any game that already has a final score
    const today = dayKey(new Date().toISOString());
    for (const sp of ['nfl', 'nhl']) {
      S.M[sp] = K.buildSport(sp, raw[sp].games, raw[sp].team_games, raw[sp].player_games);
      const done = new Set(raw[sp].games.map((g) => String(g.game_id)));
      S.U[sp] = raw[sp].upcoming.filter((g) => dayKey(g.date) >= today && !done.has(String(g.game_id)));
    }
    // attach announced NHL starting goalies to upcoming games
    S.U.nhl.forEach((g) => {
      const m = gkRows.find((r) => r.home === g.home && r.away === g.away && r.date === dayKey(g.date));
      if (m) { g.home_goalie = m.home_goalie; g.home_goalie_status = m.home_status; g.away_goalie = m.away_goalie; g.away_goalie_status = m.away_status; }
    });
  }

  /* ---------- small UI parts ---------- */
  const abbr = (M, t) => M.abbr[t] || t;
  /* injuries and goalies */
  function injOf(sp, p) { const r = S.inj && S.inj[sp] && S.inj[sp][K.normName(p.name) + '|' + p.team]; return r && !/^active$/i.test(r.status) ? r : null; }
  function isOut(sp, p) { const r = injOf(sp, p); return !!r && /^(out|injured reserve|suspension|physically unable|non-football)/i.test(r.status); }
  function injShort(st) { st = String(st || ''); if (/^out/i.test(st)) return 'OUT'; if (/injured reserve/i.test(st)) return 'IR'; if (/doubtful/i.test(st)) return 'D'; if (/questionable/i.test(st)) return 'Q'; if (/day-to-day/i.test(st)) return 'DTD'; if (/suspension/i.test(st)) return 'SUSP'; return st.slice(0, 4).toUpperCase(); }
  function injTag(sp, p) { const r = injOf(sp, p); if (!r) return ''; return ' <em class="inj ' + (isOut(sp, p) ? 'out' : 'q') + '" title="' + esc(r.status + ': ' + r.comment) + '">' + esc(injShort(r.status)) + '</em>'; }
  function starterFor(g, team) { // announced starting goalie for a team in an upcoming NHL game
    if (!g) return null;
    if (team === g.home && g.home_goalie) return { name: g.home_goalie, status: g.home_goalie_status || '' };
    if (team === g.away && g.away_goalie) return { name: g.away_goalie, status: g.away_goalie_status || '' };
    return null;
  }
  function dkOdds(sp, gid, pid, key, ms) { const D = S.dk && S.dk[sp]; if (!D) return null; const v = D.ms[String(gid) + '|' + String(pid) + '|' + key + '|' + (ms == null ? 'any' : ms)]; return v == null || isNaN(v) ? null : v; }
  function dkLine(sp, gid, pid, key) { const D = S.dk && S.dk[sp]; if (!D) return null; const v = D.ou[String(gid) + '|' + String(pid) + '|' + key]; return v == null ? null : v; }
  function dkLadder(sp, gid, pid, key) { const D = S.dk && S.dk[sp]; return (D && D.ladder[String(gid) + '|' + String(pid) + '|' + key]) || []; }
  function goalieLine(g) {
    if (!g || !(g.home_goalie || g.away_goalie)) return '';
    const one = (n, s) => n ? '<b>' + esc(n) + '</b> <em class="inj ' + (/confirm/i.test(s) ? 'st' : 'q') + '">' + esc(/confirm/i.test(s) ? 'Confirmed' : (s || 'Projected')) + '</em>' : 'TBD';
    return '<div class="g-goalies"><span class="k">Goalies</span>' + one(g.away_goalie, g.away_goalie_status) + '<i>vs</i>' + one(g.home_goalie, g.home_goalie_status) + '</div>';
  }
  function goalieExcluded(g, p) { const s = starterFor(g, p.team); return !!s && K.normName(s.name) !== K.normName(p.name); }
  function hexOk(h) { return /^[0-9a-f]{6}$/i.test(String(h || '')); }
  function lum(h) { const n = parseInt(h, 16); const c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; }
  function badge(M, team, sm) { // team-colour abbreviation badge (no logos)
    const c = (S.colors && S.colors[M.sp] && S.colors[M.sp][team]) || null;
    let style = '';
    const col = c ? String(c.color || '') : '', al = c ? String(c.alt || '') : '';
    if (hexOk(col)) {
      const alt = hexOk(al) && al.toLowerCase() !== col.toLowerCase() ? al : (lum(col) > 0.4 ? '0b1220' : 'ffffff');
      style = ' style="--tc:#' + col + ';--tt:' + (lum(col) > 0.45 ? '#0b1220' : '#ffffff') + ';--ta:#' + alt + '"';
    }
    return '<span class="mono' + (sm ? ' sm' : '') + '"' + style + '>' + esc(abbr(M, team)) + '</span>';
  }
  function probBar(M, gm) {
    const h = gm.homeWin, a = gm.awayWin;
    return '<div class="pbar" role="img" aria-label="Win probability: ' + esc(gm.away) + ' ' + pc(a) + ', ' + esc(gm.home) + ' ' + pc(h) + '">' +
      '<span class="seg away" style="width:' + (a * 100).toFixed(1) + '%"><b>' + esc(abbr(M, gm.away)) + ' ' + pc(a) + '</b></span>' +
      '<span class="seg home" style="width:' + (h * 100).toFixed(1) + '%"><b>' + pc(h) + ' ' + esc(abbr(M, gm.home)) + '</b></span></div>';
  }
  function fairOdds(p) {
    if (p < 0.02) return 'longer than +4900'; if (p > 0.98) return 'shorter than -4900';
    const a = K.probToAm(p); return a == null ? '-' : (a > 0 ? '+' + a : String(a));
  }
  function topScorers(M, gm) {
    const key = M.sp === 'nfl' ? 'atd' : 'atg';
    const list = [];
    for (const p of Object.values(M.players)) {
      if (p.team !== gm.home && p.team !== gm.away) continue;
      if (M.sp === 'nhl' && p.pos === 'G') continue;
      if (isOut(M.sp, p)) continue;
      const rows = K.eligibleRows(M.sp, p); if (rows.length < 2) continue;
      if (M.sp === 'nfl' && !rows.some((r) => (r.rush_att || 0) + (r.targets || 0) > 0)) continue;
      const r = K.propProb(M, p, key, 'over', 0.5, gm); list.push({ p, pr: r.p });
    }
    list.sort((a, b) => b.pr - a.pr);
    return list.slice(0, 4);
  }

  /* ---------- Slate ---------- */
  function lean(gm) { // model on its own vs the market, in win-probability points
    if (gm.mktHomeWin == null) return null;
    const d = gm.modelHomeWin - gm.mktHomeWin;
    return { team: d > 0 ? gm.home : gm.away, pts: Math.abs(d) * 100 };
  }
  function lineTags(M, g, gm) {
    const t = []; const f = (v) => (v > 0 ? '+' : '') + v;
    if (M.sp === 'nfl') { if (g.spread_detail) t.push(g.spread_detail); }
    else if (g.home_ml !== '' && g.away_ml !== '') { t.push(abbr(M, gm.away) + ' ' + f(g.away_ml)); t.push(abbr(M, gm.home) + ' ' + f(g.home_ml)); }
    if (g.over_under !== '') t.push('O/U ' + g.over_under);
    if (!t.length) t.push('No line yet');
    return t.map((x) => '<span class="tag">' + esc(x) + '</span>').join('');
  }
  function teamRow(M, team, p, fav) {
    return '<div class="trow' + (fav ? ' fav' : '') + '">' + badge(M, team) + '<span class="tn">' + esc(team) + '</span><span class="tp">' + pc(p) + '</span></div>';
  }
  function renderSlate() {
    const M = S.M[S.sp]; const up = S.U[S.sp].slice().sort((a, b) => (a.date < b.date ? -1 : 1));
    const models = up.slice(0, S.sp === 'nfl' ? 16 : 40).map((g) => { const gm = K.gameModel(M, g); return { g, gm, ln: lean(gm) }; });
    let h = '<div class="hero"><h2>' + (S.sp === 'nfl' ? 'The NFL board' : 'The NHL board') + '<span>Win chances, projections and likely scorers</span></h2><div class="pills"><span class="pillc"><i class="dot" aria-hidden="true"></i><b>' + models.length + '</b> games on the board</span><span class="pillc">Model and market, blended</span></div></div>' +
      '<p class="lede">Tap a game to test a bet in the Bet Lab, or tap any button or player to add it to your parlay.</p>';
    if (!models.length) return h + '<p class="empty">No upcoming games are on the schedule right now.</p>';
    const edges = models.filter((x) => x.ln && x.ln.pts >= 4).sort((a, b) => b.ln.pts - a.ln.pts).slice(0, 3);
    if (edges.length) {
      h += '<div class="sec-h"><span class="redpill">Model vs market</span><h2>Where the model disagrees</h2><span class="sub">The market is usually sharper, so treat these as leads to research, not picks.</span></div><div class="edges">' + edges.map(({ g, gm, ln }) => {
        const mk = ln.team === gm.home ? gm.mktHomeWin : 1 - gm.mktHomeWin; const md = ln.team === gm.home ? gm.modelHomeWin : 1 - gm.modelHomeWin;
        return '<article class="card edge" data-game="' + esc(g.game_id) + '" tabindex="0" role="button" aria-label="Open ' + esc(g.away) + ' at ' + esc(g.home) + ' in Bet Lab"><span class="e-m">' + esc(abbr(M, gm.away)) + ' at ' + esc(abbr(M, gm.home)) + ' &middot; ' + esc(fmtET.format(new Date(g.date))) + ' ET</span><span class="e-t">Model leans ' + esc(ln.team) + '</span><span class="e-n">The model alone gives them <b>' + pc(md) + '</b> to win, against ' + pc(mk) + ' in the market: a ' + ln.pts.toFixed(1) + '-point gap.</span></article>';
      }).join('') + '</div>';
    }
    const days = {}; models.forEach((x) => { (days[dayKey(x.g.date)] = days[dayKey(x.g.date)] || []).push(x); });
    for (const d of Object.keys(days)) {
      h += '<h2 class="day">' + esc(fmtDay.format(new Date(days[d][0].g.date))) + '</h2><div class="cards">';
      for (const { g, gm, ln } of days[d]) {
        const sc = topScorers(M, gm); const favHome = gm.homeWin >= 0.5;
        const proj = M.sp === 'nfl' ? (esc(abbr(M, gm.away)) + ' ' + gm.asB.toFixed(1) + ' &ndash; ' + esc(abbr(M, gm.home)) + ' ' + gm.hsB.toFixed(1)) : (esc(abbr(M, gm.away)) + ' ' + gm.la.toFixed(2) + ' &ndash; ' + esc(abbr(M, gm.home)) + ' ' + gm.lh.toFixed(2));
        const val = ln && ln.pts >= 4 ? '<div class="value">Model leans ' + esc(ln.team) + ' by ' + ln.pts.toFixed(1) + ' points vs the market</div>' : '';
        h += '<article class="card game" data-game="' + esc(g.game_id) + '" tabindex="0" role="button" aria-label="Open ' + esc(g.away) + ' at ' + esc(g.home) + ' in Bet Lab">' +
          '<div class="g-top"><span class="g-time">' + esc(fmtTime.format(new Date(g.date))) + ' ET</span><span class="g-lines">' + lineTags(M, g, gm) + '</span></div>' +
          teamRow(M, gm.away, gm.awayWin, !favHome) + teamRow(M, gm.home, gm.homeWin, favHome) + goalieLine(g) +
          '<div class="split' + (favHome ? '' : ' away-fav') + '" aria-hidden="true"><span class="a" style="width:' + (gm.awayWin * 100).toFixed(1) + '%"></span><span class="h" style="width:' + (gm.homeWin * 100).toFixed(1) + '%"></span></div>' +
          '<div class="g-proj"><span>Projected <b>' + proj + '</b></span><span>Total <b>' + gm.total.toFixed(1) + '</b></span></div>' + val +
          '<div class="g-sc"><span class="k">' + (M.sp === 'nfl' ? 'Most likely touchdown scorers' : 'Most likely goal scorers') + ' &middot; tap to add</span>' + sc.map((s) => '<button type="button" class="chip addchip" data-add="prop" data-sp="' + M.sp + '" data-game="' + esc(g.game_id) + '" data-pid="' + esc(s.p.id) + '" data-key="' + (M.sp === 'nfl' ? 'atd' : 'atg') + '" aria-label="Add ' + esc(s.p.name) + ' to parlay">' + esc(s.p.name) + ' <b>' + pc(s.pr) + '</b><i aria-hidden="true">+</i></button>').join('') + '</div>' +
          '<div class="g-add"><span class="k">Add to parlay</span>' +
          addBtn('data-add="win" data-sp="' + M.sp + '" data-game="' + esc(g.game_id) + '" data-team="' + esc(gm.away) + '"', esc(abbr(M, gm.away)) + ' win ' + pc(gm.awayWin)) +
          addBtn('data-add="win" data-sp="' + M.sp + '" data-game="' + esc(g.game_id) + '" data-team="' + esc(gm.home) + '"', esc(abbr(M, gm.home)) + ' win ' + pc(gm.homeWin)) +
          (g.over_under !== '' ? addBtn('data-add="total" data-sp="' + M.sp + '" data-game="' + esc(g.game_id) + '" data-side="over" data-line="' + esc(g.over_under) + '"', 'Over ' + esc(g.over_under)) + addBtn('data-add="total" data-sp="' + M.sp + '" data-game="' + esc(g.game_id) + '" data-side="under" data-line="' + esc(g.over_under) + '"', 'Under ' + esc(g.over_under)) : '') +
          '</div></article>';
      }
      h += '</div>';
    }
    return h;
  }

  /* ---------- Bet Lab ---------- */
  function labDefaults() {
    const M = S.M[S.sp]; const up = S.U[S.sp].slice().sort((a, b) => (a.date < b.date ? -1 : 1));
    const g = up[0];
    return { gameId: g ? g.game_id : 'custom', home: g ? g.home : M.teams[0].name, away: g ? g.away : M.teams[1].name, btype: 'win', team: g ? g.home : '', line: '', side: 'over', odds: '', ptype: M.sp === 'nfl' ? 'atd' : 'atg', pteam: '', pid: '', pside: 'over', pline: 0.5, podds: '' };
  }
  function usage(sp, p) { // how involved a player is: used to put the busiest players first
    const rows = K.eligibleRows(sp, p);
    return rows.reduce((s, r) => s + (sp === 'nfl' ? (r.rush_att || 0) + (r.targets || 0) + (r.pass_att || 0) * 0.5 : (r.shots || 0) + (r.saves || 0) * 0.2), 0);
  }
  function labGame() { // build game object for the model
    const L = S.lab[S.sp], M = S.M[S.sp];
    const up = S.U[S.sp].find((g) => g.game_id === L.gameId);
    if (up) return Object.assign({}, up);
    return { home: L.home, away: L.away, spread_detail: '', over_under: '', home_ml: '', away_ml: '' };
  }
  function opt(v, label, sel) { return '<option value="' + esc(v) + '"' + (sel ? ' selected' : '') + '>' + esc(label) + '</option>'; }
  function renderLab() {
    const sp = S.sp, M = S.M[sp]; if (!S.lab[sp]) S.lab[sp] = labDefaults(); const L = S.lab[sp];
    const up = S.U[sp].slice().sort((a, b) => (a.date < b.date ? -1 : 1));
    const g = labGame(); L.home = g.home; L.away = g.away;
    if (L.team !== L.home && L.team !== L.away) L.team = L.home;
    if (L.pteam !== L.home && L.pteam !== L.away) L.pteam = L.home;
    const gm = K.gameModel(M, g);
    let h = '<div class="lab">';
    h += '<section class="card"><h2><span class="step">1</span>Pick the game</h2><label class="f">Game<select id="lab-game">' + up.map((u) => opt(u.game_id, u.away + ' at ' + u.home + ' - ' + fmtShort.format(new Date(u.date)), u.game_id === L.gameId)).join('') + opt('custom', 'Any matchup (choose teams)', L.gameId === 'custom') + '</select></label>';
    if (L.gameId === 'custom') {
      const names = M.teams.map((t) => t.name).sort();
      h += '<div class="row2"><label class="f">Away<select id="lab-away">' + names.map((n) => opt(n, n, n === L.away)).join('') + '</select></label><label class="f">Home<select id="lab-home">' + names.map((n) => opt(n, n, n === L.home)).join('') + '</select></label></div>';
    }
    h += '<div class="lab-game">' + probBar(M, gm) + '<ul class="why">' + K.gameReasoning(M, gm).map((x) => '<li>' + esc(x) + '</li>').join('') + '</ul></div></section>';

    h += '<section class="card"><h2><span class="step">2</span>Game bet</h2><div class="row3"><label class="f">Bet<select id="lab-btype">' + opt('win', 'Team to win', L.btype === 'win') + opt('spread', sp === 'nfl' ? 'Point spread' : 'Puck line', L.btype === 'spread') + opt('total', 'Total goals/points', L.btype === 'total') + '</select></label>';
    if (L.btype !== 'total') h += '<label class="f">Team<select id="lab-team">' + [L.home, L.away].map((t) => opt(t, t, t === L.team)).join('') + '</select></label>'; else h += '<label class="f">Side<select id="lab-side">' + opt('over', 'Over', L.side === 'over') + opt('under', 'Under', L.side === 'under') + '</select></label>';
    if (L.btype !== 'win') h += '<label class="f">Line<input id="lab-line" type="number" step="0.5" inputmode="decimal" value="' + esc(L.line) + '" placeholder="' + (L.btype === 'total' ? 'e.g. 45.5' : 'e.g. -3.5') + '"></label>';
    h += '<label class="f">Your odds (optional)<input id="lab-odds" type="number" step="1" inputmode="numeric" value="' + esc(L.odds) + '" placeholder="e.g. -110"></label></div><div id="lab-res"></div></section>';

    // player props
    const players = Object.values(M.players).filter((p) => p.team === L.pteam && (sp === 'nhl' || K.eligibleRows(sp, p).length)).sort((a, b) => (usage(sp, b) - usage(sp, a)) || (a.name < b.name ? -1 : 1));
    const pk = Object.keys(K.PROPS[sp]);
    if (!pk.includes(L.ptype)) L.ptype = pk[0];
    const relevant = players.filter((p) => { const k = L.ptype; if (sp === 'nhl') return k === 'saves' ? p.pos === 'G' : p.pos !== 'G'; const r = K.eligibleRows(sp, p); if (k === 'pass_yds' || k === 'pass_td') return r.some((x) => x.pass_att > 0); if (k === 'rec_yds' || k === 'rec') return r.some((x) => x.targets > 0); if (k === 'rush_yds') return r.some((x) => x.rush_att > 0); return true; });
    if (!relevant.find((p) => p.id === L.pid)) L.pid = relevant[0] ? relevant[0].id : '';
    const def = K.PROPS[sp][L.ptype];
    h += '<section class="card"><h2><span class="step">3</span>Player prop</h2><div class="row3"><label class="f">Team<select id="lab-pteam">' + [L.home, L.away].map((t) => opt(t, t, t === L.pteam)).join('') + '</select></label>' +
      '<label class="f">Prop<select id="lab-ptype">' + pk.map((k) => opt(k, K.PROPS[sp][k].short || K.PROPS[sp][k].label, k === L.ptype)).join('') + '</select></label>' +
      '<label class="f">Player<select id="lab-pid">' + relevant.map((p) => { const ij = injOf(sp, p); const ex = L.ptype === 'saves' && goalieExcluded(g, p); return opt(p.id, p.name + (p.pos ? ' (' + p.pos + ')' : '') + (ij ? ' - ' + injShort(ij.status) : '') + (ex ? ' - not starting' : ''), p.id === L.pid); }).join('') + '</select></label>';
    if (!def.anytime) h += '<label class="f">Side<select id="lab-pside">' + opt('over', 'Over', L.pside === 'over') + opt('under', 'Under', L.pside === 'under') + '</select></label><label class="f">Line<input id="lab-pline" type="number" step="0.5" inputmode="decimal" value="' + esc(L.pline) + '"></label>';
    h += '<label class="f">Your odds (optional)<input id="lab-podds" type="number" step="1" inputmode="numeric" value="' + esc(L.podds) + '" placeholder="e.g. +150"></label></div><div id="lab-pres"></div></section></div>';
    return h;
  }

  function evText(p, push, odds) {
    const imp = K.amToProb(odds); if (!imp) return '';
    const o = +odds; const win = o > 0 ? o : 10000 / -o; const ev = p * win - (1 - p - (push || 0)) * 100;
    const edge = p - imp;
    return '<div class="ev ' + (edge >= 0 ? 'pos' : 'neg') + '">Your odds ' + (o > 0 ? '+' : '') + o + ' imply ' + pc(imp, 1) + '. The estimate is ' + (edge >= 0 ? 'above' : 'below') + ' that by ' + Math.abs(edge * 100).toFixed(1) + ' points, about ' + (ev >= 0 ? '+' : '-') + '$' + Math.abs(ev).toFixed(0) + ' per $100 if the estimate is right.</div>';
  }
  function resultCard(title, r, odds, why, note) {
    if (r.p == null || isNaN(r.p)) return '<p class="empty">Enter a line to see the probability.</p>';
    const imp = K.amToProb(odds); const e = imp ? r.p - imp : null;
    const verdict = e == null ? '' : (e >= 0.02 ? '<span class="verdict pos">Value</span>' : e <= -0.02 ? '<span class="verdict neg">Overpriced</span>' : '<span class="verdict mid">Fair price</span>');
    return '<div class="res"><div class="res-h"><div class="big">' + pc(r.p, 1) + '</div><div class="res-t"><b>' + esc(title) + '</b><span>Fair odds ' + fairOdds(r.p) + (r.push > 0.001 ? ' &middot; push chance ' + pc(r.push, 1) : '') + '</span></div>' + verdict + '</div>' +
      '<div class="meter"><span style="width:' + (r.p * 100).toFixed(1) + '%"></span></div>' + evText(r.p, r.push, odds) +
      '<ul class="why">' + why.map((x) => '<li>' + esc(x) + '</li>').join('') + '</ul>' + (note ? '<p class="note">' + esc(note) + '</p>' : '') + '</div>';
  }
  function logBars(M, p, key) {
    const rows = K.eligibleRows(M.sp, p).slice(0, 10).reverse(); if (!rows.length) return '';
    const vals = rows.map((r) => K.statVal(M.sp, key, r)); const mx = Math.max(1, ...vals);
    return '<div class="log" aria-label="Last games">' + rows.map((r, i) => '<div class="lb"><span class="bar" style="height:' + Math.max(3, vals[i] / mx * 44).toFixed(0) + 'px"></span><b>' + (Number.isInteger(vals[i]) ? vals[i] : vals[i].toFixed(1)) + '</b><i>' + esc(fmtShort.format(new Date(r.date))) + '</i></div>').join('') + '</div>';
  }
  function updateLabResults() {
    const sp = S.sp, M = S.M[sp], L = S.lab[sp]; if (!L) return; const g = labGame(); const gm = K.gameModel(M, g);
    const box = $('#lab-res'), pbox = $('#lab-pres');
    if (box) {
      let r, title, why = [], note = '';
      if (L.btype === 'win') {
        r = K.betProb(M, gm, { type: 'win', team: L.team }); title = L.team + ' to win';
        why = [L.team + ' win chance ' + pc(r.p, 1) + ' after blending the model with the betting market (when a line exists). The breakdown is in step 1.'];
      } else if (L.btype === 'spread') {
        const line = parseFloat(L.line); if (isNaN(line)) r = { p: null }; else {
          r = K.betProb(M, gm, { type: 'spread', team: L.team, line }); title = L.team + ' ' + (line > 0 ? '+' : '') + line;
          const m = L.team === gm.home ? gm.margin : -gm.margin;
          why = sp === 'nfl' ? ['Projected margin for ' + L.team + ': ' + (m >= 0 ? '+' : '') + m.toFixed(1) + ' points, with game-to-game spread of about ' + gm.sdMargin.toFixed(1) + '. To cover ' + (line > 0 ? '+' : '') + line + ' they need to finish ' + (-line >= 0 ? 'ahead by more than ' + (-line) : 'no worse than ' + (-line)) + '.'] :
            ['Hockey margins are small. The puck line uses the full goal distribution for both teams, with overtime and shootout decided by one goal.'];
        }
      } else {
        const line = parseFloat(L.line); if (isNaN(line)) r = { p: null }; else {
          r = K.betProb(M, gm, { type: 'total', side: L.side, line }); title = (L.side === 'over' ? 'Over ' : 'Under ') + line;
          why = ['Projected total ' + gm.total.toFixed(1) + (gm.mktTotal != null ? ' (market ' + gm.mktTotal + ')' : '') + (sp === 'nfl' ? ' with spread of about ' + gm.sdTotal.toFixed(1) + ' points.' : ', built from each team\'s expected goals.')];
        }
      }
      note = 'Built from this season\'s results, blended with the betting market' + (sp === 'nhl' ? ' and adjusted for announced starting goalies' : '') + '. Weather and late lineup news are not in the model.';
      box.innerHTML = resultCard(title || '', r, L.odds, why, note) + (r && r.p != null && !isNaN(r.p) ? addBtn('data-add="lab"', '+ Add this bet to your parlay', 'wide') : '');
    }
    if (pbox) {
      const p = M.players[L.pid];
      if (!p) pbox.innerHTML = '<p class="empty">No players found for that selection.</p>'; else {
        const def = K.PROPS[sp][L.ptype]; const line = def.anytime ? 0.5 : parseFloat(L.pline);
        if (isNaN(line)) pbox.innerHTML = '<p class="empty">Enter a line.</p>'; else {
          const r = K.propProb(M, p, L.ptype, L.pside, line, gm);
          const title = def.anytime ? p.name + ' ' + def.label.toLowerCase() : p.name + ' ' + (L.pside === 'over' ? 'over ' : 'under ') + line + ' ' + def.label.toLowerCase();
          const ij = injOf(sp, p); const why = r.why.slice();
          if (ij) why.unshift('Injury report: ' + ij.status + '. ' + ij.comment);
          if (L.ptype === 'saves') { const s = starterFor(g, p.team); if (s) why.unshift(K.normName(s.name) === K.normName(p.name) ? p.name + ' is the ' + (s.status || 'projected').toLowerCase() + ' starter.' : s.name + ' (' + (s.status || 'projected').toLowerCase() + ') is starting, not ' + p.name + ', so this prop would not apply.'); }
          pbox.innerHTML = resultCard(title, r, L.podds, why, r.low ? 'Small sample: ' + r.n + ' game' + (r.n === 1 ? '' : 's') + ' played. Treat this as rough.' : 'Role changes and late lineup news are not in the model.') + addBtn('data-add="labprop"', '+ Add this prop to your parlay', 'wide') + logBars(M, p, L.ptype);
        }
      }
    }
  }

  /* ---------- Parlay builder ---------- */
  const amToDec = (o) => { o = +o; if (!o) return null; return o > 0 ? 1 + o / 100 : 1 + 100 / -o; };
  const decToAm = (d) => (d >= 2 ? Math.round((d - 1) * 100) : Math.round(-100 / (d - 1)));
  const fmtAm = (a) => (a > 0 ? '+' + a : String(a));
  function saveParlay() { store.set('ss-parlay', JSON.stringify(S.parlay)); }
  function loadParlay() { try { const x = JSON.parse(store.get('ss-parlay') || '[]'); S.parlay = Array.isArray(x) ? x.filter((l) => l && typeof l.p === 'number') : []; } catch (e) { S.parlay = []; } }
  function findGame(sp, gameId, home, away) {
    const g = S.U[sp].find((x) => x.game_id === gameId);
    return g ? Object.assign({}, g) : { game_id: gameId, home, away, spread_detail: '', over_under: '', home_ml: '', away_ml: '', date: '' };
  }
  function makeLeg(spec) {
    const sp = spec.sp, M = S.M[sp]; const g = findGame(sp, spec.gameId, spec.home, spec.away); const gm = K.gameModel(M, g);
    const leg = { sp, gameId: spec.gameId, matchup: abbr(M, g.away) + ' @ ' + abbr(M, g.home), date: g.date || '', odds: spec.odds || '' };
    const sgn = (v) => (v > 0 ? '+' : '') + v;
    if (spec.kind === 'win') {
      leg.p = K.betProb(M, gm, { type: 'win', team: spec.team }).p; leg.label = spec.team + ' to win';
      if (!leg.odds) { const ml = spec.team === g.home ? g.home_ml : g.away_ml; if (ml !== '' && ml != null) leg.odds = String(ml); }
      leg.id = sp + '|' + spec.gameId + '|win|' + spec.team;
    } else if (spec.kind === 'spread') {
      leg.p = K.betProb(M, gm, { type: 'spread', team: spec.team, line: spec.line }).p; leg.label = spec.team + ' ' + sgn(spec.line);
      leg.id = sp + '|' + spec.gameId + '|spread|' + spec.team + '|' + spec.line; if (!leg.odds) leg.odds = '-110';
    } else if (spec.kind === 'total') {
      leg.p = K.betProb(M, gm, { type: 'total', side: spec.side, line: spec.line }).p; leg.label = (spec.side === 'over' ? 'Over ' : 'Under ') + spec.line + ' total ' + (sp === 'nfl' ? 'points' : 'goals');
      leg.id = sp + '|' + spec.gameId + '|total|' + spec.side + '|' + spec.line; if (!leg.odds) leg.odds = '-110';
    } else {
      const p = M.players[spec.pid]; if (!p) return null; const def = K.PROPS[sp][spec.key];
      const line = def.anytime ? 0.5 : spec.line; const r = K.propProb(M, p, spec.key, spec.side || 'over', line, gm);
      leg.p = r.p; leg.label = def.anytime ? p.name + ' ' + def.label.toLowerCase() : (spec.ms != null ? p.name + ' ' + spec.ms + '+ ' + def.label.toLowerCase() : p.name + ' ' + (spec.side === 'under' ? 'under ' : 'over ') + line + ' ' + def.label.toLowerCase());
      leg.id = sp + '|' + spec.gameId + '|prop|' + spec.pid + '|' + spec.key + '|' + (spec.side || 'over') + '|' + line;
    }
    if (leg.p == null || isNaN(leg.p)) return null;
    return leg;
  }
  function addLeg(spec) {
    const leg = makeLeg(spec); if (!leg) return false;
    if (S.parlay.some((l) => l.id === leg.id)) { flash('That leg is already in your parlay.'); return false; }
    if (S.parlay.length >= 12) { flash('A parlay can hold up to 12 legs here.'); return false; }
    S.parlay.push(leg); saveParlay(); flash('Added: ' + leg.label); return true;
  }
  function parlayMath(legs) {
    const p = legs.reduce((s, l) => s * l.p, 1);
    const withOdds = legs.filter((l) => amToDec(l.odds));
    const dec = withOdds.length === legs.length && legs.length ? withOdds.reduce((s, l) => s * amToDec(l.odds), 1) : null;
    const games = {}; legs.forEach((l) => { games[l.gameId] = (games[l.gameId] || 0) + 1; });
    const sameGame = Object.values(games).some((n) => n > 1);
    return { p, dec, sameGame };
  }
  function flash(msg) {
    const el = $('#toast'); if (!el) return; el.textContent = msg; el.hidden = false; el.classList.remove('show'); void el.offsetWidth; el.classList.add('show');
    clearTimeout(flash.t); flash.t = setTimeout(() => { el.hidden = true; }, 2200);
  }
  function renderSlip() {
    const el = $('#slip'); if (!el) return;
    const n = S.parlay.length; el.hidden = !n || S.tab === 'parlay'; document.body.classList.toggle('has-slip', !el.hidden);
    if (!n) return;
    const m = parlayMath(S.parlay);
    el.innerHTML = '<div class="wrap slip-in"><div class="slip-t"><b>' + n + '-leg parlay</b><span>Chance ' + pc(m.p, 1) + ' &middot; fair odds ' + fairOdds(m.p) + '</span></div><button type="button" class="btn" data-tab="parlay">View parlay</button></div>';
  }
  function addBtn(attrs, label, cls) { return '<button type="button" class="add ' + (cls || '') + '" ' + attrs + '>' + label + '</button>'; }
  function legSuggestions() {
    const out = []; const sp = S.sp, M = S.M[sp];
    const up = S.U[sp].slice().sort((a, b) => (a.date < b.date ? -1 : 1)).slice(0, sp === 'nfl' ? 16 : 30);
    const wins = up.map((g) => { const gm = K.gameModel(M, g); const home = gm.homeWin >= 0.5; return { g, team: home ? g.home : g.away, p: home ? gm.homeWin : gm.awayWin }; }).sort((a, b) => b.p - a.p).slice(0, 6);
    const key = sp === 'nfl' ? 'atd' : 'atg'; const sc = [];
    up.forEach((g) => { const gm = K.gameModel(M, g); topScorers(M, gm).slice(0, 2).forEach((s) => sc.push({ g, p: s.p, pr: s.pr })); });
    sc.sort((a, b) => b.pr - a.pr);
    const seen = new Set(); const uniq = sc.filter((s) => (seen.has(s.p.id) ? false : (seen.add(s.p.id), true)));
    return { wins, scorers: uniq.slice(0, 6), key };
  }
  function renderParlay() {
    const legs = S.parlay; let h = '<div class="lab">';
    h += '<section class="card"><div class="pl-head"><h2>Your parlay</h2>' + (legs.length ? '<button type="button" class="btn ghost" id="pl-clear">Clear all</button>' : '') + '</div>';
    if (!legs.length) h += '<p class="empty">No legs yet. Add them from the game cards on the Slate, from Bet Lab results, or from the suggestions here.</p>';
    else {
      h += '<ol class="legs">' + legs.map((l, i) => '<li class="leg"><span class="sport-tag">' + l.sp.toUpperCase() + '</span><div class="leg-m"><b>' + esc(l.label) + '</b><span>' + esc(l.matchup) + (l.date ? ' &middot; ' + esc(fmtET.format(new Date(l.date))) + ' ET' : '') + '</span></div><div class="leg-p">' + pc(l.p) + '<span>fair ' + fairOdds(l.p) + '</span></div><label class="leg-o"><span>Odds</span><input type="number" inputmode="numeric" step="1" data-leg-odds="' + i + '" value="' + esc(l.odds) + '" placeholder="-110" aria-label="Odds for ' + esc(l.label) + '"></label><button type="button" class="rm" data-rm="' + i + '" aria-label="Remove ' + esc(l.label) + '">&times;</button></li>').join('') + '</ol>';
    }
    h += '</section>';
    h += '<section class="card"><h2>Combined chance</h2><div id="pl-sum"></div></section>';
    const sg = legSuggestions();
    const nm = S.sp === 'nfl' ? 'NFL' : 'NHL';
    h += '<section class="card"><h2>Suggested legs (' + nm + ')</h2><p class="note" style="margin-top:0">The model\'s most likely outcomes on the upcoming slate. Even strong legs compound: three 70% legs all hit only about 34% of the time.</p>' +
      '<h3 class="mini">Most likely winners</h3><ul class="sugg">' + sg.wins.map((w) => '<li><div><b>' + esc(w.team) + ' to win</b><span>' + esc(abbr(S.M[S.sp], w.g.away)) + ' @ ' + esc(abbr(S.M[S.sp], w.g.home)) + ' &middot; ' + esc(fmtET.format(new Date(w.g.date))) + '</span></div><em>' + pc(w.p) + '</em>' + addBtn('data-add="win" data-sp="' + S.sp + '" data-game="' + esc(w.g.game_id) + '" data-team="' + esc(w.team) + '"', '+ Add') + '</li>').join('') + '</ul>' +
      '<h3 class="mini">' + (S.sp === 'nfl' ? 'Most likely touchdown scorers' : 'Most likely goal scorers') + '</h3><ul class="sugg">' + sg.scorers.map((s) => '<li><div><b>' + esc(s.p.name) + '</b><span>' + esc(abbr(S.M[S.sp], s.p.team)) + ' &middot; ' + esc(abbr(S.M[S.sp], s.g.away)) + ' @ ' + esc(abbr(S.M[S.sp], s.g.home)) + '</span></div><em>' + pc(s.pr) + '</em>' + addBtn('data-add="prop" data-sp="' + S.sp + '" data-game="' + esc(s.g.game_id) + '" data-pid="' + esc(s.p.id) + '" data-key="' + sg.key + '"', '+ Add') + '</li>').join('') + '</ul></section>';
    return h + '</div>';
  }
  function updateParlaySummary() {
    const box = $('#pl-sum'); renderSlip(); if (!box) return;
    const legs = S.parlay; if (!legs.length) { box.innerHTML = '<p class="empty">Add at least one leg.</p>'; return; }
    const m = parlayMath(legs);
    const why = ['Combined chance = ' + legs.map((l) => pc(l.p)).join(' &times; ') + ' = ' + pc(m.p, 1) + '. This assumes the legs don\'t affect each other.'];
    let extra = '';
    if (m.dec) {
      const book = decToAm(m.dec); const imp = 1 / m.dec; const e = m.p - imp; const payout = 10 * m.dec;
      const verdict = e >= 0.02 ? '<span class="verdict pos">Value</span>' : e <= -0.02 ? '<span class="verdict neg">Overpriced</span>' : '<span class="verdict mid">Fair price</span>';
      extra = '<div class="pl-book"><div><span class="k">Parlay odds from your legs</span><b>' + fmtAm(book) + '</b></div><div><span class="k">Implied chance</span><b>' + pc(imp, 1) + '</b></div><div><span class="k">$10 pays</span><b>$' + payout.toFixed(2) + '</b></div>' + verdict + '</div>';
      why.push('Your legs\' odds multiply to ' + fmtAm(book) + ' (decimal ' + m.dec.toFixed(2) + '), which implies ' + pc(imp, 1) + '. The estimate is ' + (e >= 0 ? 'above' : 'below') + ' that by ' + Math.abs(e * 100).toFixed(1) + ' points.');
    } else why.push('Enter odds for every leg to see the parlay price, payout and whether it looks like value.');
    if (m.sameGame) why.push('Some legs come from the same game. Those outcomes are related (for example a team winning and its running back scoring), so the true combined chance can differ from this estimate.');
    box.innerHTML = '<div class="res" style="border:0;padding-top:0;margin-top:0"><div class="res-h"><div class="big">' + pc(m.p, 1) + '</div><div class="res-t"><b>' + legs.length + '-leg parlay hits</b><span>Fair odds ' + fairOdds(m.p) + '</span></div></div><div class="meter"><span style="width:' + Math.max(0.5, m.p * 100).toFixed(1) + '%"></span></div>' + extra + '<ul class="why">' + why.map((x) => '<li>' + x + '</li>').join('') + '</ul></div>';
  }

  /* ---------- Props board: every milestone prop on the upcoming slate ---------- */
  const MILESTONES = {
    nfl: [['atd', 'Anytime TD', [null]], ['rec_yds', 'Receiving yds', [25, 40, 60, 80, 100]], ['rec', 'Receptions', [3, 5, 7]], ['rush_yds', 'Rushing yds', [40, 60, 80, 100]], ['pass_yds', 'Passing yds', [200, 250, 300]], ['pass_td', 'Passing TDs', [2, 3]], ['rushrec_yds', 'Rush + rec yds', [50, 75, 100]]],
    nhl: [['atg', 'Anytime goal', [null]], ['points', 'Points', [1, 2]], ['shots', 'Shots on goal', [2, 3, 4]], ['saves', 'Goalie saves', [20, 25, 30]]]
  };
  function propRelevant(sp, key, p, rows) {
    if (sp === 'nhl') return key === 'saves' ? p.pos === 'G' : p.pos !== 'G';
    const avg = (k) => rows.reduce((s, r) => s + (r[k] || 0), 0) / Math.max(1, rows.length);
    if (key === 'pass_yds' || key === 'pass_td') return avg('pass_att') >= 10;
    if (key === 'rec_yds' || key === 'rec') return avg('targets') >= 2;
    if (key === 'rush_yds') return avg('rush_att') >= 3;
    return avg('rush_att') + avg('targets') >= 2.5; // anytime TD, rush + rec
  }
  function upcomingSlice(sp) { return S.U[sp].slice().sort((a, b) => (a.date < b.date ? -1 : 1)).slice(0, sp === 'nfl' ? 16 : 30); }
  function gameBetRows(sp) { // moneyline, puck line / spread and totals for every upcoming game
    const M = S.M[sp]; const out = [];
    for (const g of upcomingSlice(sp)) {
      const gm = K.gameModel(M, g); const base = { kind: 'game', g, n: null, avg: null, hits: null };
      for (const team of [gm.away, gm.home]) {
        const r = K.betProb(M, gm, { type: 'win', team }); const ml = team === g.home ? g.home_ml : g.away_ml;
        out.push(Object.assign({}, base, { type: 'ml', typeLabel: 'Moneyline', team, who: team, bet: 'To win', prob: r.p, mkt: ml !== '' && ml != null ? +ml : null,
          add: 'data-add="win" data-sp="' + sp + '" data-game="' + esc(g.game_id) + '" data-team="' + esc(team) + '"' }));
      }
      const spreads = [];
      if (sp === 'nhl') { [gm.away, gm.home].forEach((team) => { spreads.push([team, -1.5], [team, 1.5]); }); }
      else if (gm.mktMargin != null) { [gm.away, gm.home].forEach((team) => { const l = team === gm.home ? -gm.mktMargin : gm.mktMargin; [l - 3, l, l + 3].forEach((x) => spreads.push([team, x])); }); }
      for (const [team, line] of spreads) {
        const r = K.betProb(M, gm, { type: 'spread', team, line });
        out.push(Object.assign({}, base, { type: 'spread', typeLabel: sp === 'nhl' ? 'Puck line' : 'Spread', team, who: team, bet: (sp === 'nhl' ? 'Puck line ' : 'Spread ') + (line > 0 ? '+' : '') + line, prob: r.p, mkt: null,
          add: 'data-add="spread" data-sp="' + sp + '" data-game="' + esc(g.game_id) + '" data-team="' + esc(team) + '" data-line="' + line + '"' }));
      }
      const mid = g.over_under !== '' && g.over_under != null ? +g.over_under : Math.round(gm.total * 2) / 2;
      const step = sp === 'nhl' ? 1 : 3;
      for (const line of [mid - step, mid, mid + step]) {
        for (const side of ['over', 'under']) {
          const r = K.betProb(M, gm, { type: 'total', side, line });
          out.push(Object.assign({}, base, { type: 'total', typeLabel: 'Total', team: null, who: 'Game total', bet: (side === 'over' ? 'Over ' : 'Under ') + line + (sp === 'nhl' ? ' goals' : ' points') + (line === mid && g.over_under !== '' ? ' (market)' : ''), prob: r.p, mkt: null,
            add: 'data-add="total" data-sp="' + sp + '" data-game="' + esc(g.game_id) + '" data-side="' + side + '" data-line="' + line + '"' }));
        }
      }
    }
    return out;
  }
  function propBetRows(sp) {
    const M = S.M[sp]; const out = [];
    for (const g of upcomingSlice(sp)) {
      const gm = K.gameModel(M, g);
      for (const p of Object.values(M.players)) {
        if (p.team !== g.home && p.team !== g.away) continue;
        const rows = K.eligibleRows(sp, p); if (rows.length < 2) continue;
        if (isOut(sp, p)) continue;
        const inj = injOf(sp, p);
        for (const [key, label, lines] of MILESTONES[sp]) {
          if (!propRelevant(sp, key, p, rows)) continue;
          if (key === 'saves' && goalieExcluded(g, p)) continue;
          const vals = rows.map((x) => K.statVal(sp, key, x)); const avg = K.mean(vals);
          // our standard milestones plus any DraftKings milestone with posted odds
          const msList = lines[0] == null ? [null] : Array.from(new Set(lines.concat(dkLadder(sp, g.game_id, p.id, key)))).sort((a, b) => a - b);
          const bookLine = dkLine(sp, g.game_id, p.id, key);
          for (const ms of msList) {
            const line = ms == null ? 0.5 : ms - 0.5; const r = K.propProb(M, p, key, 'over', line, gm);
            if (r.p == null || isNaN(r.p)) continue;
            const st = key === 'saves' ? starterFor(g, p.team) : null; const mkt = dkOdds(sp, g.game_id, p.id, key, ms);
            out.push({ kind: 'prop', g, type: key, typeLabel: label, team: p.team, who: p.name, pos: p.pos, pl: p, inj, starter: st ? st.status || 'Projected' : null, bet: ms == null ? label : ms + '+ ' + label.toLowerCase().replace(/ yds$/, ' yards'), prob: r.p, mkt, bookLine, n: rows.length, avg, ms,
              hits: vals.filter((v) => v >= (ms == null ? 1 : ms)).length,
              add: 'data-add="prop" data-sp="' + sp + '" data-game="' + esc(g.game_id) + '" data-pid="' + esc(p.id) + '" data-key="' + key + '" data-line="' + line + '"' + (ms != null ? ' data-ms="' + ms + '"' : '') });
          }
        }
      }
    }
    return out;
  }
  function renderProps() {
    const sp = S.sp, M = S.M[sp]; S.props = S.props || {}; S.betRows = S.betRows || {};
    if (!S.betRows[sp]) S.betRows[sp] = gameBetRows(sp).concat(propBetRows(sp));
    const all = S.betRows[sp];
    const games = upcomingSlice(sp);
    const F = S.props[sp] || (S.props[sp] = { key: '', game: games[0] ? games[0].game_id : '', team: '', min: 3, q: '' });
    const g0 = games.find((g) => g.game_id === F.game) || null; if (!g0) { F.game = ''; F.team = ''; }
    const q = F.q.trim().toLowerCase();
    const typeOk = (r) => !F.key || (F.key === 'game' ? r.kind === 'game' : F.key === 'props' ? r.kind === 'prop' : r.type === F.key);
    const list = all.filter((r) => typeOk(r) && (!F.game || r.g.game_id === F.game) && (!F.team || r.team === F.team) && (r.kind !== 'prop' || r.n >= F.min) &&
      (!q || r.who.toLowerCase().includes(q) || (r.team || '').toLowerCase().includes(q) || r.bet.toLowerCase().includes(q)));
    let h = '<div class="hero"><h2>' + (sp === 'nfl' ? 'NFL bets' : 'NHL bets') + '<span>Pick a game and a bet type, then sort by any column</span></h2><div class="pills"><span class="pillc"><b>' + list.length.toLocaleString() + '</b> bets</span></div></div>';
    const spreadName = sp === 'nhl' ? 'Puck line' : 'Spread';
    h += '<div class="toolbar"><label class="f grow">Game<select id="pr-game">' + opt('', 'All upcoming games', !F.game) + games.map((g) => opt(g.game_id, abbr(M, g.away) + ' @ ' + abbr(M, g.home) + ' - ' + fmtET.format(new Date(g.date)) + ' ET', g.game_id === F.game)).join('') + '</select></label>' +
      '<label class="f">Bet type<select id="pr-key">' + opt('', 'All bets', !F.key) + '<optgroup label="Game bets">' + opt('game', 'All game bets', F.key === 'game') + opt('ml', 'Moneyline', F.key === 'ml') + opt('spread', spreadName, F.key === 'spread') + opt('total', 'Total', F.key === 'total') + '</optgroup><optgroup label="Player props">' + opt('props', 'All player props', F.key === 'props') + MILESTONES[sp].map(([k, l]) => opt(k, l, k === F.key)).join('') + '</optgroup></select></label>' +
      (g0 ? '<label class="f">Team<select id="pr-team">' + opt('', 'Both teams', !F.team) + [g0.away, g0.home].map((t) => opt(t, t, t === F.team)).join('') + '</select></label>' : '') +
      '<label class="f">Props: min games<select id="pr-min">' + [2, 3, 4, 5, 6].map((n) => opt(n, n + '+ games', n === F.min)).join('') + '</select></label>' +
      '<label class="f grow">Search<input id="pr-q" type="search" placeholder="Player, team or bet" value="' + esc(F.q) + '"></label></div>';
    if (g0) {
      const gm = K.gameModel(M, g0); const favHome = gm.homeWin >= 0.5;
      h += '<div class="card gsum">' + teamRow(M, gm.away, gm.awayWin, !favHome) + teamRow(M, gm.home, gm.homeWin, favHome) + goalieLine(g0) +
        '<div class="g-proj"><span>' + esc(fmtET.format(new Date(g0.date))) + ' ET</span><span>Projected <b>' + esc(abbr(M, gm.away)) + ' ' + (sp === 'nfl' ? gm.asB.toFixed(1) : gm.la.toFixed(2)) + ' &ndash; ' + esc(abbr(M, gm.home)) + ' ' + (sp === 'nfl' ? gm.hsB.toFixed(1) : gm.lh.toFixed(2)) + '</b></span><span class="g-lines">' + lineTags(M, g0, gm) + '</span></div></div>';
    }
    const miss = -1e9;
    const cols = [
      { k: 'prob', h: 'Chance', n: 1, v: (r) => r.prob, html: 1, f: (r) => '<span class="pcell"><b>' + pc(r.prob) + '</b><i><s style="width:' + (r.prob * 100).toFixed(0) + '%"></s></i></span>' },
      { k: 'who', h: 'Pick', v: (r) => r.who, html: 1, f: (r) => '<span class="tcell">' + (r.team ? badge(M, r.team, true) : '<span class="mono sm">TOT</span>') + esc(r.who) + (r.pos ? ' <em class="ppos">' + esc(r.pos) + '</em>' : '') + (r.pl ? injTag(sp, r.pl) : '') + (r.starter ? ' <em class="inj st" title="Starting goalie: ' + esc(r.starter) + '">' + esc(/confirm/i.test(r.starter) ? 'STARTER' : 'LIKELY') + '</em>' : '') + '</span>' },
      { k: 'bet', h: 'Bet', v: (r) => r.bet, f: (r) => r.bet },
      { k: 'type', h: 'Type', v: (r) => (r.kind === 'game' ? '0' : '1') + r.typeLabel, html: 1, f: (r) => '<span class="ttag tg-' + r.kind + '">' + esc(r.typeLabel) + '</span>' },
      { k: 'game', h: 'Game', v: (r) => r.g.date + r.g.game_id, f: (r) => abbr(M, r.g.away) + ' @ ' + abbr(M, r.g.home) + ' ' + fmtShort.format(new Date(r.g.date)) },
      { k: 'fair', h: 'Fair odds', n: 1, v: (r) => r.prob, f: (r) => fairOdds(r.prob) },
      { k: 'book', h: 'DK line', n: 1, v: (r) => (r.bookLine == null ? miss : r.bookLine), f: (r) => (r.bookLine == null ? '-' : 'O/U ' + r.bookLine) },
      { k: 'mkt', h: 'DK odds', n: 1, v: (r) => (r.mkt == null ? miss : -K.amToProb(r.mkt)), f: (r) => (r.mkt == null ? '-' : (r.mkt > 0 ? '+' : '') + r.mkt) },
      { k: 'edge', h: 'Edge', n: 1, v: (r) => (r.mkt == null ? miss : r.prob - K.amToProb(r.mkt)), html: 1, f: (r) => { if (r.mkt == null) return '<span class="muted">-</span>'; const e = (r.prob - K.amToProb(r.mkt)) * 100; return '<span class="' + (e >= 0 ? 'up' : 'dn') + '">' + (e >= 0 ? '+' : '') + e.toFixed(1) + '</span>'; } },
      { k: 'hits', h: 'Hit rate', n: 1, v: (r) => (r.n ? r.hits / r.n : miss), f: (r) => (r.n ? r.hits + ' of ' + r.n : '-') },
      { k: 'avg', h: 'Avg', n: 1, v: (r) => (r.avg == null ? miss : r.avg), f: (r) => (r.avg == null ? '-' : (r.ms == null ? r.avg.toFixed(2) : r.avg.toFixed(1))) },
      { k: 'add', h: 'Parlay', v: () => 0, html: 1, f: (r) => addBtn(r.add, '+ Add') }
    ];
    const tid = 'bets-' + sp; if (!S.players.sort[tid]) S.players.sort[tid] = { key: 'prob', dir: 'desc' };
    const st = S.players.sort[tid]; const c = cols.find((x) => x.k === st.key) || cols[0];
    const sorted = list.slice().sort((a, b) => { const x = c.v(a), y = c.v(b); const d = (typeof x === 'string' ? x.localeCompare(y) : x - y) * (st.dir === 'asc' ? 1 : -1); return d || (b.prob - a.prob); });
    const shown = sorted.slice(0, 300);
    h += table(tid, cols, shown, { [tid]: st, presorted: true }, 'props');
    if (sorted.length > shown.length) h += '<p class="note">Showing the top ' + shown.length + ' of ' + sorted.length.toLocaleString() + '. Pick a game or bet type to narrow it down.</p>';
    h += '<p class="note">Click any column header to sort, and click again to reverse. "DK odds" are DraftKings prices (moneylines for game bets; "X or more" and anytime odds for NHL props) and "Edge" is the chance minus the price\'s implied chance, so a positive edge means the estimate is above what the price implies. "DK line" is the player\'s main DraftKings over/under line for that stat. NFL prop odds are not in the free feed yet. Player props are "X or more" bets. Players ruled out on the ESPN injury report are left off, questionable ones are tagged, and NHL saves props only list the announced starter. Late scratches, snap counts and weather are not in the model.</p>';
    return h;
  }

  /* ---------- Accuracy: walk-forward backtest on games already played ---------- */
  function runBacktest(sp) {
    const R = S.raw[sp]; const games = R.games.slice().sort((a, b) => (a.date < b.date ? -1 : 1));
    const by = {}; games.forEach((g) => { const k = sp === 'nfl' ? 'w' + String(g.week).padStart(2, '0') : dayKey(g.date); (by[k] = by[k] || []).push(g); });
    const slots = Object.keys(by).sort().map((k) => by[k]);
    const pgByGame = {}; R.player_games.forEach((r) => { (pgByGame[r.game_id] = pgByGame[r.game_id] || []).push(r); });
    const out = { win: [], winModel: [], winMkt: [], total: [], props: [], bets: [], nGames: 0, from: null, to: null, favRight: 0, mktFavRight: 0, mktN: 0 };
    const minPrior = sp === 'nfl' ? 32 : 64; // a few games per team before testing starts
    const prior = []; const ids = new Set();
    for (const slot of slots) {
      if (prior.length >= minPrior) {
        const Mb = K.buildSport(sp, prior, R.team_games.filter((r) => ids.has(r.game_id)), R.player_games.filter((r) => ids.has(r.game_id)));
        for (const g of slot) {
          const gm = K.gameModel(Mb, g); const y = g.home_score > g.away_score ? 1 : 0;
          out.nGames++; out.from = out.from || g.date; out.to = g.date;
          out.win.push([gm.homeWin, y]); out.winModel.push([gm.modelHomeWin, y]);
          if ((gm.homeWin >= 0.5 ? 1 : 0) === y) out.favRight++;
          modelBets(sp, Mb, gm, g, out.bets);
          if (gm.mktHomeWin != null) { out.winMkt.push([gm.mktHomeWin, y]); out.mktN++; if ((gm.mktHomeWin >= 0.5 ? 1 : 0) === y) out.mktFavRight++; }
          if (g.over_under !== '' && g.over_under != null) { const line = +g.over_under, tot = g.home_score + g.away_score; if (tot !== line) out.total.push([K.betProb(Mb, gm, { type: 'total', side: 'over', line }).p, tot > line ? 1 : 0]); }
          for (const row of (pgByGame[g.game_id] || [])) {
            const p = Mb.players[row.player_id]; if (!p) continue;
            const prows = K.eligibleRows(sp, p); if (prows.length < 3) continue;
            for (const [key, , lines] of MILESTONES[sp]) {
              if (!propRelevant(sp, key, p, prows)) continue;
              if (key === 'saves' && !(row.shots_against > 0)) continue;
              if (sp === 'nhl' && key !== 'saves' && row.pos === 'G') continue;
              const actual = K.statVal(sp, key, row);
              for (const ms of lines) {
                const r = K.propProb(Mb, p, key, 'over', ms == null ? 0.5 : ms - 0.5, gm);
                if (r.p != null && !isNaN(r.p)) out.props.push([r.p, actual >= (ms == null ? 1 : ms) ? 1 : 0, key]);
              }
            }
          }
        }
      }
      slot.forEach((g) => { prior.push(g); ids.add(g.game_id); });
    }
    return out;
  }
  /* ---------- Model Bets: the side the model would have bet in every game, graded ---------- */
  const VALUE_EDGE = 0.02; // a "value bet" = model chance at least 2 points above the price's implied chance
  function payout(odds) { return odds > 0 ? odds / 100 : 100 / -odds; }
  function modelBets(sp, M, gm, g, list) {
    const d = dayKey(g.date), game = abbr(M, g.away) + ' @ ' + abbr(M, g.home);
    const margin = g.home_score - g.away_score, tot = g.home_score + g.away_score;
    const add = (type, bet, team, p, price, res) => {
      const imp = K.amToProb(price);
      list.push({ d, date: g.date, gid: g.game_id, game, type, bet, team, p, price, res, edge: imp == null ? null : p - imp, units: res === 'W' ? payout(price) : res === 'L' ? -1 : 0 });
    };
    const hm = +g.home_ml, am = +g.away_ml;
    if (hm && am && isFinite(hm) && isFinite(am)) { // moneyline: the side the model makes more likely to win
      const home = gm.homeWin >= 0.5, team = home ? g.home : g.away;
      add('ml', abbr(M, team) + ' to win', team, home ? gm.homeWin : gm.awayWin, home ? hm : am, margin === 0 ? 'P' : (margin > 0) === home ? 'W' : 'L');
    }
    if (sp === 'nfl' && gm.mktMargin != null) { // spread at the DraftKings closing number, -110 assumed
      const hl = -gm.mktMargin;
      const ph = K.betProb(M, gm, { type: 'spread', team: g.home, line: hl }).p, pa = K.betProb(M, gm, { type: 'spread', team: g.away, line: -hl }).p;
      const home = ph >= pa, line = home ? hl : -hl, cov = (home ? margin : -margin) + line, team = home ? g.home : g.away;
      add('spread', abbr(M, team) + ' ' + (line > 0 ? '+' : '') + line, team, home ? ph : pa, -110, cov > 0 ? 'W' : cov < 0 ? 'L' : 'P');
    }
    if (g.over_under !== '' && g.over_under != null) { // total at the DraftKings closing number, -110 assumed
      const line = +g.over_under;
      const po = K.betProb(M, gm, { type: 'total', side: 'over', line }).p, pu = K.betProb(M, gm, { type: 'total', side: 'under', line }).p;
      const over = po >= pu, diff = tot - line;
      add('total', (over ? 'Over ' : 'Under ') + line, null, over ? po : pu, -110, diff === 0 ? 'P' : (diff > 0) === over ? 'W' : 'L');
    }
  }
  function betRec(list) {
    const w = list.filter((b) => b.res === 'W').length, l = list.filter((b) => b.res === 'L').length, p = list.length - w - l;
    const u = list.reduce((s, b) => s + b.units, 0);
    return { n: list.length, w, l, p, hit: w + l ? w / (w + l) : null, units: u, roi: list.length - p ? u / (list.length - p) : null };
  }
  const uTxt = (u) => '<span class="' + (u >= 0 ? 'up' : 'dn') + '">' + (u >= 0 ? '+' : '') + u.toFixed(2) + 'u</span>';
  const roiTxt = (r) => (r == null ? '-' : '<span class="' + (r >= 0 ? 'up' : 'dn') + '">' + (r >= 0 ? '+' : '') + (r * 100).toFixed(1) + '%</span>');
  const wlTxt = (r) => r.w + '-' + r.l + (r.p ? '-' + r.p : '');
  function recTable(head, rows) {
    return '<div class="tscroll"><table class="data"><thead><tr>' + [head, 'Bets', 'W-L-P', 'Hit %', 'Units', 'ROI'].map((x, i) => '<th class="' + (i ? 'n' : '') + '"><button type="button" tabindex="-1">' + esc(x) + '</button></th>').join('') + '</tr></thead><tbody>' +
      rows.filter(([, r]) => r.n).map(([label, r]) => '<tr><td>' + label + '</td><td class="n">' + r.n + '</td><td class="n">' + wlTxt(r) + '</td><td class="n">' + (r.hit == null ? '-' : pc(r.hit, 1)) + '</td><td class="n">' + uTxt(r.units) + '</td><td class="n">' + roiTxt(r.roi) + '</td></tr>').join('') + '</tbody></table></div>';
  }
  function ensureBt(sp, tab) {
    S.bt = S.bt || {};
    if (S.bt[sp]) return S.bt[sp];
    setTimeout(() => { try { S.bt[sp] = runBacktest(sp); } catch (e) { S.bt[sp] = { error: e.message }; } if (S.tab === tab && S.sp === sp) render(); }, 40);
    return null;
  }
  function renderTrack() {
    const sp = S.sp, M = S.M[sp], nfl = sp === 'nfl';
    let h = '<div class="hero"><h2>Model bets tracker<span>Every ' + (nfl ? 'moneyline, spread and total' : 'moneyline and total') + ' the model would have bet, graded</span></h2></div>';
    h += '<p class="lede">For each ' + (nfl ? 'week' : 'day') + ', the model is rebuilt from only the games before it, then it takes a side in every game against the DraftKings closing line: the side it gives the better chance. Each bet is 1 unit.</p>';
    const B = ensureBt(sp, 'track');
    if (!B) return h + '<p class="empty">Grading every game so far. This takes a few seconds...</p>';
    if (B.error) return h + '<p class="empty err">The tracker did not finish (' + esc(B.error) + ').</p>';
    const all = B.bets, val = all.filter((b) => b.edge != null && b.edge >= VALUE_EDGE);
    if (!all.length) return h + '<p class="empty">No graded bets yet.</p>';
    const A = betRec(all), V = betRec(val);
    const days = Array.from(new Set(all.map((b) => b.d))).sort().reverse();
    const last = days[0], L = betRec(all.filter((b) => b.d === last));
    const fmtD = (d) => fmtShort.format(new Date(d + 'T12:00:00Z'));
    h += '<section class="tiles">' +
      '<div class="card tile"><span class="k">All model bets</span><b>' + wlTxt(A) + '</b><span>' + (A.hit == null ? '' : pc(A.hit, 1) + ' hit') + ' &middot; ' + A.n + ' bets</span></div>' +
      '<div class="card tile"><span class="k">Units won/lost</span><b>' + uTxt(A.units) + '</b><span>ROI ' + roiTxt(A.roi) + '</span></div>' +
      '<div class="card tile"><span class="k">Value bets only</span><b>' + (V.n ? wlTxt(V) : '-') + '</b><span>' + (V.n ? uTxt(V.units) + ' &middot; ROI ' + roiTxt(V.roi) : 'none yet') + '</span></div>' +
      '<div class="card tile"><span class="k">Latest day (' + esc(fmtD(last)) + ')</span><b>' + wlTxt(L) + '</b><span>' + uTxt(L.units) + '</span></div></section>';
    const types = [['ml', 'Moneyline']].concat(nfl ? [['spread', 'Spread']] : []).concat([['total', 'Total']]);
    h += '<section class="card acc"><h2>By bet type</h2>' + recTable('Bet type', types.map(([k, l]) => [esc(l), betRec(all.filter((b) => b.type === k))])) +
      '<h3 class="mini">Value bets only (chance at least ' + (VALUE_EDGE * 100) + ' points above the price)</h3>' +
      (V.n ? recTable('Bet type', types.map(([k, l]) => [esc(l), betRec(val.filter((b) => b.type === k))])) : '<p class="note">None yet. The model leans heavily on the market, so it rarely finds a price it beats by that much.</p>') + '</section>';
    const buckets = [[0.5, 0.55], [0.55, 0.6], [0.6, 0.7], [0.7, 1.01]];
    h += '<section class="card acc"><h2>By model confidence</h2>' + recTable('Model chance', buckets.map(([a, b]) => [Math.round(a * 100) + (b > 1 ? '%+' : '-' + Math.round(b * 100) + '%'), betRec(all.filter((x) => x.p >= a && x.p < b))])) + '</section>';
    h += '<section class="card acc"><h2>By day</h2>' + recTable('Day', days.slice(0, 14).map((d) => [esc(fmtD(d)), betRec(all.filter((b) => b.d === d))])) + '</section>';
    const recent = all.filter((b) => days.slice(0, 3).includes(b.d)).sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
    const chip = (r) => '<span class="' + (r === 'W' ? 'up' : r === 'L' ? 'dn' : 'muted') + '"><b>' + ({ W: 'WIN', L: 'LOSS', P: 'PUSH' }[r]) + '</b></span>';
    h += '<section class="card acc"><h2>Recent bets</h2><div class="tscroll"><table class="data"><thead><tr>' + ['Day', 'Game', 'Bet', 'Chance', 'Price', 'Edge', 'Result', 'Units'].map((x, i) => '<th class="' + (i >= 3 && i !== 6 ? 'n' : '') + '"><button type="button" tabindex="-1">' + x + '</button></th>').join('') + '</tr></thead><tbody>' +
      recent.map((b) => '<tr><td>' + esc(fmtD(b.d)) + '</td><td>' + esc(b.game) + '</td><td><span class="tcell">' + (b.team ? badge(M, b.team, true) : '<span class="mono sm">TOT</span>') + esc(b.bet) + '</span></td><td class="n">' + pc(b.p) + '</td><td class="n">' + (b.price > 0 ? '+' : '') + b.price + '</td><td class="n">' + (b.edge == null ? '-' : '<span class="' + (b.edge >= 0 ? 'up' : 'dn') + '">' + (b.edge >= 0 ? '+' : '') + (b.edge * 100).toFixed(1) + '</span>') + '</td><td>' + chip(b.res) + '</td><td class="n">' + uTxt(b.units) + '</td></tr>').join('') + '</tbody></table></div></section>';
    h += '<p class="note">How it is graded: final scores from ESPN. Moneylines use the DraftKings closing price; ' + (nfl ? 'spreads and ' : '') + 'totals use the DraftKings closing number at an assumed -110, because the feed does not keep those prices. A tie on the number is a push (no units). ' + (nfl ? '' : 'Puck lines are not tracked because the feed has no puck-line prices. ') + 'The model weights the betting market heavily, so most moneyline picks are the favorite; the honest test of an edge is the value-bet line. Settings fitted on Nov 2 are used throughout, so games before then flatter the model a little. New games are added each time the data is refreshed.</p>';
    return h;
  }

  function calib(pairs) {
    const b = Array.from({ length: 10 }, () => ({ n: 0, p: 0, y: 0 })); let brier = 0, hits = 0;
    pairs.forEach(([p, y]) => { const i = Math.min(9, Math.floor(p * 10)); b[i].n++; b[i].p += p; b[i].y += y; brier += (p - y) ** 2; hits += y; });
    const n = pairs.length; const rate = n ? hits / n : 0; let base = 0; pairs.forEach(([, y]) => { base += (rate - y) ** 2; });
    return { n, brier: n ? brier / n : null, skill: n && base ? 1 - brier / base : null, rate, avgP: n ? pairs.reduce((s, x) => s + x[0], 0) / n : null,
      buckets: b.map((x, i) => ({ lo: i * 10, hi: i * 10 + 10, n: x.n, p: x.n ? x.p / x.n : null, y: x.n ? x.y / x.n : null })) };
  }
  function calibTable(c, unit) {
    const rows = c.buckets.filter((b) => b.n > 0);
    return '<div class="tscroll"><table class="data calib"><thead><tr><th><button type="button" tabindex="-1">Model said</button></th><th class="n"><button type="button" tabindex="-1">Avg chance</button></th><th class="n"><button type="button" tabindex="-1">Actually hit</button></th><th><button type="button" tabindex="-1">Predicted vs actual</button></th><th class="n"><button type="button" tabindex="-1">' + esc(unit) + '</button></th></tr></thead><tbody>' +
      rows.map((b) => { const gap = (b.y - b.p) * 100; return '<tr><td>' + b.lo + '-' + b.hi + '%</td><td class="n">' + pc(b.p) + '</td><td class="n ' + (Math.abs(gap) <= 5 ? 'up' : Math.abs(gap) <= 10 ? '' : 'dn') + '">' + pc(b.y) + '</td><td><span class="cbar"><i style="width:' + (b.p * 100).toFixed(0) + '%"></i><s style="width:' + (b.y * 100).toFixed(0) + '%"></s></span></td><td class="n">' + b.n.toLocaleString() + '</td></tr>'; }).join('') + '</tbody></table></div>';
  }
  function verdictLine(c) {
    const best = c.buckets.filter((b) => b.n >= 20 && b.lo >= 50).sort((a, b) => b.n - a.n)[0];
    if (!best) return '';
    return 'When it said ' + best.lo + '-' + best.hi + '%, those bets hit ' + pc(best.y) + ' of the time (' + best.n.toLocaleString() + ' bets).';
  }
  function skillText(s) { if (s == null) return '-'; return (s >= 0 ? '+' : '') + (s * 100).toFixed(1) + '%'; }
  function renderAcc() {
    const sp = S.sp;
    let h = '<div class="hero"><h2>How accurate is it?<span>A test on ' + (sp === 'nfl' ? 'NFL' : 'NHL') + ' games already played</span></h2></div>';
    h += '<p class="lede">For each ' + (sp === 'nfl' ? 'week' : 'day') + ', the model is rebuilt using only the games before it, then its chances are checked against what happened. A well-calibrated model\'s 70% bets hit about 70% of the time.</p>';
    const B = ensureBt(sp, 'acc');
    if (!B) return h + '<p class="empty">Running the test on every game so far. This takes a few seconds...</p>'; if (B.error) return h + '<p class="empty err">The test did not finish (' + esc(B.error) + ').</p>';
    const cw = calib(B.win), cm = calib(B.winModel), ck = calib(B.winMkt), ct = calib(B.total), cp = calib(B.props);
    h += '<section class="tiles">' +
      '<div class="card tile"><span class="k">Games tested</span><b>' + B.nGames + '</b><span>' + (B.from ? esc(fmtShort.format(new Date(B.from))) + ' to ' + esc(fmtShort.format(new Date(B.to))) : '') + '</span></div>' +
      '<div class="card tile"><span class="k">Picked the winner</span><b>' + pc(B.favRight / Math.max(1, B.nGames)) + '</b><span>Market favorite: ' + (B.mktN ? pc(B.mktFavRight / B.mktN) : '-') + '</span></div>' +
      '<div class="card tile"><span class="k">Props tested</span><b>' + cp.n.toLocaleString() + '</b><span>' + (cp.n ? 'Avg chance ' + pc(cp.avgP) + ', hit ' + pc(cp.rate) : '') + '</span></div>' +
      '<div class="card tile"><span class="k">Prop skill score</span><b>' + skillText(cp.skill) + '</b><span>Above 0 beats guessing the average</span></div></section>';
    h += '<section class="card acc"><h2>Game winners</h2><p class="note" style="margin-top:0">' + esc(verdictLine(cw)) + ' Skill scores (higher is better, 0 = no better than always guessing the home-win rate): blended <b>' + skillText(cw.skill) + '</b>, model alone <b>' + skillText(cm.skill) + '</b>, betting market alone <b>' + skillText(ck.skill) + '</b>.</p>' + calibTable(cw, 'Games') + '</section>';
    if (ct.n) h += '<section class="card acc"><h2>Totals: over the closing line</h2><p class="note" style="margin-top:0">' + esc(verdictLine(ct) || 'Totals sit close to 50% because the line is set to split the action.') + ' Skill score <b>' + skillText(ct.skill) + '</b> on ' + ct.n + ' games.</p>' + calibTable(ct, 'Games') + '</section>';
    h += '<section class="card acc"><h2>Player props ("X or more")</h2><p class="note" style="margin-top:0">' + esc(verdictLine(cp)) + '</p>' + calibTable(cp, 'Bets');
    const keys = {}; B.props.forEach(([p, y, k]) => { (keys[k] = keys[k] || []).push([p, y]); });
    h += '<h3 class="mini">By prop type</h3><div class="tscroll"><table class="data"><thead><tr><th><button type="button" tabindex="-1">Prop</button></th><th class="n"><button type="button" tabindex="-1">Bets</button></th><th class="n"><button type="button" tabindex="-1">Avg chance</button></th><th class="n"><button type="button" tabindex="-1">Actually hit</button></th><th class="n"><button type="button" tabindex="-1">Skill</button></th></tr></thead><tbody>' +
      MILESTONES[sp].filter(([k]) => keys[k]).map(([k, l]) => { const c = calib(keys[k]); const gap = Math.abs(c.rate - c.avgP) * 100; return '<tr><td>' + esc(l) + '</td><td class="n">' + c.n.toLocaleString() + '</td><td class="n">' + pc(c.avgP) + '</td><td class="n ' + (gap <= 3 ? 'up' : gap > 7 ? 'dn' : '') + '">' + pc(c.rate) + '</td><td class="n">' + skillText(c.skill) + '</td></tr>'; }).join('') + '</tbody></table></div></section>';
    h += '<p class="note"><b>Adjustments made from this test (Nov 2):</b> the betting market now gets 85% of the weight for winners and totals (up from 60%), and prop chances include a calibration step fitted from this test, because raw 40-85% props were landing 5-8 points lower than predicted. Because that step was fitted on these same games, the props section here looks somewhat better than a fresh test would; the honest check is how it does on games still to come.</p>' +
      '<p class="note">How to read this: green "actually hit" figures are within 5 points of what the model said; red ones are more than 10 points off. The test uses closing betting lines for the market blend, and the injury and goalie data only exists for upcoming games, so it is not part of this test.' + (sp === 'nfl' ? ' NFL box scores only list players who recorded a stat, so players who were shut out entirely are missing, which flatters NFL props a little.' : '') + ' ' + B.nGames + ' games is still a small sample; the picture firms up as the season goes on.</p>';
    return h;
  }

  /* ---------- generic sortable table ---------- */
  function table(id, cols, rows, sortState, cls) {
    const st = sortState[id] || {}; let data = rows.slice();
    if (st.key && !sortState.presorted) { const c = cols.find((x) => x.k === st.key); if (c) data.sort((a, b) => { const x = c.v(a), y = c.v(b); return (typeof x === 'string' ? x.localeCompare(y) : x - y) * (st.dir === 'asc' ? 1 : -1); }); }
    return '<div class="tscroll"><table class="data ' + (cls || '') + '" data-tid="' + id + '"><thead><tr>' + cols.map((c) => '<th scope="col" data-k="' + c.k + '" class="' + (c.n ? 'n' : '') + (st.key === c.k ? ' on' : '') + '" aria-sort="' + (st.key === c.k ? (st.dir === 'asc' ? 'ascending' : 'descending') : 'none') + '"><button type="button">' + esc(c.h) + '</button></th>').join('') + '</tr></thead><tbody>' + data.map((r) => '<tr' + (r._attr ? ' ' + r._attr : '') + '>' + cols.map((c) => '<td class="' + (c.n ? 'n' : '') + '">' + (c.html ? c.f(r) : esc(c.f ? c.f(r) : c.v(r))) + '</td>').join('') + '</tr>').join('') + '</tbody></table></div>';
  }

  /* ---------- Teams ---------- */
  function renderTeams() {
    const M = S.M[S.sp]; const nfl = S.sp === 'nfl'; const d = nfl ? 1 : 2;
    const cols = [
      { k: 'rank', h: '#', n: 1, v: (t) => t.rank, html: 1, f: (t) => '<span class="rk">' + t.rank + '</span>' },
      { k: 'name', h: 'Team', v: (t) => t.name, html: 1, f: (t) => '<span class="tcell">' + badge(M, t.name, true) + esc(t.name) + '</span>' },
      { k: 'rec', h: 'Record', n: 1, v: (t) => t.w * 10 + (nfl ? 0 : t.otl), f: (t) => t.w + '-' + t.l + (nfl ? '' : '-' + t.otl) },
      { k: 'pfg', h: nfl ? 'Pts/G' : 'Goals/G', n: 1, v: (t) => t.pfg, f: (t) => t.pfg.toFixed(d) }, { k: 'pag', h: nfl ? 'Opp pts/G' : 'Opp goals/G', n: 1, v: (t) => -t.pag, f: (t) => t.pag.toFixed(d) },
      { k: 'off', h: 'Offence rating', n: 1, v: (t) => t.off, f: (t) => (t.off >= 0 ? '+' : '') + t.off.toFixed(d) }, { k: 'def', h: 'Defence rating', n: 1, v: (t) => -t.def, f: (t) => (t.def <= 0 ? '+' : '') + (-t.def).toFixed(d) },
      { k: 'net', h: 'Net rating', n: 1, v: (t) => t.net, f: (t) => (t.net >= 0 ? '+' : '') + t.net.toFixed(d) }
    ];
    return '<p class="lede">Ratings measure how many ' + (nfl ? 'points' : 'goals') + ' a team adds to (offence) or takes from (defence) the league average in a typical game, after adjusting for opponents and home advantage. They are pulled toward zero because about ' + Math.round(M.goals.n * 2 / M.teams.length) + ' games per team is still a small sample.</p>' + table('teams', cols, M.teams, S.players.sort, 'teams');
  }

  /* ---------- Players ---------- */
  const PCATS = {
    nfl: {
      rec: { label: 'Receiving', cols: ['gp', 'tgt', 'rec', 'recy', 'rectd', 'ypr'] }, rush: { label: 'Rushing', cols: ['gp', 'att', 'rushy', 'ypa', 'rushtd'] },
      pass: { label: 'Passing', cols: ['gp', 'cmp', 'att2', 'passy', 'passtd', 'int'] }, td: { label: 'Touchdowns', cols: ['gp', 'tds', 'rushtd', 'rectd', 'tdpg'] }
    },
    nhl: { sk: { label: 'Skaters', cols: ['gp', 'g', 'a', 'pts', 'sh', 'shp', 'toi'] }, gk: { label: 'Goalies', cols: ['gp', 'sv', 'sa', 'svp', 'ga'] } }
  };
  const CD = {
    gp: { h: 'GP', f: (a) => a.gp }, tgt: { h: 'Targets', f: (a) => a.tgt }, rec: { h: 'Rec', f: (a) => a.rec }, recy: { h: 'Rec yds', f: (a) => a.recy }, rectd: { h: 'Rec TD', f: (a) => a.rectd }, ypr: { h: 'Yds/rec', f: (a) => a.rec ? a.recy / a.rec : 0, d: 1 },
    att: { h: 'Carries', f: (a) => a.att }, rushy: { h: 'Rush yds', f: (a) => a.rushy }, ypa: { h: 'Yds/carry', f: (a) => a.att ? a.rushy / a.att : 0, d: 1 }, rushtd: { h: 'Rush TD', f: (a) => a.rushtd },
    cmp: { h: 'Comp', f: (a) => a.cmp }, att2: { h: 'Att', f: (a) => a.patt }, passy: { h: 'Pass yds', f: (a) => a.passy }, passtd: { h: 'Pass TD', f: (a) => a.passtd }, int: { h: 'INT', f: (a) => a.ints },
    tds: { h: 'Total TD', f: (a) => a.tds }, tdpg: { h: 'TD/game', f: (a) => a.gp ? a.tds / a.gp : 0, d: 2 },
    g: { h: 'Goals', f: (a) => a.g }, a: { h: 'Assists', f: (a) => a.a }, pts: { h: 'Points', f: (a) => a.g + a.a }, sh: { h: 'Shots', f: (a) => a.sh }, shp: { h: 'Shot %', f: (a) => a.sh ? 100 * a.g / a.sh : 0, d: 1 }, toi: { h: 'TOI/G', f: (a) => a.gp ? a.toi / a.gp : 0, d: 1 },
    sv: { h: 'Saves', f: (a) => a.sv }, sa: { h: 'Shots against', f: (a) => a.sa }, svp: { h: 'Save %', f: (a) => a.sa ? a.sv / a.sa : 0, d: 3 }, ga: { h: 'GA', f: (a) => a.ga }
  };
  function aggPlayer(M, p) {
    const rows = K.eligibleRows(M.sp, p); const a = { gp: rows.length };
    const sum = (k) => rows.reduce((s, r) => s + (r[k] || 0), 0);
    if (M.sp === 'nfl') Object.assign(a, { tgt: sum('targets'), rec: sum('rec'), recy: sum('rec_yds'), rectd: sum('rec_td'), att: sum('rush_att'), rushy: sum('rush_yds'), rushtd: sum('rush_td'), cmp: sum('pass_cmp'), patt: sum('pass_att'), passy: sum('pass_yds'), passtd: sum('pass_td'), ints: sum('ints'), tds: sum('tot_td') });
    else Object.assign(a, { g: sum('goals'), a: sum('assists'), sh: sum('shots'), toi: sum('toi'), sv: sum('saves'), sa: sum('shots_against'), ga: sum('goals_against') });
    return a;
  }
  function renderPlayers() {
    const sp = S.sp, M = S.M[sp]; const cats = PCATS[sp]; const cat = S.players.cat[sp] || Object.keys(cats)[0]; S.players.cat[sp] = cat;
    const q = S.players.q.trim().toLowerCase();
    let list = Object.values(M.players).map((p) => ({ p, a: aggPlayer(M, p) }));
    list = list.filter((x) => {
      if (q && !(x.p.name.toLowerCase().includes(q) || x.p.team.toLowerCase().includes(q))) return false;
      if (sp === 'nfl') { if (cat === 'rec') return x.a.tgt > 0; if (cat === 'rush') return x.a.att > 0; if (cat === 'pass') return x.a.patt > 0; return x.a.tds > 0; }
      return cat === 'gk' ? x.p.pos === 'G' && x.a.sa > 0 : x.p.pos !== 'G';
    });
    const cols = [{ k: 'name', h: 'Player', v: (r) => r.p.name, f: (r) => r.p.name }, { k: 'team', h: 'Team', v: (r) => (M.abbr[r.p.team] || r.p.team), f: (r) => M.abbr[r.p.team] || r.p.team }].concat(cats[cat].cols.map((c) => ({ k: c, h: CD[c].h, n: 1, v: (r) => CD[c].f(r.a), f: (r) => { const v = CD[c].f(r.a); return CD[c].d ? v.toFixed(CD[c].d) : v; } })));
    const tid = 'players-' + sp + cat; if (!S.players.sort[tid]) S.players.sort[tid] = { key: cats[cat].cols[cats[cat].cols.indexOf(cats[cat].cols.find((c) => c !== 'gp'))], dir: 'desc' };
    const st = S.players.sort[tid]; list.forEach((r) => { r._attr = 'data-pid="' + esc(r.p.id) + '"'; });
    let h = '<div class="toolbar"><div class="seg-ctl" role="tablist">' + Object.keys(cats).map((k) => '<button type="button" data-cat="' + k + '" class="' + (k === cat ? 'on' : '') + '">' + cats[k].label + '</button>').join('') + '</div><label class="f grow">Search<input id="p-q" type="search" placeholder="Player or team" value="' + esc(S.players.q) + '"></label></div>';
    if (S.players.sel && M.players[S.players.sel]) h += playerPanel(M, M.players[S.players.sel]);
    list = list.slice(0, 400);
    h += table(tid, cols, list, S.players.sort, 'players');
    return h;
  }
  function playerPanel(M, p) {
    const rows = K.eligibleRows(M.sp, p); const nfl = M.sp === 'nfl';
    const head = nfl ? ['Date', 'Opp', 'Rec', 'Rec yds', 'Rush', 'Rush yds', 'Pass yds', 'TD'] : (p.pos === 'G' ? ['Date', 'Opp', 'Saves', 'SA', 'GA'] : ['Date', 'Opp', 'G', 'A', 'Shots', 'TOI']);
    const body = rows.map((r) => (nfl ? [r.rec, r.rec_yds, r.rush_att, r.rush_yds, r.pass_yds, r.tot_td] : (p.pos === 'G' ? [r.saves, r.shots_against, r.goals_against] : [r.goals, r.assists, r.shots, (r.toi || 0).toFixed(1)])).reduce((s, v) => s + '<td class="n">' + esc(v) + '</td>', '<td>' + esc(fmtShort.format(new Date(r.date))) + '</td><td>' + esc(M.abbr[r.opp] || r.opp) + '</td>'));
    return '<section class="card ppanel"><div class="pp-h"><h2>' + esc(p.name) + '</h2><span>' + esc(p.team) + (p.pos ? ' &middot; ' + esc(p.pos) : '') + '</span><button type="button" id="p-close" aria-label="Close player">Close</button></div><div class="tscroll"><table class="data"><thead><tr>' + head.map((x, i) => '<th class="' + (i > 1 ? 'n' : '') + '">' + x + '</th>').join('') + '</tr></thead><tbody>' + body.map((r) => '<tr>' + r + '</tr>').join('') + '</tbody></table></div></section>';
  }

  /* ---------- Games ---------- */
  function renderGames() {
    const M = S.M[S.sp]; const t = S.games.team; const nfl = S.sp === 'nfl';
    let gs = M.games.slice().reverse(); if (t) gs = gs.filter((g) => g.home === t || g.away === t);
    let h = '<div class="toolbar"><label class="f grow">Team<select id="g-team">' + opt('', 'All teams', !t) + M.teams.map((x) => x.name).sort().map((n) => opt(n, n, n === t)).join('') + '</select></label><span class="count">' + gs.length + ' games</span></div><div class="glist">';
    for (const g of gs.slice(0, 150)) {
      h += '<details class="gitem" data-gid="' + esc(g.id) + '"><summary><span class="gd">' + esc(fmtShort.format(new Date(g.date))) + '</span><span class="gt ' + (g.as > g.hs ? 'w' : '') + '"><span>' + esc(g.away) + '</span><b>' + g.as + '</b></span><span class="gt ' + (g.hs > g.as ? 'w' : '') + '"><span>' + esc(g.home) + '</span><b>' + g.hs + '</b></span><span class="gx">' + esc(g.extra) + '</span></summary><div class="gbody"></div></details>';
    }
    return h + '</div>';
  }
  function gameDetail(M, gid) {
    const g = M.games.find((x) => x.id === gid); const tr = M.teamRows.filter((r) => r.game_id === gid); if (!g || tr.length < 2) return '<p class="empty">No details.</p>';
    const a = tr.find((r) => r.team === g.away), b = tr.find((r) => r.team === g.home);
    const nfl = M.sp === 'nfl';
    const stats = nfl ? [['Total yards', 'total_yards'], ['Pass yards', 'pass_yds'], ['Rush yards', 'rush_yds'], ['First downs', 'first_downs'], ['Turnovers', 'turnovers'], ['Sacks taken', 'sacks_taken'], ['Penalties', 'penalties'], ['Time of possession', 'poss_min']] : [['Shots', 'shots'], ['Hits', 'hits'], ['Blocked shots', 'blocks'], ['Takeaways', 'takeaways'], ['Giveaways', 'giveaways'], ['Power-play goals', 'pp_goals'], ['Power-play chances', 'pp_opps'], ['Faceoff %', 'faceoff_pct'], ['Penalty minutes', 'pim']];
    let h = '<div class="tscroll"><table class="data cmp"><thead><tr><th>' + esc(g.away) + '</th><th></th><th>' + esc(g.home) + '</th></tr></thead><tbody>' + stats.map(([l, k]) => '<tr><td class="n">' + esc(a[k]) + '</td><td class="mid">' + l + '</td><td class="n">' + esc(b[k]) + '</td></tr>').join('') + '</tbody></table></div>';
    const pr = M.playerRows.filter((r) => r.game_id === gid);
    const top = (team) => {
      const rows = pr.filter((r) => r.team === team);
      const score = (r) => nfl ? (r.pass_yds || 0) * 0.5 + (r.rush_yds || 0) + (r.rec_yds || 0) + 25 * (r.tot_td || 0) : (r.goals || 0) * 4 + (r.assists || 0) * 2 + (r.shots || 0) * 0.3 + (r.saves || 0) * 0.15;
      return rows.sort((x, y) => score(y) - score(x)).slice(0, 4).map((r) => {
        const parts = nfl ? [r.pass_yds ? r.pass_cmp + '/' + r.pass_att + ', ' + r.pass_yds + ' pass yds' + (r.pass_td ? ', ' + r.pass_td + ' TD' : '') : '', r.rush_att ? r.rush_att + ' car, ' + r.rush_yds + ' yds' : '', r.rec ? r.rec + ' rec, ' + r.rec_yds + ' yds' : '', r.tot_td ? r.tot_td + ' TD' : ''] : [r.pos === 'G' ? r.saves + ' saves on ' + r.shots_against : r.goals + ' G, ' + r.assists + ' A, ' + r.shots + ' shots'];
        return '<li><b>' + esc(r.name) + '</b> ' + esc(parts.filter(Boolean).join(' | ')) + '</li>';
      }).join('');
    };
    h += '<div class="perf"><div><h3>' + esc(g.away) + '</h3><ul>' + top(g.away) + '</ul></div><div><h3>' + esc(g.home) + '</h3><ul>' + top(g.home) + '</ul></div></div>';
    if (g.spread || g.ou !== '') h += '<p class="note">Closing market: ' + esc(g.spread || '') + (g.ou !== '' ? ' &middot; total ' + esc(g.ou) : '') + '. ' + (nfl ? 'Result vs total: ' + (g.hs + g.as) : '') + '</p>';
    return h;
  }

  /* ---------- shell ---------- */
  function render() {
    const view = $('#view'); const sp = S.sp;
    document.documentElement.setAttribute('data-sport', sp);
    document.querySelectorAll('.sp [data-sp]').forEach((b) => { b.classList.toggle('on', b.dataset.sp === sp); b.setAttribute('aria-pressed', b.dataset.sp === sp); });
    renderTabs();
    const fn = { slate: renderSlate, props: renderProps, lab: renderLab, parlay: renderParlay, teams: renderTeams, players: renderPlayers, games: renderGames, track: renderTrack, acc: renderAcc }[S.tab];
    try { view.innerHTML = fn(); } catch (err) { view.innerHTML = '<p class="empty err">Something went wrong drawing this section (' + esc(err.message) + '). Try another tab or reload.</p>'; if (window.console) console.error(err); }
    if (S.tab === 'lab') updateLabResults();
    if (S.tab === 'parlay') updateParlaySummary();
    renderSlip();
    const m = S.meta[sp];
    $('#fresh').textContent = m ? m.games + ' games through ' + fmtShort.format(new Date(m.last + 'T12:00:00Z')) + ' (' + sp.toUpperCase() + ')' : '';
  }
  const PALETTES = { ice: 'Ice', ember: 'Ember', royal: 'Royal', rose: 'Rose' };
  function setPalette(name, announce) {
    if (!PALETTES[name]) name = 'ice';
    document.documentElement.setAttribute('data-palette', name);
    document.querySelectorAll('[data-pal]').forEach((b) => { const on = b.dataset.pal === name; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });
    store.set('ss-pal', name);
    if (announce) flash(PALETTES[name] + ' color scheme');
  }
  function renderTabs() {
    $('#tabs').innerHTML = TABS.map(([k, l]) => '<button type="button" data-tab="' + k + '" class="' + (S.tab === k ? 'on' : '') + '" role="tab" aria-selected="' + (S.tab === k) + '">' + l + (k === 'parlay' && S.parlay.length ? ' <span class="count-pill">' + S.parlay.length + '</span>' : '') + '</button>').join('');
  }
  function handleAdd(ad) {
    const d = ad.dataset; const kind = d.add; let ok = false;
    if (kind === 'win') ok = addLeg({ kind, sp: d.sp, gameId: d.game, team: d.team });
    else if (kind === 'spread') ok = addLeg({ kind, sp: d.sp, gameId: d.game, team: d.team, line: parseFloat(d.line) });
    else if (kind === 'total') ok = addLeg({ kind, sp: d.sp, gameId: d.game, side: d.side, line: parseFloat(d.line) });
    else if (kind === 'prop') ok = addLeg({ kind, sp: d.sp, gameId: d.game, pid: d.pid, key: d.key, side: 'over', line: d.line != null ? parseFloat(d.line) : undefined, ms: d.ms != null ? +d.ms : null });
    else if (kind === 'lab' || kind === 'labprop') {
      const L = S.lab[S.sp]; if (!L) return; const g = labGame(); const gameId = g.game_id || ('custom:' + g.away + '@' + g.home);
      if (kind === 'lab') {
        const line = parseFloat(L.line); if (L.btype !== 'win' && isNaN(line)) { flash('Enter a line first.'); return; }
        ok = addLeg({ kind: L.btype, sp: S.sp, gameId, home: g.home, away: g.away, team: L.team, side: L.side, line, odds: L.odds });
      } else {
        const def = K.PROPS[S.sp][L.ptype]; const line = def.anytime ? 0.5 : parseFloat(L.pline); if (isNaN(line)) { flash('Enter a line first.'); return; }
        ok = addLeg({ kind: 'prop', sp: S.sp, gameId, home: g.home, away: g.away, pid: L.pid, key: L.ptype, side: L.pside, line, odds: L.podds });
      }
    }
    if (ok) { renderTabs(); renderSlip(); if (S.tab === 'parlay') render(); }
  }
  function setHash() { try { history.replaceState(null, '', '#' + S.sp + '-' + S.tab); } catch (e) { /* ignore */ } }
  function readHash() { const m = (location.hash || '').replace('#', '').match(/^(nfl|nhl)-(slate|props|lab|parlay|teams|players|games|track|acc)$/); if (m) { S.sp = m[1]; S.tab = m[2]; return true; } return false; }
  function go(sp, tab) { S.sp = sp || S.sp; S.tab = tab || S.tab; store.set('kc-sp', S.sp); setHash(); render(); window.scrollTo(0, 0); }

  function bind() {
    document.addEventListener('click', (e) => {
      const t = e.target;
      const b1 = t.closest('.sp [data-sp]'); if (b1) return go(b1.dataset.sp, null);
      const pb = t.closest('[data-pal]'); if (pb) return setPalette(pb.dataset.pal, true);
      const b2 = t.closest('[data-tab]'); if (b2) return go(null, b2.dataset.tab);
      const ad = t.closest('[data-add]'); if (ad) { e.preventDefault(); return handleAdd(ad); }
      const rm = t.closest('[data-rm]'); if (rm) { S.parlay.splice(+rm.dataset.rm, 1); saveParlay(); return render(); }
      if (t.closest('#pl-clear')) { S.parlay = []; saveParlay(); return render(); }
      const card = t.closest('[data-game]'); if (card) { const L = S.lab[S.sp] || (S.lab[S.sp] = labDefaults()); L.gameId = card.dataset.game; L.btype = 'win'; L.line = ''; L.team = ''; L.pteam = ''; return go(null, 'lab'); }
      const th = t.closest('th[data-k]'); if (th) { const id = th.closest('table').dataset.tid; const cur = S.players.sort[id] || {}; const numeric = th.classList.contains('n'); S.players.sort[id] = { key: th.dataset.k, dir: cur.key === th.dataset.k ? (cur.dir === 'desc' ? 'asc' : 'desc') : (numeric ? 'desc' : 'asc') }; return render(); }
      const cb = t.closest('[data-cat]'); if (cb) { S.players.cat[S.sp] = cb.dataset.cat; S.players.sel = null; return render(); }
      const pr = t.closest('tr[data-pid]'); if (pr) { S.players.sel = pr.dataset.pid; render(); window.scrollTo(0, 0); return; }
      if (t.closest('#p-close')) { S.players.sel = null; return render(); }
    });
    document.addEventListener('keydown', (e) => { if ((e.key === 'Enter' || e.key === ' ') && e.target.dataset && e.target.dataset.game) { e.preventDefault(); e.target.click(); } });
    document.addEventListener('toggle', (e) => { const d = e.target; if (d.classList && d.classList.contains('gitem') && d.open) { const body = d.querySelector('.gbody'); if (!body.dataset.done) { body.innerHTML = gameDetail(S.M[S.sp], d.dataset.gid); body.dataset.done = '1'; } } }, true);
    document.addEventListener('input', (e) => {
      const id = e.target.id; const L = S.lab[S.sp];
      if (id === 'pr-q') { const F = S.props && S.props[S.sp]; if (F) F.q = e.target.value; const pos = e.target.selectionStart; render(); const el = $('#pr-q'); if (el) { el.focus(); el.setSelectionRange(pos, pos); } return; }
      if (id === 'p-q') { S.players.q = e.target.value; const pos = e.target.selectionStart; render(); const el = $('#p-q'); if (el) { el.focus(); el.setSelectionRange(pos, pos); } return; }
      if (e.target.dataset && e.target.dataset.legOdds != null) { const i = +e.target.dataset.legOdds; if (S.parlay[i]) { S.parlay[i].odds = e.target.value; saveParlay(); updateParlaySummary(); } return; }
      if (!L) return;
      const num = { 'lab-line': 'line', 'lab-odds': 'odds', 'lab-pline': 'pline', 'lab-podds': 'podds' }[id];
      if (num) { L[num] = e.target.value; updateLabResults(); }
    });
    document.addEventListener('change', (e) => {
      const id = e.target.id; const v = e.target.value; const sp = S.sp; const L = S.lab[sp];
      if (id === 'g-team') { S.games.team = v; return render(); }
      if (id === 'pr-key' || id === 'pr-game' || id === 'pr-min' || id === 'pr-team') { const F = S.props[sp]; if (F) { if (id === 'pr-key') F.key = v; else if (id === 'pr-game') { F.game = v; F.team = ''; } else if (id === 'pr-team') F.team = v; else F.min = +v; } return render(); }
      if (!L) return;
      const map = { 'lab-game': 'gameId', 'lab-away': 'away', 'lab-home': 'home', 'lab-btype': 'btype', 'lab-team': 'team', 'lab-side': 'side', 'lab-pteam': 'pteam', 'lab-ptype': 'ptype', 'lab-pid': 'pid', 'lab-pside': 'pside' };
      if (!map[id]) return; L[map[id]] = v;
      if (id === 'lab-game') { L.team = ''; L.pteam = ''; L.line = ''; L.pid = ''; }
      if (id === 'lab-btype' && v !== 'win') { const gm = K.gameModel(S.M[sp], labGame()); L.line = ''; const mk = gm.mktMargin; if (v === 'spread' && sp === 'nfl' && mk != null) L.line = String(L.team === gm.home ? -mk : mk); if (v === 'total' && gm.mktTotal != null) L.line = String(gm.mktTotal); if (v === 'spread' && sp === 'nhl') L.line = L.team === gm.home ? '-1.5' : '1.5'; }
      if (id === 'lab-team' && L.btype === 'spread') { const gm = K.gameModel(S.M[sp], labGame()); if (sp === 'nfl' && gm.mktMargin != null) L.line = String(L.team === gm.home ? -gm.mktMargin : gm.mktMargin); if (sp === 'nhl') L.line = L.team === gm.home ? '-1.5' : '1.5'; }
      if (id === 'lab-ptype') { L.pid = ''; L.pline = ({ rec_yds: 55.5, rec: 4.5, rush_yds: 49.5, pass_yds: 249.5, pass_td: 1.5, rushrec_yds: 65.5, shots: 2.5, points: 0.5, saves: 25.5 })[v] || 0.5; }
      if (id === 'lab-pteam') L.pid = '';
      render();
    });
    window.addEventListener('hashchange', () => { if (readHash()) render(); });
  }

  async function start() {
    setPalette(store.get('ss-pal') || 'ember', false);
    try { await loadAll(); } catch (err) { $('#view').innerHTML = '<p class="empty err">The data files did not load (' + esc(err.message) + '). Reload the page to try again.</p>'; return; }
    loadParlay();
    if (!readHash()) { const sv = store.get('kc-sp'); if (sv === 'nfl' || sv === 'nhl') S.sp = sv; }
    bind(); setHash(); render();
  }
  start();
})();
