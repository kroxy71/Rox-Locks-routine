#!/usr/bin/env python3
"""Fetch every public data source once and print only what the picks need.

  python3 routine/gather.py fetch --sports nba,nhl [--date YYYY-MM-DD]
        pulls ESPN, SharpAPI (FanDuel/DraftKings), Polymarket, Kalshi and the scraped pages
        into /tmp/kc/g/ (cache) and writes /tmp/kc/g/games.json
  python3 routine/gather.py show picks.json
        prints one compact record per game that has a pick (lines, no-vig %, market and model %,
        page excerpts) and fills each pick's "game", "time", "line" and "sites" when they are empty
        (writes picks.json back, so render_picks.py can use it). Verdicts follow the routine rules.
  python3 routine/gather.py props "Player Name" [--sport nba]
        current FanDuel/DraftKings lines for one player (SharpAPI)

Standard library only. The SharpAPI key is read from $ODDS_API_KEY and only sent as a header; it is never printed.
"""
import argparse
import datetime
import gzip
import html as htmlmod
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
G = os.environ.get('KC_G', '/tmp/kc/g')
UA = {'User-Agent': 'Mozilla/5.0', 'Accept-Encoding': 'gzip'}
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/'
PATH = {'nfl': 'football/nfl', 'ncaaf': 'football/college-football', 'nba': 'basketball/nba', 'nhl': 'hockey/nhl',
        'mlb': 'baseball/mlb', 'ncaab': 'basketball/mens-college-basketball'}
EXTRA = {'ncaaf': '&groups=80&limit=300', 'ncaab': '&groups=50&limit=300'}
SHARP_LEAGUE = {'nfl': 'nfl', 'ncaaf': 'ncaaf', 'nba': 'nba', 'nhl': 'nhl', 'mlb': 'mlb', 'ncaab': 'ncaab'}
PM_TAG = {'nfl': 'nfl', 'ncaaf': 'cfb', 'nba': 'nba', 'nhl': 'nhl', 'mlb': 'mlb', 'ncaab': 'cbb'}
KALSHI = {'nfl': 'KXNFLGAME', 'ncaaf': 'KXNCAAFGAME', 'nba': 'KXNBAGAME', 'nhl': 'KXNHLGAME', 'mlb': 'KXMLBGAME'}
VI = {'nfl': 'nfl', 'ncaaf': 'college-football', 'nba': 'nba', 'nhl': 'nhl', 'mlb': 'mlb'}
TR = {'nfl': 'nfl', 'ncaaf': 'ncf', 'nba': 'nba'}
ROTO = {'nfl': 'football/lineups.php', 'ncaaf': 'cfootball/lineups.php', 'nba': 'basketball/nba-lineups.php',
        'nhl': 'hockey/nhl-lineups.php', 'mlb': 'baseball/daily-lineups.php'}
SAO = {'nfl': 'nfl', 'ncaaf': 'ncaaf', 'nba': 'nba', 'nhl': 'nhl', 'mlb': 'mlb'}
STATS_PROP = {'pra': 'player_points_+_rebounds_+_assists', 'pr': 'player_points_+_rebounds', 'points': 'player_points',
              'rebounds': 'player_rebounds', 'assists': 'player_assists', 'threes': 'player_made_threes',
              'steals': 'player_steals', 'blocks': 'player_blocks'}


def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9 ]', '', s).strip()


def nick(name):
    n = norm(name).split()
    return n[-1] if n else ''


def http(url, headers=None, timeout=25, text=True):
    req = urllib.request.Request(url, headers=dict(UA, **(headers or {})))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if r.headers.get('Content-Encoding') == 'gzip':
            raw = gzip.decompress(raw)
    return raw.decode('utf-8', 'replace') if text else raw


def jget(url, headers=None, timeout=25):
    return json.loads(http(url, headers, timeout))


def cached(name, fn):
    os.makedirs(G, exist_ok=True)
    fp = os.path.join(G, name)
    if os.path.exists(fp) and time.time() - os.path.getmtime(fp) < 600:
        return open(fp, encoding='utf-8').read()
    try:
        s = fn()
    except Exception as ex:
        s = ''
        print('  (source failed: %s: %s)' % (name, str(ex)[:80]), file=sys.stderr)
    open(fp, 'w', encoding='utf-8').write(s or '')
    return s or ''


