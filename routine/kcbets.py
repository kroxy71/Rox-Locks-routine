#!/usr/bin/env python3
"""Rox Locks Computer: KingCap paper bets (cat "kingcap") added to data/bot.json.

  python3 routine/kcbets.py /tmp/kc/picks.json [--dry]

Run from the clone (cwd = repo root) right after `gather.py show` filled picks.json, i.e. after the picks email.
The computer runs KingCap's firm picks through its own model and paper-bets the ones it likes best:
  - up to 5 KingCap bets per ET day (a later Final/Update email only tops the day up to 5)
  - only games that start at least 10 minutes from now; never the same bet twice
  - stake $25, or $50 when the model's edge is big (>= 0.05) and the day can still hold all 5; KingCap bets at most $175 a day
  - no odds price is ever invented: a pick that cannot be priced at FanDuel/DraftKings is skipped
Then publish.py (or this script's own commit when run with --push) pushes data/bot.json.
Standard library only. Never prints the SharpAPI key.
"""
import argparse
import datetime
import json
import math
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gather as G  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
BOT = os.path.join(REPO, 'data', 'bot.json')
MAX_BETS, MAX_DAY, BASE, BIG, BIG_EDGE = 5, 175, 25, 50, 0.05
W = {'market': 0.40, 'pm': 0.25, 'espn': 0.20}
CONF = {'High': 0.02, 'Medium': 0.0, 'Low': -0.02}
SPN = {'nfl': 'NFL', 'ncaaf': 'NCAAF', 'nba': 'NBA', 'nhl': 'NHL', 'mlb': 'MLB', 'ncaab': 'NCAAB'}


def utc(iso):
    return datetime.datetime.fromisoformat(iso.replace('Z', '+00:00'))


def best_price(g, key, idx=None):
    """best American price over FD/DK for lines[key]; returns (odds, book, line)"""
    out = None
    for b, name in (('fd', 'FanDuel'), ('dk', 'DraftKings')):
        v = ((g['src'].get('lines') or {}).get(b) or {}).get(key)
        if v is None:
            continue
        line, a = (v[0], v[1]) if isinstance(v, list) else (None, v)
        if out is None or G.dec(a) > G.dec(out[0]):
            out = (a, name, line)
    return out


def novig_pair(g, ka, kb):
    ps = []
    for b in ('fd', 'dk'):
        s = (g['src'].get('lines') or {}).get(b) or {}
        if ka in s and kb in s:
            a = s[ka][1] if isinstance(s[ka], list) else s[ka]
            c = s[kb][1] if isinstance(s[kb], list) else s[kb]
            ps.append(G.novig(a, c)[0])
    return sum(ps) / len(ps) if ps else None


def model_ml(g, side):
    """weighted model probability for side ('home'/'away'); returns (p, n_sources, text)"""
    other = 'away' if side == 'home' else 'home'
    parts, txt = [], []
    mp = G.mkt_probs(g)
    if mp:
        m = mp[0] if side == 'home' else mp[1]
        parts.append((W['market'], m))
        txt.append('Market %d%%' % round(m * 100))
    pm = [g['src'][k][side] for k in ('kalshi', 'polymarket') if side in (g['src'].get(k) or {}) and other in g['src'][k]]
    if pm:
        v = sum(pm) / len(pm)
        parts.append((W['pm'], v))
        txt.append('Kalshi/Polymarket %d%%' % round(v * 100))
    e = g['src'].get('espn_pred') or {}
    if side in e:
        parts.append((W['espn'], e[side]))
        txt.append('ESPN %d%%' % round(e[side] * 100))
    if not parts:
        return None, 0, ''
    tw = sum(w for w, _ in parts)
    return sum(w * p for w, p in parts) / tw, len(parts), ', '.join(txt)


