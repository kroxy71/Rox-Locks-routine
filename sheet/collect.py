#!/usr/bin/env python3
"""Collect NFL + NHL 2026 regular-season game, team and player stats from ESPN's public JSON."""
import json, os, sys, csv, datetime, concurrent.futures as cf, urllib.request, re, time

OUT = sys.argv[1]
CACHE = os.path.join(OUT, 'cache'); os.makedirs(CACHE, exist_ok=True)
BASE = 'https://site.api.espn.com/apis/site/v2/sports/'
H = {'User-Agent': 'Mozilla/5.0'}
SPORTS = {'nfl': ('football/nfl', datetime.date(2026, 9, 1)), 'nhl': ('hockey/nhl', datetime.date(2026, 10, 1))}
END = datetime.date.today()


def get(u, tries=3):
    fp = os.path.join(CACHE, re.sub(r'[^A-Za-z0-9]', '_', u)[-200:] + '.json')
    if os.path.exists(fp) and '/summary' in u:
        return json.load(open(fp, encoding='utf8'))
    for i in range(tries):
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=40))
            if '/summary' in u:
                json.dump(d, open(fp, 'w', encoding='utf8'))
            return d
        except Exception:
            time.sleep(1 + i)
    return None


def num(x, default=0.0):
    try:
        return float(str(x).replace('+', '').split('/')[0].split('-')[0]) if str(x).count('-') < 2 and x not in ('', '--', None) else default
    except Exception:
        return default


def pair(x):
    try:
        a, b = str(x).split('/')
        return float(a), float(b)
    except Exception:
        return 0.0, 0.0


def tof(x):
    try:
        m, s = str(x).split(':'); return int(m) + int(s) / 60
    except Exception:
        return 0.0


def events_for(sp):
    path, a = SPORTS[sp]
    evs = {}
    d = a
    dates = []
    while d <= END + datetime.timedelta(days=8):
        dates.append(d); d += datetime.timedelta(days=1)

    def one(d):
        return get(f"{BASE}{path}/scoreboard?dates={d:%Y%m%d}&limit=300")
    with cf.ThreadPoolExecutor(6) as ex:
        for s in ex.map(one, dates):
            for e in (s or {}).get('events', []):
                evs[e['id']] = e
    return evs


def team_row(sp, t):
    st = {s['name']: s.get('displayValue') for s in t.get('statistics', [])}
    if sp == 'nfl':
        cmp_, att = pair(st.get('completionAttempts'))
        sk = str(st.get('sacksYardsLost', '0-0')).split('-')
        return dict(first_downs=num(st.get('firstDowns')), total_yards=num(st.get('totalYards')),
                    plays=num(st.get('totalOffensivePlays')), pass_yds=num(st.get('netPassingYards')),
                    pass_cmp=cmp_, pass_att=att, rush_yds=num(st.get('rushingYards')),
                    rush_att=num(st.get('rushingAttempts')), sacks_taken=num(sk[0]),
                    turnovers=num(st.get('turnovers')), penalties=num(str(st.get('totalPenaltiesYards', '0-0')).split('-')[0]),
                    poss_min=round(tof(st.get('possessionTime')), 1), third_made=pair(str(st.get('thirdDownEff', '0-0')).replace('-', '/'))[0],
                    third_att=pair(str(st.get('thirdDownEff', '0-0')).replace('-', '/'))[1])
    return dict(shots=num(st.get('shotsTotal')), hits=num(st.get('hits')), blocks=num(st.get('blockedShots')),
                takeaways=num(st.get('takeaways')), giveaways=num(st.get('giveaways')),
                pp_goals=num(st.get('powerPlayGoals')), pp_opps=num(st.get('powerPlayOpportunities')),
                faceoff_pct=num(st.get('faceoffPercent')), pim=num(st.get('penaltyMinutes')))