def strip_tags(h):
    h = re.sub(r'(?is)<(script|style).*?</\1>', ' ', h)
    h = re.sub(r'<[^>]+>', ' ', h)
    return re.sub(r'\s+', ' ', htmlmod.unescape(h))


# ---------------------------------------------------------------- odds math
def am2p(a):
    return 100.0 / (a + 100) if a > 0 else -a / (-a + 100.0)


def dec(a):
    return 1 + a / 100.0 if a > 0 else 1 + 100.0 / -a


def novig(a, b):
    pa, pb = am2p(a), am2p(b)
    return pa / (pa + pb), pb / (pa + pb)


def fmt_am(a):
    return ('%+d' % a) if a is not None else '?'


# ---------------------------------------------------------------- fetch
def espn_games(sp, date):
    d1 = date.strftime('%Y%m%d')
    d2 = (date + datetime.timedelta(days=1)).strftime('%Y%m%d')
    games = {}
    for dd in (d1, d2):
        raw = cached('espn_%s_%s.json' % (sp, dd), lambda dd=dd: http('%s%s/scoreboard?dates=%s%s' % (ESPN, PATH[sp], dd, EXTRA.get(sp, ''))))
        if not raw:
            continue
        for e in json.loads(raw).get('events', []):
            c = e['competitions'][0]
            comps = {x['homeAway']: x for x in c['competitors']}
            if 'home' not in comps or 'away' not in comps:
                continue
            o = (c.get('odds') or [{}])[0]
            games[e['id']] = {
                'sp': sp, 'id': e['id'], 'start': e['date'],
                'home': comps['home']['team']['displayName'], 'away': comps['away']['team']['displayName'],
                'home_abbr': comps['home']['team'].get('abbreviation', ''), 'away_abbr': comps['away']['team'].get('abbreviation', ''),
                'status': e['status']['type'].get('shortDetail', ''), 'state': e['status']['type'].get('state', ''),
                'tv': ','.join(b.get('names', [''])[0] for b in c.get('broadcasts', []) if b.get('names')),
                'espn_line': o.get('details'), 'espn_total': o.get('overUnder'), 'espn_provider': (o.get('provider') or {}).get('name'),
                'src': {}}
    return list(games.values())


def sharp_pull(sp, market):
    key = os.environ.get('ODDS_API_KEY', '')
    if not key:
        return []
    rows, cursor = [], None
    for _ in range(4):
        q = {'league': SHARP_LEAGUE[sp], 'sportsbook': 'fanduel,draftkings', 'market': market, 'limit': 200}
        if cursor:
            q['cursor'] = cursor
        url = 'https://api.sharpapi.io/api/v1/odds?' + urllib.parse.urlencode(q, safe=',')
        try:
            j = json.loads(http(url, {'X-API-Key': key}, 30))
        except urllib.error.HTTPError as ex:
            if ex.code == 429:
                time.sleep(60)
                continue
            break
        except Exception:
            break
        rows += j.get('data', [])
        pg = j.get('pagination') or {}
        cursor = pg.get('next_cursor')
        if not (pg.get('has_more') and cursor):
            break
        time.sleep(6)
    return rows


def attach_sharp(games, sp):
    rows = json.loads(cached('sharp_%s.json' % sp, lambda: json.dumps(sharp_pull(sp, 'main')))) if os.environ.get('ODDS_API_KEY') else []
    byk = {}
    for g in games:
        byk[(norm(g['home']), norm(g['away']))] = g
    for r in rows:
        g = byk.get((norm(r.get('home_team')), norm(r.get('away_team'))))
        if not g:
            continue
        book = 'fd' if r.get('sportsbook') == 'fanduel' else 'dk'
        mt, side, line, a = r.get('market_type'), r.get('selection_type'), r.get('line'), r.get('odds_american')
        if a is None or r.get('is_alternate_line'):
            continue
        s = g['src'].setdefault('lines', {}).setdefault(book, {})
        if mt == 'moneyline' and side in ('home', 'away'):
            s['ml_' + side] = a
        elif mt in ('point_spread', 'puck_line') and side in ('home', 'away'):
            s['sp_' + side] = [line, a]
        elif mt in ('total_points', 'total_goals') and side in ('over', 'under'):
            s['tot_' + side] = [line, a]


