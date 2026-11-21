#!/usr/bin/env python3
"""Publish a sent email (and its slips / picks / state) to the public repo in one commit.

Usage (run from a clone of kroxy71/Rox-Locks-routine, GITHUB_TOKEN in the environment):
  python3 routine/publish.py --web OUT/web.json [--id MESSAGE_ID]
        [--picks picks.json] [--slipdir DIR] [--reported OUT/reported.json]
        [--videos v1,v2] [--partial] [--kcbets picks.json] [--dry]

  --web       web.json written by render_picks.py / render_results.py
  --id        the Gmail message id that send_message returned (else kind-UTC time)
  --picks     picks.json of this email: its slips go to data/slips.json, its kc objects to data/history.json
  --slipdir   folder holding slip_<YYYY-MM-DD>_<mm-ss>.jpg crops (copied to slips/)
  --reported  list of pick keys a results email reported (added to data/state.json "reported")
  --videos    Twitch video ids now fully covered (added to data/state.json "videos"); skipped with --partial
  --kcbets    picks.json (after gather.py show): the computer's KingCap paper bets go into data/bot.json (kcbets.py)
  --dry       change the files but do not commit or push

Changes only data/emails.json, data/slips.json, data/history.json, data/state.json, data/bot.json (--kcbets) and slips/*.jpg.
Scrubs email addresses and keys. Never prints the token.
"""
import argparse
import base64
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATA = os.path.join(REPO, 'data')
MAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][a-z]{2,}')
SECRET = re.compile(r'(sk_live|github_pat_|ghp_)[A-Za-z0-9_]*')


def scrub(s):
    if not isinstance(s, str):
        return s
    return SECRET.sub('', MAIL.sub('', s))


def load(name, default):
    try:
        return json.load(open(os.path.join(DATA, name), encoding='utf-8'))
    except Exception:
        return default


def save(name, obj):
    with open(os.path.join(DATA, name), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))