def prop_price(player, sp, stat, ou, line):
    key = os.environ.get('ODDS_API_KEY', '')
    if not key or sp not in G.SHARP_LEAGUE:
        return None
    q = {'league': G.SHARP_LEAGUE[sp], 'sportsbook': 'fanduel,draftkings', 'market': 'props', 'player_name': player, 'limit': 100}
    try:
        j = json.loads(G.http('https://api.sharpapi.io/api/v1/odds?' + urllib.parse.urlencode(q, safe=','), {'X-API-Key': key}, 30))
    except Exception:
        return None
    rows = [r for r in j.get('data', []) if not r.get('is_live') and r.get('odds_american') is not None]
    if stat in ('atd', 'atg'):
        want = ('touchdown',) if stat == 'atd' else ('goal',)
        rows = [r for r in rows if any(w in (r.get('market_type') or '') for w in want) and 'anytime' in (r.get('market_type') or '')
                and (r.get('selection_type') or '').lower() in ('yes', 'over', '')]
        side_rows = rows
        opp_rows = []
    else:
        mt = G.STATS_PROP.get(stat)
        if not mt:
            return None
        rows = [r for r in rows if r.get('market_type') == mt and r.get('line') is not None]
        if not rows:
            return None
        if line is not None:
            lines = sorted({float(r['line']) for r in rows}, key=lambda x: abs(x - line))
            if abs(lines[0] - line) > 1.0:
                return None
            use = lines[0]
        else:
            use = sorted({float(r['line']) for r in rows})[len({float(r['line']) for r in rows}) // 2]
        rows = [r for r in rows if float(r['line']) == use]
        side_rows = [r for r in rows if (r.get('selection_type') or '').lower() == ou]
        opp_rows = [r for r in rows if (r.get('selection_type') or '').lower() != ou]
        line = use
    if not side_rows:
        return None
    best = max(side_rows, key=lambda r: G.dec(r['odds_american']))
    nv = None
    for r in side_rows:
        o = [x for x in opp_rows if x.get('sportsbook') == r.get('sportsbook')]
        if o:
            nv = G.novig(r['odds_american'], o[0]['odds_american'])[0]
            break
    book = 'FanDuel' if best.get('sportsbook') == 'fanduel' else 'DraftKings'
    return best['odds_american'], book, line, nv


def candidate(p, games):
    kc = p.get('kc') or {}
    t = kc.get('t')
    sp = (p.get('sp') or '').lower()
    names = [kc.get('team'), kc.get('opp')] + list(kc.get('teams') or [])
    g = G.find_game(games, sp, names)
    if not g:
        return None
    if sp in G.PATH and 'espn_pred' not in g['src']:
        G.attach_predictor(g)
    side = None
    if kc.get('team'):
        side = G.side_of(g, kc['team'])
    leg = {'sp': SPN.get(sp, sp.upper()), 'game': '%s @ %s' % (g['away'], g['home']), 'start': g['start'],
           'status': 'pending', 'result': ''}
    srcs = ''
    if t == 'ml' and side:
        pr = best_price(g, 'ml_' + side)
        if not pr:
            return None
        mp, n, srcs = model_ml(g, side)
        if mp is None or n < 2:
            return None
        team = g[side]
        opp = g['away' if side == 'home' else 'home']
        leg.update(kind='ml', sel='%s ML' % team, team=team, opp=opp)
        odds, book, line = pr
    elif t == 'spread' and side:
        pr = best_price(g, 'sp_' + side)
        if not pr:
            return None
        odds, book, line = pr
        if kc.get('line') is not None and line is not None and abs(float(line) - float(kc['line'])) > 1.5:
            return None
        nv = novig_pair(g, 'sp_' + side, 'sp_' + ('away' if side == 'home' else 'home'))
        mm, n, srcs = model_ml(g, side)
        mk = G.mkt_probs(g)
        if nv is None:
            return None
        shift = 0.0
        if mm is not None and mk and n >= 2:
            shift = 0.5 * (mm - (mk[0] if side == 'home' else mk[1]))
        mp = nv + shift
        team = g[side]
        opp = g['away' if side == 'home' else 'home']
        leg.update(kind='spread', sel='%s %+g' % (team, float(line)), team=team, opp=opp, line=float(line))
        srcs = 'Spread no-vig %d%%; %s' % (round(nv * 100), srcs)
    elif t == 'total' and kc.get('ou') in ('over', 'under'):
        pr = best_price(g, 'tot_' + kc['ou'])
        if not pr:
            return None
        odds, book, line = pr
        if kc.get('line') is not None and line is not None and abs(float(line) - float(kc['line'])) > 1.5:
            return None
        mp = novig_pair(g, 'tot_' + kc['ou'], 'tot_' + ('under' if kc['ou'] == 'over' else 'over'))
        if mp is None:
            return None
        leg.update(kind='total', sel='%s/%s %s %g' % (g['away'], g['home'], kc['ou'], float(line)), ou=kc['ou'], line=float(line),
                   team=g['away'], opp=g['home'])
        srcs = 'Total no-vig %d%%' % round(mp * 100)
    elif t in ('prop', 'atd', 'atg') and kc.get('player'):
        stat = t if t != 'prop' else kc.get('stat')
        pr = prop_price(kc['player'], sp, stat, kc.get('ou', 'over'), kc.get('line'))
        if not pr:
            return None
        odds, book, line, nv = pr
        mp = nv if nv is not None else None
        if mp is None:
            return None
        if t == 'prop':
            sel = '%s %s %s %g' % (kc['player'], stat, kc.get('ou', 'over'), line)
        else:
            sel = '%s anytime %s' % (kc['player'], 'TD' if t == 'atd' else 'goal')
        leg.update(kind=('prop' if t == 'prop' else t), sel=sel, player=kc['player'], team=kc.get('team', ''),
                   stat=stat, ou=kc.get('ou', 'over'), line=line)
        srcs = 'Prop no-vig %d%%' % round(mp * 100)
    else:
        return None
    ip = G.am2p(odds)
    edge = mp - ip
    agrees = sum(1 for s in p.get('sites') or [] if len(s) > 2 and s[2] == 'agrees')
    disag = sum(1 for s in p.get('sites') or [] if len(s) > 2 and s[2] == 'disagrees')
    conf = p.get('conf') or p.get('conv') or 'Medium'
    score = edge + 0.01 * (agrees - disag) + CONF.get(conf, 0)
    leg.update(odds=int(odds), book=book, model_p=round(mp, 4), implied_p=round(ip, 4))
    return {'g': g, 'leg': leg, 'edge': edge, 'score': score, 'srcs': srcs, 'conf': conf, 'agrees': agrees, 'disag': disag,
            'bet': p.get('index') or p.get('bet') or leg['sel']}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('picks')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    d = json.load(open(a.picks, encoding='utf-8'))
    games = json.load(open(os.path.join(G.G, 'games.json'), encoding='utf-8'))
    try:
        bot = json.load(open(BOT, encoding='utf-8'))
    except Exception:
        bot = {'version': 1, 'start': 1000, 'bankroll': 1000, 'bets': [], 'public': [], 'days': []}
    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.astimezone(G.ET).date().isoformat()
    mine = [b for b in bot['bets'] if b.get('cat') == 'kingcap' and b.get('date') == today]
    have = {b['legs'][0]['sel'] for b in mine}
    room_n = MAX_BETS - len(mine)
    room_s = MAX_DAY - sum(b['stake'] for b in mine)
    if room_n <= 0 or room_s < BASE:
        print('kingcap bets: already %d today, nothing added' % len(mine))
        return
    cands, skipped = [], 0
    for p in d.get('picks', []):
        if p.get('lean') or not p.get('kc'):
            continue
        c = None
        try:
            c = candidate(p, games)
        except Exception:
            c = None
        if not c:
            skipped += 1
            continue
        if utc(c['g']['start']) < now + datetime.timedelta(minutes=10) or c['g'].get('state') in ('in', 'post'):
            continue
        if c['leg']['sel'] in have:
            continue
        cands.append(c)
        time.sleep(0.2)
    cands.sort(key=lambda c: -c['score'])
    n = len(bot['bets'])
    added = []
    for c in cands:
        if len(added) >= room_n or room_s < BASE:
            break
        if c['leg']['sel'] in have:
            continue
        after = min(room_n, len(cands)) - len(added) - 1          # bets still to place after this one
        stake = BIG if (c['edge'] >= BIG_EDGE and room_s - BIG >= BASE * max(after, 0)) else BASE
        leg = c['leg']
        dd = G.dec(leg['odds'])
        idx = sum(1 for b in bot['bets'] if b.get('date') == today) + 1
        bet = {'id': '%s-k%d' % (today, idx), 'date': today, 'placed': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'cat': 'kingcap',
               'title': 'KingCap: %s' % leg['sel'], 'legs': [leg], 'odds': leg['odds'], 'book': leg['book'], 'stake': stake,
               'to_win': round(stake * (dd - 1), 2), 'model_p': leg['model_p'], 'edge': round(c['edge'], 4),
               'sources': '%s | KingCap %s, %d sites agree, %d disagree' % (c['srcs'], c['conf'], c['agrees'], c['disag']),
               'why': 'Model %d%% vs %s %+d (%d%%); KingCap confidence %s.' % (round(leg['model_p'] * 100), leg['book'], leg['odds'],
                                                                               round(leg['implied_p'] * 100), c['conf']),
               'status': 'pending', 'profit': None, 'result': ''}
        bot['bets'].append(bet)
        have.add(leg['sel'])
        added.append(bet)
        room_s -= stake
    pend = sum(b['stake'] for b in bot['bets'] if b.get('status') == 'pending')
    bot['at_risk'] = pend
    bot['updated'] = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    if not a.dry:
        with open(BOT, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(bot, f, ensure_ascii=False, indent=1)
    print('kingcap bets added: %d ($%d) from %d priced picks (%d could not be priced)%s' % (
        len(added), sum(b['stake'] for b in added), len(cands), skipped, ' [dry]' if a.dry else ''))
    for b in added:
        print('  $%d %s %+d %s edge %.3f' % (b['stake'], b['legs'][0]['sel'], b['odds'], b['book'], b['edge']))


if __name__ == '__main__':
    try:
        main()
    except Exception as ex:
        print('kcbets failed:', str(ex)[:300])
        sys.exit(1)