def attach_polymarket(games, sp):
    raw = cached('pm_%s.json' % sp, lambda: http('https://gamma-api.polymarket.com/events?tag_slug=%s&closed=false&limit=100' % PM_TAG[sp]))
    try:
        ev = json.loads(raw) if raw else []
    except Exception:
        ev = []
    for e in ev:
        for m in e.get('markets', [])[:1]:
            try:
                outs, prices = json.loads(m['outcomes']), [float(x) for x in json.loads(m['outcomePrices'])]
            except Exception:
                continue
            if len(outs) != 2:
                continue
            for g in games:
                hn, an = nick(g['home']), nick(g['away'])
                names = [norm(o) for o in outs]
                if any(hn in n or n in norm(g['home']) for n in names) and any(an in n or n in norm(g['away']) for n in names):
                    for o, p in zip(outs, prices):
                        side = 'home' if (nick(g['home']) in norm(o) or norm(o) in norm(g['home'])) else 'away'
                        g['src'].setdefault('polymarket', {})[side] = round(p, 3)


def attach_kalshi(games, sp):
    if sp not in KALSHI:
        return
    raw = cached('kalshi_%s.json' % sp, lambda: http('https://api.elections.kalshi.com/trade-api/v2/markets?status=open&limit=200&series_ticker=%s' % KALSHI[sp]))
    try:
        ms = json.loads(raw).get('markets', []) if raw else []
    except Exception:
        ms = []
    for m in ms:
        title = norm(m.get('title', '') + ' ' + m.get('yes_sub_title', ''))
        for g in games:
            hn, an = nick(g['home']), nick(g['away'])
            if hn in title and an in title:
                who = norm(m.get('yes_sub_title', ''))
                try:
                    p = float(m.get('last_price_dollars') or 0) or (float(m.get('yes_bid_dollars') or 0) + float(m.get('yes_ask_dollars') or 0)) / 2
                except Exception:
                    continue
                if p <= 0:
                    continue
                if hn in who:
                    g['src'].setdefault('kalshi', {})['home'] = round(p, 3)
                elif an in who:
                    g['src'].setdefault('kalshi', {})['away'] = round(p, 3)


def attach_predictor(g):
    raw = cached('espn_sum_%s.json' % g['id'], lambda: http('%s%s/summary?event=%s' % (ESPN, PATH[g['sp']], g['id'])))
    if not raw:
        return
    j = json.loads(raw)
    pr = j.get('predictor')
    if pr:
        try:
            g['src']['espn_pred'] = {'home': float(pr['homeTeam']['gameProjection']) / 100, 'away': float(pr['awayTeam']['gameProjection']) / 100}
        except Exception:
            pass
    inj = []
    for t in j.get('injuries', []):
        for a in t.get('injuries', []):
            if a.get('status') in ('Out', 'Doubtful', 'Questionable', 'Day-To-Day'):
                inj.append('%s %s' % (a['athlete'].get('displayName'), a.get('status')))
    if inj:
        g['injuries'] = inj[:12]


PAGES = {
    'oddsshark': lambda sp: 'https://www.oddsshark.com/%s/computer-picks' % sp if sp in SAO else None,
    'scoresandodds': lambda sp: 'https://www.scoresandodds.com/%s' % SAO[sp] if sp in SAO else None,
    'vegasinsider': lambda sp: 'https://www.vegasinsider.com/%s/odds/las-vegas/' % VI[sp] if sp in VI else None,
    'teamrankings_ats': lambda sp: 'https://www.teamrankings.com/%s/trends/ats_trends/' % TR[sp] if sp in TR else None,
    'teamrankings_ou': lambda sp: 'https://www.teamrankings.com/%s/trends/ou_trends/' % TR[sp] if sp in TR else None,
    'rotowire': lambda sp: 'https://www.rotowire.com/%s' % ROTO[sp] if sp in ROTO else None,
}


def page_text(name, sp):
    u = PAGES[name](sp)
    if not u:
        return ''
    raw = cached('page_%s_%s.txt' % (name, sp), lambda: strip_tags(http(u, timeout=30)))
    return raw


def tr_rows(text, g):
    """TeamRankings trend tables: 'Golden State 8-6-0 57.1% ...' rows for the two teams."""
    out = []
    for name in (g['away'], g['home']):
        words = name.split()
        cands = [name, ' '.join(words[:-1]), words[-1], name.replace('Los Angeles', 'LA'), ' '.join(words[:-1]).replace('Los Angeles', 'LA')]
        for c in cands:
            if not c:
                continue
            m = re.search(r'(?<![A-Za-z])' + re.escape(c) + r'\s+(\d+-\d+-\d+)\s+([\d.]+%)', text)
            if m:
                out.append('%s %s %s' % (c, m.group(1), m.group(2)))
                break
    return '; '.join(out)