def git(*args, token=False, check=True):
    cmd = ['git']
    if token:
        tok = os.environ.get('GITHUB_TOKEN', '')
        if not tok:
            raise RuntimeError('no GITHUB_TOKEN')
        b = base64.b64encode(('x-access-token:%s' % tok).encode()).decode()
        cmd += ['-c', 'http.extraHeader=Authorization: Basic %s' % b]
    cmd += list(args)
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, encoding='utf-8')
    if check and r.returncode:
        err = (r.stderr or r.stdout).replace(os.environ.get('GITHUB_TOKEN', '@@none@@'), '***')
        raise RuntimeError('git %s failed: %s' % (args[0], err.strip()[-300:]))
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--web')
    ap.add_argument('--id', default='')
    ap.add_argument('--picks')
    ap.add_argument('--slipdir')
    ap.add_argument('--reported')
    ap.add_argument('--videos', default='')
    ap.add_argument('--partial', action='store_true')
    ap.add_argument('--kcbets')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    now = datetime.datetime.now(datetime.timezone.utc)

    if not a.dry:
        git('pull', '-q', '--rebase', 'origin', 'main', token=True)

    # 1. the email
    if a.web:
        w = json.load(open(a.web, encoding='utf-8'))
        mid = re.sub(r'[^A-Za-z0-9]', '', a.id) or (w['kind'] + now.strftime('%Y%m%d%H%M%S'))
        entry = {'id': mid, 'kind': w['kind'], 'subject': scrub(w['subject']), 'sent': w['sent'],
                 'html': scrub(w.get('html', '')), 'text': scrub(w.get('text', ''))}
        emails = [e for e in load('emails.json', []) if e.get('id') != mid]
        emails.append(entry)
        emails.sort(key=lambda e: e['sent'])
        save('emails.json', emails[-120:])
        print('email added:', mid, w['kind'])

    # 2. slips and history from picks.json
    if a.picks:
        d = json.load(open(a.picks, encoding='utf-8'))
        slips = load('slips.json', [])
        for s in d.get('slips', []):
            t = s['t']
            img = ''
            if a.slipdir:
                name = 'slip_%s_%s.jpg' % (d['date'], t.replace(':', '-'))
                src = os.path.join(a.slipdir, name)
                if os.path.exists(src):
                    os.makedirs(os.path.join(REPO, 'slips'), exist_ok=True)
                    img = 'slips/%s_%s.jpg' % (d['date'], t.replace(':', '-'))
                    shutil.copy(src, os.path.join(REPO, img))
            legs = [{'sp': (lg.get('sp') or '').upper(),
                     'text': scrub(lg['text'] + ((' · ' + lg['odds']) if lg.get('odds') else ''))}
                    for lg in s.get('legs', [])]
            obj = {'date': d['date'], 't': t, 'book': s.get('book', ''), 'title': s.get('title', ''),
                   'odds': s.get('odds', 'unreadable'), 'wager': s.get('wager', 'no wager entered'),
                   'link': s.get('link', ''), 'legs': legs, 'note': s.get('note', ''), 'img': img,
                   'live_odds': s.get('live_odds', ''), 'pays10': s.get('pays10', ''),
                   'odds_at': s.get('odds_at', ''), 'flags': s.get('flags', '')}
            slips = [x for x in slips if not (x.get('date') == d['date'] and x.get('t') == t)]
            slips.append(obj)
        slips.sort(key=lambda x: (x.get('date', ''), x.get('t', '')))
        save('slips.json', slips)
        hist = load('history.json', [])
        seen = {json.dumps(h, sort_keys=True) for h in hist}
        added = 0
        for p in d.get('picks', []):
            if not p.get('kc') or p.get('lean') or (p.get('early_dup') or p.get('early')):
                continue
            o = dict(p['kc'])
            o.setdefault('d', d['date'])
            o.setdefault('sp', (p['sp'] or '').lower())
            o.setdefault('conv', p.get('conv', 'Medium'))
            k = json.dumps(o, sort_keys=True)
            if k not in seen:
                seen.add(k)
                hist.append(o)
                added += 1
        sys.path.insert(0, HERE)
        from parlays import parlay_entries
        nparl = 0
        for o in parlay_entries(d):
            k = json.dumps(o, sort_keys=True)
            if k not in seen:
                seen.add(k)
                hist.append(o)
                nparl += 1
        save('history.json', hist)
        print('slips:', len(d.get('slips', [])), 'history picks added:', added, 'parlays added:', nparl)

    # 3. state
    if a.reported or a.videos:
        st = load('state.json', {})
        st.setdefault('reported', [])
        st.setdefault('videos', [])
        if a.reported:
            for k in json.load(open(a.reported, encoding='utf-8')):
                if k not in st['reported']:
                    st['reported'].append(k)
            st['reported'] = st['reported'][-1500:]
        if a.videos and not a.partial:
            for v in a.videos.split(','):
                v = v.strip()
                if v and v not in st['videos']:
                    st['videos'].append(v)
            st['videos'] = st['videos'][-200:]
        save('state.json', st)

    # 4. the computer's KingCap paper bets (never stops the publish if it fails)
    if a.kcbets:
        r = subprocess.run([sys.executable, os.path.join(HERE, 'kcbets.py'), a.kcbets] + (['--dry'] if a.dry else []),
                           cwd=REPO, capture_output=True, text=True, encoding='utf-8')
        print((r.stdout or r.stderr or 'kcbets: no output').strip()[-600:])

    if a.dry:
        print('dry run: nothing committed')
        return
    git('config', 'user.name', 'Rox Locks routine')
    git('config', 'user.email', 'kroxy71@users.noreply.github.com')
    git('add', '-A', 'data', 'slips')
    if git('diff', '--cached', '--quiet', check=False).returncode == 0:
        print('nothing-to-push')
        return
    git('commit', '-q', '-m', 'Update %s' % now.strftime('%Y-%m-%dT%H:%MZ'))
    try:
        git('push', '-q', 'origin', 'HEAD:main', token=True)
    except RuntimeError:
        git('pull', '-q', '--rebase', 'origin', 'main', token=True)
        git('push', '-q', 'origin', 'HEAD:main', token=True)
    print('push-ok')


if __name__ == '__main__':
    try:
        main()
    except Exception as ex:   # never leak anything else
        print('publish failed:', str(ex)[:300])
        sys.exit(1)