def process(sp, e):
    path = SPORTS[sp][0]
    sm = get(f"{BASE}{path}/summary?event={e['id']}")
    if not sm:
        return None
    comp = sm['header']['competitions'][0]
    cs = {c['homeAway']: c for c in comp['competitors']}
    home, away = cs['home'], cs['away']
    hid, aid = home['team']['id'], away['team']['id']
    pc = (sm.get('pickcenter') or [{}])[0]
    detail = comp['status']['type'].get('shortDetail', '')
    g = dict(sport=sp, game_id=e['id'], date=e['date'], week=(e.get('week') or {}).get('number', ''),
             home=home['team']['displayName'], away=away['team']['displayName'],
             home_abbr=home['team']['abbreviation'], away_abbr=away['team']['abbreviation'],
             home_score=int(float(home.get('score', 0))), away_score=int(float(away.get('score', 0))),
             extra='OT' if 'OT' in detail or 'SO' in detail else '',
             spread_detail=pc.get('details', ''), over_under=pc.get('overUnder', ''),
             home_ml=(pc.get('homeTeamOdds') or {}).get('moneyLine', ''), away_ml=(pc.get('awayTeamOdds') or {}).get('moneyLine', ''),
             venue=(sm.get('gameInfo') or {}).get('venue', {}).get('fullName', ''))
    names = {hid: g['home'], aid: g['away']}
    teams = []
    for t in sm['boxscore']['teams']:
        tid = t['team']['id']; own = tid == hid
        r = dict(sport=sp, game_id=e['id'], date=e['date'], team=names[tid], opp=names[aid if own else hid],
                 home=1 if own else 0, pts_for=g['home_score'] if own else g['away_score'],
                 pts_against=g['away_score'] if own else g['home_score'])
        r.update(team_row(sp, t)); teams.append(r)
    players = []
    for pl in sm['boxscore'].get('players', []):
        tid = pl['team']['id']; tname = names.get(tid, pl['team']['displayName']); opp = names[aid if tid == hid else hid]
        acc = {}
        for grp in pl.get('statistics', []):
            keys = grp.get('keys') or grp.get('names') or []
            gname = grp.get('name')
            for a in grp.get('athletes', []):
                ath = a['athlete']; pid = ath['id']
                p = acc.setdefault(pid, dict(sport=sp, game_id=e['id'], date=e['date'], team=tname, opp=opp,
                                             player_id=pid, name=ath['displayName'],
                                             pos=(ath.get('position') or {}).get('abbreviation', '')))
                st = dict(zip(keys, a.get('stats', [])))
                if sp == 'nfl':
                    if gname == 'passing':
                        c, at = pair(st.get('completions/passingAttempts'))
                        p.update(pass_cmp=c, pass_att=at, pass_yds=num(st.get('passingYards')), pass_td=num(st.get('passingTouchdowns')), ints=num(st.get('interceptions')))
                    elif gname == 'rushing':
                        p.update(rush_att=num(st.get('rushingAttempts')), rush_yds=num(st.get('rushingYards')), rush_td=num(st.get('rushingTouchdowns')))
                    elif gname == 'receiving':
                        p.update(rec=num(st.get('receptions')), rec_yds=num(st.get('receivingYards')), rec_td=num(st.get('receivingTouchdowns')), targets=num(st.get('receivingTargets')))
                    elif gname == 'kickReturns':
                        p['kr_td'] = num(st.get('kickReturnTouchdowns'))
                    elif gname == 'puntReturns':
                        p['pr_td'] = num(st.get('puntReturnTouchdowns'))
                    elif gname == 'interceptions':
                        p['def_td'] = p.get('def_td', 0) + num(st.get('interceptionTouchdowns'))
                    elif gname == 'defensive':
                        p['def_td'] = p.get('def_td', 0) + num(st.get('defensiveTouchdowns'))
                        p.update(tackles=num(st.get('totalTackles')), sacks=num(st.get('sacks')))
                    elif gname == 'kicking':
                        m, at = pair(st.get('fieldGoalsMade/fieldGoalAttempts')); p.update(fg_made=m, fg_att=at)
                else:
                    if gname == 'goalies':
                        p.update(pos='G', saves=num(st.get('saves')), shots_against=num(st.get('shotsAgainst')),
                                 goals_against=num(st.get('goalsAgainst')), toi=round(tof(st.get('timeOnIce')), 1))
                    else:
                        p.update(pos=p['pos'] or ('D' if gname == 'defenses' else 'F'), goals=num(st.get('goals')), assists=num(st.get('assists')),
                                 shots=num(st.get('shotsTotal')), hits=num(st.get('hits')), blocks=num(st.get('blockedShots')),
                                 plus_minus=num(st.get('plusMinus')), toi=round(tof(st.get('timeOnIce')), 1),
                                 pp_toi=round(tof(st.get('powerPlayTimeOnIce')), 1))
        for p in acc.values():
            if sp == 'nfl':
                p['tot_td'] = p.get('rush_td', 0) + p.get('rec_td', 0) + p.get('kr_td', 0) + p.get('pr_td', 0)
                if not any(p.get(k) for k in ('pass_att', 'rush_att', 'rec', 'targets', 'fg_att', 'tot_td', 'def_td')):
                    continue
            players.append(p)
    return g, teams, players


def write(path, rows, cols):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore'); w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, 0 if c not in ('pos', 'name', 'team', 'opp', 'date') else '') for c in cols})


