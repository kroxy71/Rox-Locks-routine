/* Sharp Sheet - model.js
   Pure functions, no DOM access. Runs in a browser, a PWA or Node (module.exports).
   Every probability here is an estimate from this season's games, not a guarantee. */
(function (root) {
  'use strict';

  /* ---------- math helpers ---------- */
  function erf(x) {
    const s = x < 0 ? -1 : 1; x = Math.abs(x);
    const t = 1 / (1 + 0.3275911 * x);
    const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
    return s * y;
  }
  const Phi = (z) => 0.5 * (1 + erf(z / Math.SQRT2));
  function pois(k, l) { let p = Math.exp(-l); for (let i = 1; i <= k; i++) p *= l / i; return p; }
  function poisCdf(k, l) { if (k < 0) return 0; let s = 0; for (let i = 0; i <= k; i++) s += pois(i, l); return Math.min(1, s); }
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  // negative binomial: counts that vary more than a plain average implies (receptions, shots, saves)
  function lgamma(x) {
    const c = [0.99999999999980993, 676.5203681218851, -1259.1392167224028, 771.32342877765313, -176.61502916214059, 12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
    if (x < 0.5) return Math.log(Math.PI / Math.sin(Math.PI * x)) - lgamma(1 - x);
    x -= 1; let a = c[0]; const t = x + 7.5; for (let i = 1; i < 9; i++) a += c[i] / (x + i);
    return 0.5 * Math.log(2 * Math.PI) + (x + 0.5) * Math.log(t) - t + Math.log(a);
  }
  function nbPmf(k, mu, r) { const p = r / (r + mu); return Math.exp(lgamma(k + r) - lgamma(r) - lgamma(k + 1) + r * Math.log(p) + k * Math.log(1 - p)); }
  function nbCdf(k, mu, r) { if (k < 0) return 0; let s = 0; for (let i = 0; i <= k; i++) s += nbPmf(i, mu, r); return Math.min(1, s); }
  const mean = (a) => a.length ? a.reduce((s, x) => s + x, 0) / a.length : 0;
  function sd(a) { if (a.length < 2) return 0; const m = mean(a); return Math.sqrt(a.reduce((s, x) => s + (x - m) * (x - m), 0) / (a.length - 1)); }
  function amToProb(a) { a = +a; if (!a) return null; return a < 0 ? -a / (-a + 100) : 100 / (a + 100); }
  function probToAm(p) { if (p <= 0 || p >= 1) return null; return p >= 0.5 ? Math.round(-100 * p / (1 - p)) : Math.round(100 * (1 - p) / p); }
  const pct = (p, d) => (100 * p).toFixed(d == null ? 0 : d) + '%';
  // prop calibration fitted from the Nov 2 walk-forward backtest (NFL + NHL, about 42,000 props):
  // raw chances in the 40-85% range ran 5-8 points high, so pull them in on the log-odds scale
  const CAL = { a: -0.15, b: 0.88 };
  function calibrate(p) { p = clamp(p, 1e-4, 1 - 1e-4); const l = Math.log(p / (1 - p)); return 1 / (1 + Math.exp(-(CAL.b * l + CAL.a))); }

  /* ---------- CSV ---------- */
  const STRING_KEYS = new Set(['game_id', 'player_id', 'date', 'name', 'team', 'opp', 'home', 'away', 'home_abbr', 'away_abbr', 'pos', 'sport', 'extra', 'spread_detail', 'venue', 'abbr', 'color', 'alt', 'status', 'comment', 'home_goalie', 'away_goalie', 'home_status', 'away_status']);
  function parseCSV(text) {
    const rows = []; let row = [], f = '', q = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (q) { if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c; }
      else if (c === '"') q = true;
      else if (c === ',') { row.push(f); f = ''; }
      else if (c === '\n') { row.push(f); rows.push(row); row = []; f = ''; }
      else if (c !== '\r') f += c;
    }
    if (f !== '' || row.length) { row.push(f); rows.push(row); }
    const head = rows.shift() || [];
    return rows.filter((r) => r.length === head.length).map((r) => {
      const o = {};
      head.forEach((h, i) => { const v = r[i]; o[h] = (!STRING_KEYS.has(h) && v !== '' && !isNaN(v)) ? +v : v; });
      return o;
    });
  }

  function normName(s) { return String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z]/g, ''); }
  // how a named starting goalie changes the goals his team allows, vs the team's usual goaltending
  function goalieFactor(M, team, name) {
    if (!name || !M.goalieSv) return { f: 1, info: null };
    const g = M.goalieSv[normName(name) + '|' + team]; const t = M.teamSv[team];
    if (!g || !t) return { f: 1, info: { name, known: false } };
    return { f: clamp((1 - g.sv) / (1 - t), 0.85, 1.15), info: { name: g.name, known: true, sv: g.sv, teamSv: t, sa: g.sa } };
  }

  /* ---------- team ratings: ridge-regularised offence/defence ---------- */
  function fitRatings(games, cfg) {
    const teams = {};
    const T = (n) => teams[n] || (teams[n] = { name: n, gp: 0, pf: 0, pa: 0, w: 0, l: 0, otl: 0, list: [] });
    let tot = 0, hm = 0;
    for (const g of games) {
      const h = T(g.home), a = T(g.away);
      h.gp++; a.gp++; h.pf += g.hs; h.pa += g.as; a.pf += g.as; a.pa += g.hs; tot += g.hs + g.as; hm += g.hs - g.as;
      h.list.push({ opp: g.away, pf: g.hs, pa: g.as, home: 1 }); a.list.push({ opp: g.home, pf: g.as, pa: g.hs, home: 0 });
      if (g.hs > g.as) { h.w++; if (g.extra) a.otl++; else a.l++; } else { a.w++; if (g.extra) h.otl++; else h.l++; }
    }
    const n = games.length || 1;
    const mu = tot / (2 * n);
    const hfa = ((hm / n) / 2 * n + cfg.hfaPrior * cfg.hfaK) / (n + cfg.hfaK);
    const names = Object.keys(teams);
    names.forEach((k) => { teams[k].off = 0; teams[k].def = 0; });
    for (let it = 0; it < 80; it++) {
      for (const k of names) {
        const t = teams[k]; let so = 0, sdf = 0;
        for (const e of t.list) {
          const o = teams[e.opp];
          so += e.pf - mu - o.def - (e.home ? hfa : -hfa);
          sdf += e.pa - mu - o.off + (e.home ? hfa : -hfa);
        }
        t.off = so / (t.list.length + cfg.lam); t.def = sdf / (t.list.length + cfg.lam);
      }
    }
    let ss = 0;
    for (const g of games) {
      const ph = mu + teams[g.home].off + teams[g.away].def + hfa, pa = mu + teams[g.away].off + teams[g.home].def - hfa;
      ss += ((g.hs - g.as) - (ph - pa)) ** 2;
    }
    const residSdMargin = Math.sqrt(ss / Math.max(1, n)) * 1.08;
    return { teams, mu, hfa, n, residSdMargin };
  }
  function predictScores(R, home, away) {
    const h = R.teams[home], a = R.teams[away];
    return { hs: R.mu + (h ? h.off : 0) + (a ? a.def : 0) + R.hfa, as: R.mu + (a ? a.off : 0) + (h ? h.def : 0) - R.hfa };
  }

  /* ---------- build a sport model from the three CSV tables ---------- */
  const CFG = {
    // wMarket raised to 0.85 after the Nov 2 backtest: the market alone beat a 60/40 blend on winners and totals
    nfl: { lam: 4, hfaPrior: 1.0, hfaK: 60, sdMargin: 13.4, sdTotal: 10.3, wMarket: 0.85 },
    nhl: { lam: 7, hfaPrior: 0.07, hfaK: 150, wMarket: 0.85 }
  };

  function buildSport(sp, gamesRows, teamRows, playerRows) {
    const cfg = CFG[sp];
    const games = gamesRows.map((r) => ({ id: r.game_id, date: r.date, week: r.week, home: r.home, away: r.away, homeAbbr: r.home_abbr, awayAbbr: r.away_abbr, hs: r.home_score, as: r.away_score, extra: r.extra, spread: r.spread_detail, ou: r.over_under, homeMl: r.home_ml, awayMl: r.away_ml, venue: r.venue }));
    games.sort((a, b) => (a.date < b.date ? -1 : 1));
    const M = { sp, cfg, games, teamRows, playerRows, abbr: {} };
    games.forEach((g) => { M.abbr[g.home] = g.homeAbbr; M.abbr[g.away] = g.awayAbbr; });
    M.goals = fitRatings(games, cfg);
    if (sp === 'nhl') {
      const sh = {}; teamRows.forEach((t) => { sh[t.game_id + '|' + t.team] = t.shots; });
      const sg = games.map((g) => ({ home: g.home, away: g.away, hs: sh[g.id + '|' + g.home] || 0, as: sh[g.id + '|' + g.away] || 0, extra: '' }));
      M.shots = fitRatings(sg, { lam: 7, hfaPrior: 0.5, hfaK: 150 });
      const tg = games.reduce((s, g) => s + g.hs + g.as, 0), ts = sg.reduce((s, g) => s + g.hs + g.as, 0);
      M.gpShot = tg / Math.max(1, ts);
    } else {
      M.sdMargin = Math.sqrt((M.goals.n * M.goals.residSdMargin ** 2 + 120 * cfg.sdMargin ** 2) / (M.goals.n + 120));
      const tot = games.map((g) => g.hs + g.as); const mt = mean(tot);
      M.sdTotal = Math.sqrt((M.goals.n * (sd(tot) * 0.95) ** 2 + 120 * cfg.sdTotal ** 2) / (M.goals.n + 120));
      M.meanTotal = mt;
    }
    // team records / per-game
    M.teams = Object.values(M.goals.teams).map((t) => ({ name: t.name, gp: t.gp, w: t.w, l: t.l, otl: t.otl, pf: t.pf, pa: t.pa, pfg: t.pf / t.gp, pag: t.pa / t.gp, off: t.off, def: t.def, net: t.off - t.def }));
    M.teams.sort((a, b) => b.net - a.net);
    M.teams.forEach((t, i) => { t.rank = i + 1; });
    M.teamIdx = {}; M.teams.forEach((t) => { M.teamIdx[t.name] = t; });
    // players
    const P = {};
    for (const r of playerRows) {
      const p = P[r.player_id] || (P[r.player_id] = { id: r.player_id, name: r.name, team: r.team, pos: r.pos, rows: [] });
      p.rows.push(r); p.team = r.team; if (r.pos) p.pos = r.pos;
    }
    Object.values(P).forEach((p) => p.rows.sort((a, b) => (a.date < b.date ? 1 : -1))); // newest first
    M.players = P;
    M.teamGames = {}; M.teams.forEach((t) => { M.teamGames[t.name] = t.gp; });
    if (sp === 'nfl') {
      let ra = 0, rt = 0, tg = 0, tt = 0;
      playerRows.forEach((r) => { ra += r.rush_att || 0; rt += r.rush_td || 0; tg += r.targets || 0; tt += r.rec_td || 0; });
      M.rTdPerAtt = rt / Math.max(1, ra); M.cTdPerTgt = tt / Math.max(1, tg);
    } else {
      const f = { g: 0, s: 0 }, d = { g: 0, s: 0 };
      playerRows.forEach((r) => { if (r.pos === 'G') return; const o = r.pos === 'D' ? d : f; o.g += r.goals || 0; o.s += r.shots || 0; });
      M.shF = f.g / Math.max(1, f.s); M.shD = d.g / Math.max(1, d.s);
      // goalie save percentages (shrunk toward the league) and each team's blended goalie save percentage
      let lsv = 0, lsa = 0; const gk = {}, tm = {};
      playerRows.forEach((r) => {
        if (r.pos !== 'G' || !(r.shots_against > 0)) return;
        lsv += r.saves || 0; lsa += r.shots_against;
        const k = normName(r.name) + '|' + r.team; const o = gk[k] || (gk[k] = { name: r.name, team: r.team, sv: 0, sa: 0 }); o.sv += r.saves || 0; o.sa += r.shots_against;
        const t = tm[r.team] || (tm[r.team] = { sv: 0, sa: 0 }); t.sv += r.saves || 0; t.sa += r.shots_against;
      });
      M.lgSv = lsa ? lsv / lsa : 0.9; const K0 = 400;
      M.goalieSv = {}; Object.keys(gk).forEach((k) => { const o = gk[k]; M.goalieSv[k] = { name: o.name, sa: o.sa, sv: (o.sv + K0 * M.lgSv) / (o.sa + K0) }; });
      M.teamSv = {}; Object.keys(tm).forEach((k) => { const o = tm[k]; M.teamSv[k] = (o.sv + K0 * M.lgSv) / (o.sa + K0); });
    }
    return M;
  }

  /* ---------- game-level probabilities ---------- */
  function parseSpread(detail, homeAbbr, awayAbbr) { // returns home margin implied by market (home favoured => positive)
    if (!detail) return null;
    if (/^even$/i.test(detail.trim())) return 0;
    const m = detail.match(/^([A-Z]+)\s+([+-]?\d+(\.\d+)?)/);
    if (!m) return null;
    const v = Math.abs(parseFloat(m[2]));
    if (m[1] === homeAbbr) return v; if (m[1] === awayAbbr) return -v; return null;
  }

  function nhlLambdas(M, home, away) {
    const g = predictScores(M.goals, home, away), s = predictScores(M.shots, home, away);
    return { lh: 0.5 * g.hs + 0.5 * s.hs * M.gpShot, la: 0.5 * g.as + 0.5 * s.as * M.gpShot, goalsOnly: g, shotsOnly: s };
  }
  function nhlGrid(lh, la, N) {
    N = N || 14;
    const ph = [], pa = [];
    for (let i = 0; i <= N; i++) { ph.push(pois(i, lh)); pa.push(pois(i, la)); }
    return { ph, pa, N };
  }

  function gameModel(M, game) {
    const out = { sp: M.sp, home: game.home, away: game.away, notes: [] };
    const hAbbr = game.homeAbbr || game.home_abbr || M.abbr[game.home], aAbbr = game.awayAbbr || game.away_abbr || M.abbr[game.away];
    const spreadTxt = game.spread || game.spread_detail, ouLine = game.ou != null ? game.ou : game.over_under;
    const homeMl = game.homeMl != null ? game.homeMl : game.home_ml, awayMl = game.awayMl != null ? game.awayMl : game.away_ml;
    const th = M.teamIdx[game.home], ta = M.teamIdx[game.away];
    out.th = th; out.ta = ta;
    if (M.sp === 'nfl') {
      const s = predictScores(M.goals, game.home, game.away);
      out.hs = s.hs; out.as = s.as;
      out.modelMargin = s.hs - s.as; out.modelTotal = s.hs + s.as;
      const mk = parseSpread(spreadTxt, hAbbr, aAbbr);
      out.mktMargin = mk; out.mktTotal = (ouLine === '' || ouLine == null) ? null : +ouLine;
      const w = mk == null ? 0 : M.cfg.wMarket;
      out.margin = w * (mk || 0) + (1 - w) * out.modelMargin;
      out.total = (out.mktTotal == null ? out.modelTotal : M.cfg.wMarket * out.mktTotal + (1 - M.cfg.wMarket) * out.modelTotal);
      out.sdMargin = M.sdMargin; out.sdTotal = M.sdTotal;
      out.homeWin = Phi(out.margin / out.sdMargin);
      out.modelHomeWin = Phi(out.modelMargin / out.sdMargin);
      out.mktHomeWin = mk == null ? null : Phi(mk / M.cfg.sdMargin);
      out.hsB = (out.total + out.margin) / 2; out.asB = (out.total - out.margin) / 2;
      out.wMarket = w;
    } else {
      const L = nhlLambdas(M, game.home, game.away);
      // starting goalies: the away goalie affects home goals and vice versa
      const gh = goalieFactor(M, game.home, game.home_goalie), ga = goalieFactor(M, game.away, game.away_goalie);
      L.lh *= ga.f; L.la *= gh.f;
      out.goalies = { home: gh.info, away: ga.info, homeStatus: game.home_goalie_status || '', awayStatus: game.away_goalie_status || '', homeF: gh.f, awayF: ga.f };
      out.lh = L.lh; out.la = L.la; out.hs = L.lh; out.as = L.la;
      out.modelMargin = L.lh - L.la; out.modelTotal = L.lh + L.la;
      const G = nhlGrid(L.lh, L.la); out.grid = G;
      let pH = 0, pA = 0, pT = 0;
      for (let i = 0; i <= G.N; i++) for (let j = 0; j <= G.N; j++) { const p = G.ph[i] * G.pa[j]; if (i > j) pH += p; else if (j > i) pA += p; else pT += p; }
      const otHome = 0.5 + 0.01;
      out.regTie = pT; out.modelHomeWin = pH + pT * otHome; out.modelAwayWin = pA + pT * (1 - otHome);
      const ph = amToProb(homeMl), pa = amToProb(awayMl);
      if (ph && pa) { out.mktHomeWin = ph / (ph + pa); out.mktAwayWin = pa / (ph + pa); out.vig = ph + pa - 1; }
      const w = out.mktHomeWin == null ? 0 : M.cfg.wMarket;
      out.homeWin = w * (out.mktHomeWin || 0) + (1 - w) * out.modelHomeWin;
      out.wMarket = w;
      out.mktTotal = (ouLine === '' || ouLine == null) ? null : +ouLine;
      out.total = out.mktTotal == null ? out.modelTotal : M.cfg.wMarket * out.mktTotal + (1 - M.cfg.wMarket) * out.modelTotal;
      out.margin = out.modelMargin;
    }
    out.awayWin = 1 - out.homeWin;
    return out;
  }

  /* bets: {type:'win', team} | {type:'spread', team, line} | {type:'total', side:'over'|'under', line} */
  function betProb(M, gm, bet) {
    const res = { p: null, push: 0, why: [] };
    const isHome = bet.team === gm.home;
    if (bet.type === 'win') {
      res.p = isHome ? gm.homeWin : gm.awayWin;
    } else if (M.sp === 'nfl') {
      if (bet.type === 'spread') {
        const m = isHome ? gm.margin : -gm.margin; // team's expected margin
        const need = -bet.line; // team margin must exceed -line
        const wholeLine = Number.isInteger(bet.line);
        if (wholeLine) {
          res.p = 1 - Phi((need + 0.5 - m) / gm.sdMargin); res.push = Phi((need + 0.5 - m) / gm.sdMargin) - Phi((need - 0.5 - m) / gm.sdMargin);
        } else res.p = 1 - Phi((need - m) / gm.sdMargin);
      } else {
        const wholeLine = Number.isInteger(bet.line);
        const over = wholeLine ? 1 - Phi((bet.line + 0.5 - gm.total) / gm.sdTotal) : 1 - Phi((bet.line - gm.total) / gm.sdTotal);
        const under = wholeLine ? Phi((bet.line - 0.5 - gm.total) / gm.sdTotal) : 1 - over;
        res.push = wholeLine ? 1 - over - under : 0;
        res.p = bet.side === 'over' ? over : under;
      }
    } else {
      const G = gm.grid;
      if (bet.type === 'spread') {
        // puck line: margin includes the OT/shootout winner by exactly one goal
        let pm = {}; const otH = 0.51;
        for (let i = 0; i <= G.N; i++) for (let j = 0; j <= G.N; j++) {
          const p = G.ph[i] * G.pa[j]; let d = i - j;
          if (d === 0) { pm[1] = (pm[1] || 0) + p * otH; pm[-1] = (pm[-1] || 0) + p * (1 - otH); } else pm[d] = (pm[d] || 0) + p;
        }
        let pc = 0; const t = isHome ? 1 : -1;
        for (const k of Object.keys(pm)) { const d = t * +k; if (d + bet.line > 0) pc += pm[k]; else if (d + bet.line === 0) res.push += pm[k]; }
        res.p = pc;
      } else {
        // scale both teams' expected goals so their sum matches the market-blended total
        const kk = gm.total / (gm.lh + gm.la); const G2 = Math.abs(kk - 1) < 1e-6 ? G : nhlGrid(gm.lh * kk, gm.la * kk);
        const lam = gm.total; const otGoal = 0.55;
        // distribution of regulation total ~ Poisson(lh+la); a tie adds one goal with prob otGoal
        let over = 0, under = 0, push = 0;
        for (let k = 0; k <= 30; k++) {
          const p = pois(k, lam);
          const tieShare = 0; // approximate: tie probability is concentrated at even totals
          let pk = p;
          const sub = [{ tot: k, pr: pk }];
          // spread tie mass at even k onto k+1
          if (k % 2 === 0) {
            const tieMass = (() => { let s = 0; const half = k / 2; if (half <= G2.N) s = G2.ph[half] * G2.pa[half]; return s; })();
            sub[0] = { tot: k, pr: pk - tieMass * otGoal }; sub.push({ tot: k + 1, pr: tieMass * otGoal });
          }
          for (const s of sub) {
            if (s.tot > bet.line) over += s.pr; else if (s.tot < bet.line) under += s.pr; else push += s.pr;
          }
        }
        res.push = push; res.p = bet.side === 'over' ? over : under;
      }
    }
    if (res.p != null) res.p = clamp(res.p, 0.005, 0.995);
    return res;
  }

  /* ---------- player props ---------- */
  function weightedStats(vals, decay) {
    let sw = 0, sx = 0; vals.forEach((v, i) => { const w = Math.pow(decay, i); sw += w; sx += w * v; });
    return sw ? sx / sw : 0;
  }
  function playedNfl(r) { return (r.pass_att || 0) > 0 || (r.rush_att || 0) > 0 || (r.targets || 0) > 0 || (r.rec || 0) > 0 || (r.tot_td || 0) > 0; }

  function envFactor(M, gm, team) {
    if (!gm) return 1;
    const own = team === gm.home ? (M.sp === 'nfl' ? gm.hsB : gm.lh) : (M.sp === 'nfl' ? gm.asB : gm.la);
    const t = M.teamIdx[team]; if (!t || !own) return 1;
    return clamp(own / t.pfg, 0.72, 1.4);
  }
  function oppEnv(M, gm, team) { // how much the opponent scores relative to its season average (drives goalie saves etc.)
    if (!gm) return 1;
    const opp = team === gm.home ? gm.away : gm.home;
    return envFactor(M, gm, opp);
  }

  const PROPS = {
    nfl: {
      atd: { label: 'Anytime touchdown', short: 'Anytime TD', anytime: true },
      rec_yds: { label: 'Receiving yards', sd: 18, cv: 0.55, count: false },
      rec: { label: 'Receptions', count: true, r: 6 },
      rush_yds: { label: 'Rushing yards', sd: 14, cv: 0.5, count: false },
      pass_yds: { label: 'Passing yards', sd: 55, cv: 0.3, count: false },
      pass_td: { label: 'Passing touchdowns', count: true, r: 8 },
      rushrec_yds: { label: 'Rush + receiving yards', sd: 20, cv: 0.45, count: false }
    },
    nhl: {
      atg: { label: 'Anytime goal', short: 'Anytime goal', anytime: true },
      shots: { label: 'Shots on goal', count: true, r: 6 },
      points: { label: 'Points (goals + assists)', count: true, r: 12 },
      saves: { label: 'Goalie saves', count: true, r: 14 }
    }
  };
  function statVal(sp, key, r) {
    if (sp === 'nfl') { if (key === 'rushrec_yds') return (r.rush_yds || 0) + (r.rec_yds || 0); if (key === 'atd') return r.tot_td || 0; return r[key] || 0; }
    if (key === 'points') return (r.goals || 0) + (r.assists || 0); if (key === 'atg') return r.goals || 0; return r[key] || 0;
  }
  function eligibleRows(sp, p) { return sp === 'nfl' ? p.rows.filter(playedNfl) : p.rows.filter((r) => (r.toi || 0) > 0 || (r.shots || 0) > 0 || (r.saves || 0) > 0); }

  function propProb(M, p, key, side, line, gm) {
    const sp = M.sp, def = PROPS[sp][key];
    const rows = eligibleRows(sp, p); const n = rows.length;
    const res = { n, p: null, push: 0, mu: null, why: [], low: n < 4 };
    const gp = M.teamGames[p.team] || n;
    const env = envFactor(M, gm, p.team);
    if (key === 'atd') {
      const tds = rows.reduce((s, r) => s + (r.tot_td || 0), 0);
      const att = rows.reduce((s, r) => s + (r.rush_att || 0), 0), tg = rows.reduce((s, r) => s + (r.targets || 0), 0);
      const opp = n ? (att + tg) / n : 0;
      const prior = n ? (att / n) * M.rTdPerAtt + (tg / n) * M.cTdPerTgt : 0;
      const obs = n ? tds / n : 0; const w = n / (n + 10);
      const base = w * obs + (1 - w) * prior; const lam = clamp(base * env, 0, 1.6);
      res.raw = 1 - Math.exp(-lam); res.p = calibrate(res.raw); res.mu = lam;
      res.why.push(p.name + ' has ' + tds + ' touchdown' + (tds === 1 ? '' : 's') + ' in ' + n + ' game' + (n === 1 ? '' : 's') + ' (' + obs.toFixed(2) + ' per game) on ' + opp.toFixed(1) + ' carries plus targets per game.');
      res.why.push('Typical touchdown rates for that usage predict ' + prior.toFixed(2) + ' per game. The estimate blends the two (' + pct(w) + ' weight on his own results).');
      if (gm) res.why.push('Game environment: ' + p.team + ' projected for ' + (p.team === gm.home ? gm.hsB : gm.asB).toFixed(1) + ' points against a season average of ' + (M.teamIdx[p.team] ? M.teamIdx[p.team].pfg.toFixed(1) : '?') + ', which scales the rate by ' + env.toFixed(2) + '.');
      if (n < gp - 1) res.why.push('He appeared in ' + n + ' of ' + gp + ' team games, so injuries or role changes may matter more than the average shows.');
      res.why.push('Chance of at least one touchdown = 1 - e^(-' + lam.toFixed(2) + ') = ' + pct(res.raw, 1) + ', adjusted to ' + pct(res.p, 1) + ' using how past estimates like this actually performed.');
      return res;
    }
    if (key === 'atg') {
      const goals = rows.reduce((s, r) => s + (r.goals || 0), 0), shots = rows.reduce((s, r) => s + (r.shots || 0), 0);
      const prior = p.pos === 'D' ? M.shD : M.shF; const K = 80;
      const shp = (goals + K * prior) / (shots + K); const spg = n ? shots / n : 0;
      const lam = clamp(spg * shp * env, 0, 1.4);
      res.raw = 1 - Math.exp(-lam); res.p = calibrate(res.raw); res.mu = lam;
      res.why.push(p.name + ' has ' + goals + ' goal' + (goals === 1 ? '' : 's') + ' on ' + shots + ' shots in ' + n + ' game' + (n === 1 ? '' : 's') + ' (' + spg.toFixed(1) + ' shots per game).');
      res.why.push('His own shooting rate is pulled toward the league rate for ' + (p.pos === 'D' ? 'defensemen' : 'forwards') + ' (' + pct(prior, 1) + ') because a few weeks of shots is a small sample. Blended: ' + pct(shp, 1) + ' per shot.');
      if (gm) res.why.push('Game environment: ' + p.team + ' projected for ' + (p.team === gm.home ? gm.lh : gm.la).toFixed(2) + ' goals against a season average of ' + (M.teamIdx[p.team] ? M.teamIdx[p.team].pfg.toFixed(2) : '?') + ', a factor of ' + env.toFixed(2) + '.');
      res.why.push('Expected goals ' + lam.toFixed(2) + ', so the raw chance of at least one is ' + pct(res.raw, 1) + ', adjusted to ' + pct(res.p, 1) + ' using how past estimates like this actually performed. The opposing starting goalie is included when announced.');
      return res;
    }
    // over/under props
    const vals = rows.map((r) => statVal(sp, key, r)); // newest first
    const wm = weightedStats(vals, 0.9), season = mean(vals);
    let mult = 1; if (gm) { mult = key === 'saves' ? 1 + 0.6 * (oppEnv(M, gm, p.team) - 1) : 1 + 0.5 * (env - 1); }
    const mu = Math.max(0.01, (0.5 * wm + 0.5 * season) * mult); res.mu = mu;
    const isInt = Number.isInteger(line);
    let over, under, push = 0;
    if (def.count) {
      const k = Math.floor(line); const r = def.r || 30;
      over = 1 - nbCdf(k, mu, r);
      if (isInt) { push = nbPmf(k, mu, r); under = nbCdf(k - 1, mu, r); } else under = nbCdf(k, mu, r);
    } else {
      const s = Math.max(def.sd, sd(vals), (def.cv || 0) * mu) * Math.sqrt(1 + 1 / Math.max(1, n));
      if (isInt) { over = 1 - Phi((line + 0.5 - mu) / s); under = Phi((line - 0.5 - mu) / s); push = 1 - over - under; }
      else { over = 1 - Phi((line - mu) / s); under = 1 - over; }
      res.s = s;
    }
    const emp = (() => { if (!n) return null; let o = 0, u = 0, ps = 0; vals.forEach((v) => { if (v > line) o++; else if (v < line) u++; else ps++; }); return { o, u, ps }; })();
    let pO = over, pU = under;
    // the player's own record, smoothed so a perfect 7-of-7 counts as about 89%, not 100%
    if (emp && n) { const wE = n / (n + 6); pO = wE * ((emp.o + 1) / (n + 2)) + (1 - wE) * over; pU = wE * ((emp.u + 1) / (n + 2)) + (1 - wE) * under; }
    res.raw = side === 'over' ? pO : pU;
    res.p = clamp(calibrate(res.raw), 0.02, 0.97); // calibrated from the backtest; never certain res.push = push; res.emp = emp; res.modelOnly = side === 'over' ? over : under;
    res.why.push(p.name + ' averages ' + season.toFixed(1) + ' ' + def.label.toLowerCase() + ' over ' + n + ' game' + (n === 1 ? '' : 's') + (n > 1 ? ' (recent-weighted ' + wm.toFixed(1) + ')' : '') + '.');
    if (gm && Math.abs(mult - 1) > 0.01) res.why.push('Adjusted ' + (mult > 1 ? 'up' : 'down') + ' ' + Math.abs((mult - 1) * 100).toFixed(0) + '% for this game\'s projected scoring.');
    res.why.push('Projection ' + mu.toFixed(1) + (def.count ? ', allowing for game-to-game swings in the count,' : ' with a typical swing of about ' + res.s.toFixed(0) + ' either way,') + ' gives ' + pct(res.modelOnly, 1) + ' for the ' + side + ' ' + line + '.');
    if (emp) res.why.push('He has gone over ' + line + ' in ' + emp.o + ' of ' + n + ' games, under in ' + emp.u + (emp.ps ? ', pushed in ' + emp.ps : '') + '. The final figure leans on that record by ' + pct(n / (n + 6)) + ', then the result (' + pct(res.raw, 1) + ') is adjusted to ' + pct(res.p, 1) + ' using how past estimates like this actually performed. No prop is rated above 97% because a player can always get hurt or benched.');
    return res;
  }

  /* ---------- reasoning text for a game ---------- */
  function gameReasoning(M, gm) {
    const lines = []; const th = gm.th, ta = gm.ta;
    const rec = (t) => t ? (t.w + '-' + t.l + (M.sp === 'nhl' ? '-' + t.otl : '')) : '?';
    if (th && ta) {
      lines.push(gm.home + ' (' + rec(th) + ') score ' + th.pfg.toFixed(M.sp === 'nfl' ? 1 : 2) + ' and allow ' + th.pag.toFixed(M.sp === 'nfl' ? 1 : 2) + ' per game; ' + gm.away + ' (' + rec(ta) + ') score ' + ta.pfg.toFixed(M.sp === 'nfl' ? 1 : 2) + ' and allow ' + ta.pag.toFixed(M.sp === 'nfl' ? 1 : 2) + '.');
      lines.push('Power ranks from this season\'s results: ' + gm.home + ' #' + th.rank + ', ' + gm.away + ' #' + ta.rank + ' of ' + M.teams.length + '.');
    }
    if (M.sp === 'nfl') {
      lines.push('Model alone: ' + gm.home + ' by ' + gm.modelMargin.toFixed(1) + ', total ' + gm.modelTotal.toFixed(1) + ' (' + pct(gm.modelHomeWin) + ' home win).');
      if (gm.mktMargin != null) lines.push('Betting market: ' + gm.home + ' by ' + gm.mktMargin.toFixed(1) + (gm.mktTotal != null ? ', total ' + gm.mktTotal : '') + ' (' + pct(gm.mktHomeWin) + ' home win). With only about ' + Math.round(M.goals.n * 2 / M.teams.length) + ' games played per team, the market is weighted ' + pct(gm.wMarket) + ' because lines already reflect injuries and information this model cannot see.');
      lines.push('Blended: ' + gm.home + ' by ' + gm.margin.toFixed(1) + ', projected ' + gm.hsB.toFixed(1) + '-' + gm.asB.toFixed(1) + ' with a margin spread of about ' + gm.sdMargin.toFixed(1) + ' points.');
    } else {
      const G = gm.goalies || {};
      const gtxt = (side, team, info, st, f) => {
        if (!info) return team + ' starting goalie not announced yet';
        if (!info.known) return info.name + ' (' + (st || 'projected') + ') starts for ' + team + ', no save data this season';
        const ch = (f - 1) * 100;
        return info.name + ' (' + (st || 'projected').toLowerCase() + ') starts for ' + team + ': save % ' + info.sv.toFixed(3).replace(/^0/, '') + ' vs the team\'s ' + info.teamSv.toFixed(3).replace(/^0/, '') + (Math.abs(ch) >= 1 ? ', so goals against him are adjusted ' + (ch > 0 ? 'up ' : 'down ') + Math.abs(ch).toFixed(0) + '%' : ', about average for them');
      };
      lines.push('Starting goalies: ' + gtxt('away', gm.away, G.away, G.awayStatus, G.awayF) + '. ' + gtxt('home', gm.home, G.home, G.homeStatus, G.homeF) + '.');
      lines.push('Expected goals: ' + gm.home + ' ' + gm.lh.toFixed(2) + ', ' + gm.away + ' ' + gm.la.toFixed(2) + ' (half from goals scored and allowed, half from shot volume, then the goalie adjustment).');
      if (gm.mktHomeWin != null) lines.push('Betting market (vig removed): ' + gm.home + ' ' + pct(gm.mktHomeWin) + '. Model alone: ' + pct(gm.modelHomeWin) + '. Blended with ' + pct(gm.wMarket) + ' weight on the market.');
      else lines.push('No moneyline available, so this is the model alone: ' + pct(gm.modelHomeWin) + ' for ' + gm.home + '.');
      lines.push('Regulation tie chance ' + pct(gm.regTie) + '; overtime and shootout are split about evenly.');
    }
    return lines;
  }

  const API = { normName, goalieFactor, parseCSV, buildSport, gameModel, betProb, propProb, gameReasoning, PROPS, statVal, eligibleRows, amToProb, probToAm, pct, mean, sd, Phi, pois, envFactor };
  if (typeof module !== 'undefined' && module.exports) module.exports = API; else root.KCModel = API;
})(typeof window !== 'undefined' ? window : this);