def excerpt(text, g, width=330, name=''):
    if not text:
        return ''
    if name.startswith('teamrankings'):
        r = tr_rows(text, g)
        return ('%s: %s' % ('ATS' if name.endswith('ats') else 'over/under', r)) if r else ''
    t = text
    hn, an = nick(g['home']), nick(g['away'])
    low = t.lower()
    best = None
    for m in re.finditer(re.escape(an), low):
        seg = low[max(0, m.start() - 250):m.start() + 450]
        if hn in seg:
            best = m.start()
            break
    if best is None:
        return ''
    return t[max(0, best - 60):best + width].strip()


def fetch(sports, date):
    os.makedirs(G, exist_ok=True)
    out = []
    for sp in sports:
        if sp not in PATH:
            continue
        games = [g for g in espn_games(sp, date)]
        attach_sharp(games, sp)
        attach_polymarket(games, sp)
        attach_kalshi(games, sp)
        for name in PAGES:
            txt = page_text(name, sp)
            if not txt:
                continue
            for g in games:
                ex = excerpt(txt, g, name=name)
                if ex:
                    g['src'].setdefault('pages', {})[name] = ex
        out += games
    json.dump(out, open(os.path.join(G, 'games.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print('games:', len(out), 'by sport:', {s: sum(1 for g in out if g['sp'] == s) for s in sports})


# ---------------------------------------------------------------- show
def et(iso):
    d = datetime.datetime.fromisoformat(iso.replace('Z', '+00:00')).astimezone(ET)
    return d.strftime('%-I:%M %p ET') if sys.platform != 'win32' else d.strftime('%I:%M %p ET').lstrip('0')


def find_game(games, sp, names):
    names = [n for n in names if n]
    best = None
    for g in games:
        if g['sp'] != sp:
            continue
        hit = sum(1 for n in names if nick(n) in (nick(g['home']), nick(g['away'])) or norm(n) in (norm(g['home']), norm(g['away'])))
        if hit and (best is None or hit > best[0]):
            best = (hit, g)
    return best[1] if best else None


def mkt_probs(g):
    ps = []
    for b in ('fd', 'dk'):
        s = (g['src'].get('lines') or {}).get(b) or {}
        if 'ml_home' in s and 'ml_away' in s:
            ps.append(novig(s['ml_home'], s['ml_away']))
    if not ps:
        return None
    return sum(p[0] for p in ps) / len(ps), sum(p[1] for p in ps) / len(ps)


def verdict(pa, pb):
    """pa = probability for KingCap's side, pb = other side."""
    if pa >= 0.55:
        return 'agrees'
    if pb >= 0.55:
        return 'disagrees'
    return 'neutral'


def sites_for(p, g):
    kc = p.get('kc') or {}
    t = kc.get('t')
    out = []
    side = None
    if t in ('ml', 'spread', 'h1ml'):
        side = 'home' if nick(kc.get('team', '')) == nick(g['home']) else 'away'
    src = g['src']
    if side:
        other = 'away' if side == 'home' else 'home'
        mp = mkt_probs(g)
        if mp:
            pa, pb = (mp[0], mp[1]) if side == 'home' else (mp[1], mp[0])
            out.append(['FD/DK no-vig', '%s %d%%' % (kc['team'], round(pa * 100)), verdict(pa, pb)])
        for key, label in (('polymarket', 'Polymarket'), ('kalshi', 'Kalshi'), ('espn_pred', 'ESPN predictor')):
            d = src.get(key)
            if d and side in d and other in d:
                out.append([label, '%s %d%%' % (kc['team'], round(d[side] * 100)), verdict(d[side], d[other])])
    elif t == 'total':
        line = kc.get('line')
        for b, label in (('fd', 'FanDuel'), ('dk', 'DraftKings')):
            s = (src.get('lines') or {}).get(b) or {}
            if 'tot_over' in s:
                out.append([label + ' total', '%g' % s['tot_over'][0], 'neutral'])
                break
    return out


def show(path):
    picks = json.load(open(path, encoding='utf-8'))
    games = json.load(open(os.path.join(G, 'games.json'), encoding='utf-8'))
    seen = set()
    for p in picks.get('picks', []):
        kc = p.get('kc') or {}
        sp = (p['sp'] or '').lower()
        names = [kc.get('team'), kc.get('opp')] + list(kc.get('teams') or [])
        g = find_game(games, sp, names)
        if not g:
            continue
        if not p.get('game'):
            p['game'] = '%s @ %s' % (g['away'], g['home'])
        if not p.get('time'):
            p['time'] = et(g['start'])
        if not p.get('tv') and g.get('tv'):
            p['tv'] = g['tv']
        if g['state'] == 'in' or g['state'] == 'post':
            p.setdefault('status', g['status'])
        if sp in PATH and not g['src'].get('espn_pred') and g['id'] not in seen:
            attach_predictor(g)
        s = sites_for(p, g)
        if s and not p.get('sites'):
            p['sites'] = s
        if g['id'] in seen:
            continue
        seen.add(g['id'])
        L = g['src'].get('lines') or {}
        print('== %s: %s @ %s | %s | %s' % (sp.upper(), g['away'], g['home'], et(g['start']), g['status']))
        for b in ('fd', 'dk'):
            s_ = L.get(b)
            if s_:
                print('  %s ML %s/%s  spread %s/%s  total %s/%s' % (b.upper(), fmt_am(s_.get('ml_away')), fmt_am(s_.get('ml_home')),
                                                                   s_.get('sp_away'), s_.get('sp_home'), s_.get('tot_over'), s_.get('tot_under')))
        if g.get('espn_line'):
            print('  ESPN line: %s total %s (%s)' % (g['espn_line'], g.get('espn_total'), g.get('espn_provider')))
        for k in ('polymarket', 'kalshi', 'espn_pred'):
            if g['src'].get(k):
                print('  %s (away/home): %s/%s' % (k, g['src'][k].get('away'), g['src'][k].get('home')))
        if g.get('injuries'):
            print('  injuries: ' + '; '.join(g['injuries']))
        for k, v in (g['src'].get('pages') or {}).items():
            print('  [%s] %s' % (k, v[:330]))
    json.dump(picks, open(path, 'w', encoding='utf-8'), ensure_ascii=False)
    print('(auto-filled game, time, tv and sites on picks.json where empty; judge the [page] excerpts yourself and add them to sites)')


def props(player, sport, stat=None, line=None):
    key = os.environ.get('ODDS_API_KEY', '')
    if not key:
        print('no ODDS_API_KEY')
        return
    q = {'league': SHARP_LEAGUE[sport], 'sportsbook': 'fanduel,draftkings', 'market': 'props', 'player_name': player, 'limit': 100}
    j = json.loads(http('https://api.sharpapi.io/api/v1/odds?' + urllib.parse.urlencode(q, safe=','), {'X-API-Key': key}, 30))
    want = STATS_PROP.get(stat) if stat else None
    n = 0
    for r in j.get('data', []):
        if want and r.get('market_type') != want:
            continue
        if line is not None and r.get('line') is not None and abs(float(r['line']) - line) > 1e-9:
            continue
        print('%s %s %s %s line %s %s%s' % (r.get('sportsbook'), r.get('player_name'), r.get('market_type'), r.get('selection_type'),
                                            r.get('line'), fmt_am(r.get('odds_american')), ' (live)' if r.get('is_live') else ''))
        n += 1
    if not n:
        print('no match; markets seen: %s' % sorted({r.get('market_type') for r in j.get('data', [])}))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    f = sub.add_parser('fetch')
    f.add_argument('--sports', required=True)
    f.add_argument('--date', default='')
    s = sub.add_parser('show')
    s.add_argument('picks')
    pr = sub.add_parser('props')
    pr.add_argument('player')
    pr.add_argument('--sport', default='nba')
    pr.add_argument('--stat', default='')
    pr.add_argument('--line', type=float, default=None, help='only rows at this exact line')
    a = ap.parse_args()
    if a.cmd == 'fetch':
        date = datetime.date.fromisoformat(a.date) if a.date else datetime.datetime.now(ET).date()
        fetch([x.strip() for x in a.sports.split(',') if x.strip()], date)
    elif a.cmd == 'show':
        show(a.picks)
    else:
        props(a.player, a.sport, a.stat or None, a.line)


if __name__ == '__main__':
    main()