meta = {'built_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'source': 'ESPN public JSON (site.api.espn.com)'}
for sp in SPORTS:
    evs = events_for(sp)
    final = [e for e in evs.values() if e['status']['type']['completed'] and e.get('season', {}).get('type') == 2]
    upcoming = [e for e in evs.values() if not e['status']['type']['completed'] and e.get('season', {}).get('type') == 2]
    with cf.ThreadPoolExecutor(6) as ex:
        res = [r for r in ex.map(lambda e: process(sp, e), final) if r]
    games = sorted((r[0] for r in res), key=lambda g: g['date'])
    teams = [t for r in res for t in r[1]]; players = [p for r in res for p in r[2]]
    gcols = ['sport', 'game_id', 'date', 'week', 'home', 'away', 'home_abbr', 'away_abbr', 'home_score', 'away_score', 'extra', 'spread_detail', 'over_under', 'home_ml', 'away_ml', 'venue']
    base_t = ['sport', 'game_id', 'date', 'team', 'opp', 'home', 'pts_for', 'pts_against']
    if sp == 'nfl':
        tcols = base_t + ['first_downs', 'total_yards', 'plays', 'pass_yds', 'pass_cmp', 'pass_att', 'rush_yds', 'rush_att', 'sacks_taken', 'turnovers', 'penalties', 'poss_min', 'third_made', 'third_att']
        pcols = ['sport', 'game_id', 'date', 'team', 'opp', 'player_id', 'name', 'pos', 'pass_cmp', 'pass_att', 'pass_yds', 'pass_td', 'ints', 'rush_att', 'rush_yds', 'rush_td', 'targets', 'rec', 'rec_yds', 'rec_td', 'kr_td', 'pr_td', 'def_td', 'tot_td', 'tackles', 'sacks', 'fg_made', 'fg_att']
    else:
        tcols = base_t + ['shots', 'hits', 'blocks', 'takeaways', 'giveaways', 'pp_goals', 'pp_opps', 'faceoff_pct', 'pim']
        pcols = ['sport', 'game_id', 'date', 'team', 'opp', 'player_id', 'name', 'pos', 'toi', 'pp_toi', 'goals', 'assists', 'shots', 'hits', 'blocks', 'plus_minus', 'saves', 'shots_against', 'goals_against']
    write(os.path.join(OUT, f'{sp}_games.csv'), games, gcols)
    write(os.path.join(OUT, f'{sp}_team_games.csv'), teams, tcols)
    write(os.path.join(OUT, f'{sp}_player_games.csv'), players, pcols)
    # upcoming slate with market lines (scoreboard odds)
    up = []
    for e in sorted(upcoming, key=lambda e: e['date']):
        c = e['competitions'][0]; cs = {x['homeAway']: x for x in c['competitors']}
        od = (c.get('odds') or [{}])[0]
        up.append(dict(sport=sp, game_id=e['id'], date=e['date'], home=cs['home']['team']['displayName'], away=cs['away']['team']['displayName'],
                       spread_detail=od.get('details', ''), over_under=od.get('overUnder', ''),
                       home_ml=((od.get('moneyline') or {}).get('home') or {}).get('close', {}).get('odds', '') if isinstance(od.get('moneyline'), dict) else '',
                       away_ml=((od.get('moneyline') or {}).get('away') or {}).get('close', {}).get('odds', '') if isinstance(od.get('moneyline'), dict) else ''))
    write(os.path.join(OUT, f'{sp}_upcoming.csv'), up, ['sport', 'game_id', 'date', 'home', 'away', 'spread_detail', 'over_under', 'home_ml', 'away_ml'])
    meta[sp] = dict(games=len(games), team_rows=len(teams), player_rows=len(players), upcoming=len(up),
                    first=games[0]['date'][:10], last=games[-1]['date'][:10])
    print(sp, meta[sp])
json.dump(meta, open(os.path.join(OUT, 'meta.json'), 'w'), indent=1)

# ---- team colours (used for the abbreviation badges; no logos) ----
def write_teams(out):
    rows = []
    for sp, path in (('nfl', 'football/nfl'), ('nhl', 'hockey/nhl')):
        d = get(f"{BASE}{path}/teams?limit=100") or {}
        for t in d.get('sports', [{}])[0].get('leagues', [{}])[0].get('teams', []):
            t = t['team']
            rows.append(dict(sport=sp, name=t.get('displayName', ''), abbr=t.get('abbreviation', ''), color=t.get('color', ''), alt=t.get('alternateColor', '')))
    write(os.path.join(out, 'teams.csv'), rows, ['sport', 'name', 'abbr', 'color', 'alt'])
    return len(rows)


print('teams', write_teams(OUT))


# ---- injuries (ESPN) and NHL starting goalies (Daily Faceoff) ----
def write_injuries(out):
    rows = []
    for sp, path in (('nfl', 'football/nfl'), ('nhl', 'hockey/nhl')):
        d = get(f"{BASE}{path}/injuries") or {}
        for t in d.get('injuries', []):
            for i in t.get('injuries', []):
                a = i.get('athlete', {})
                rows.append(dict(sport=sp, team=t.get('displayName', ''), name=a.get('displayName', ''), pos=(a.get('position') or {}).get('abbreviation', ''),
                                 status=i.get('status', ''), date=i.get('date', ''), comment=(i.get('shortComment') or '').replace('\n', ' ')[:220]))
    write(os.path.join(out, 'injuries.csv'), rows, ['sport', 'team', 'name', 'pos', 'status', 'date', 'comment'])
    return len(rows)


def write_goalies(out, days=4):
    rows = []
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-5))).date()
    for k in range(days):
        day = today + datetime.timedelta(days=k)
        try:
            req = urllib.request.Request(f"https://www.dailyfaceoff.com/starting-goalies/{day:%Y-%m-%d}", headers=H)
            html = urllib.request.urlopen(req, timeout=40).read().decode('utf8', 'ignore')
            i = html.find('__NEXT_DATA__'); j = html[html.find('>', i) + 1: html.find('</script>', i)]
            data = json.loads(j)['props']['pageProps'].get('data') or []
        except Exception:
            data = []
        for g in data:
            rows.append(dict(date=str(day), home=g.get('homeTeamName', ''), away=g.get('awayTeamName', ''),
                             home_goalie=g.get('homeGoalieName', '') or '', home_status=g.get('homeNewsStrengthName', '') or '',
                             away_goalie=g.get('awayGoalieName', '') or '', away_status=g.get('awayNewsStrengthName', '') or ''))
    write(os.path.join(out, 'goalies.csv'), rows, ['date', 'home', 'away', 'home_goalie', 'home_status', 'away_goalie', 'away_status'])
    return len(rows)


print('injuries', write_injuries(OUT))
print('goalies', write_goalies(OUT))



# ---- DraftKings player props via ESPN's core odds API (provider 100) ----
DK_MAP = {
    'nfl': {'Anytime Touchdown Scorer': ('atd', 'any'), 'Receiving Yards Milestones': ('rec_yds', 'ms'), 'Receptions Milestones': ('rec', 'ms'),
            'Rushing Yards Milestones': ('rush_yds', 'ms'), 'Passing Yards Milestones': ('pass_yds', 'ms'), 'Passing Touchdown Milestones': ('pass_td', 'ms'),
            'Rushing + Receiving Yards Milestones': ('rushrec_yds', 'ms'),
            'Total Receiving Yards (incl. overtime)': ('rec_yds', 'ou'), 'Total Receptions (incl. overtime)': ('rec', 'ou'), 'Total Rushing Yards (incl. overtime)': ('rush_yds', 'ou'),
            'Total Passing Yards (incl. overtime)': ('pass_yds', 'ou'), 'Total Rushing Plus Receiving Yards (incl. overtime)': ('rushrec_yds', 'ou'), 'Total Passing Touchdowns (incl. overtime)': ('pass_td', 'ou')},
    'nhl': {'Anytime Goalscorer': ('atg', 'any'), 'Points Milestones': ('points', 'ms'), 'Shots on Goal Milestones': ('shots', 'ms'), 'Goalkeeper Saves Milestones': ('saves', 'ms'),
            'Total Points': ('points', 'ou'), 'Total Shots on Goal': ('shots', 'ou'), 'Total Saves': ('saves', 'ou')}}


def write_dk_props(out):
    rows = []
    for sp, lg, path in (('nfl', 'football', 'nfl'), ('nhl', 'hockey', 'nhl')):
        up = list(csv.DictReader(open(os.path.join(out, f'{sp}_upcoming.csv'), encoding='utf-8')))
        up.sort(key=lambda g: g['date'])
        for g in up[: (16 if sp == 'nfl' else 30)]:
            eid = g['game_id']; page = 1
            while True:
                d = get(f"https://sports.core.api.espn.com/v2/sports/{lg}/leagues/{path}/events/{eid}/competitions/{eid}/odds/100/propBets?limit=1000&page={page}") or {}
                for i in d.get('items', []):
                    m = re.search(r'athletes/(\d+)', (i.get('athlete') or {}).get('$ref', ''))
                    t = (i.get('type') or {}).get('name', '')
                    if not m or t not in DK_MAP[sp]:
                        continue
                    key, kind = DK_MAP[sp][t]
                    tgt = ((i.get('current') or {}).get('target') or {}).get('value')
                    odds = (((i.get('odds') or {}).get('american') or {}).get('value')) or ''
                    rows.append(dict(sport=sp, game_id=eid, athlete_id=m.group(1), key=key, kind=kind, line='' if tgt is None else tgt, odds=odds))
                if page >= int(d.get('pageCount') or 1):
                    break
                page += 1
    write(os.path.join(out, 'dk_props.csv'), rows, ['sport', 'game_id', 'athlete_id', 'key', 'kind', 'line', 'odds'])
    return len(rows)


print('dk props', write_dk_props(OUT))
