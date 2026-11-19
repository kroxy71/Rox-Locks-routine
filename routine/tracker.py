#!/usr/bin/env python3
"""Build the accuracy tracker.  Usage: python3 tracker.py OUTDIR [picks.json ...]
Combines routine/baseline.json + data/history.json + the kc objects of any picks.json given (today's new picks),
writes OUTDIR/history.json, then runs kctrack.py into OUTDIR (tracker.html, tracker.txt, graded.json).
Run from anywhere; paths are relative to the repo this file lives in."""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
out = os.path.abspath(sys.argv[1])
os.makedirs(out, exist_ok=True)


def load(p, default):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return default


hist = load(os.path.join(HERE, 'baseline.json'), []) + load(os.path.join(REPO, 'data', 'history.json'), [])
for pj in sys.argv[2:]:
    d = load(pj, {})
    for p in d.get('picks', []):
        if p.get('kc') and not p.get('lean') and not (p.get('early_dup') or p.get('early')):
            o = dict(p['kc'])
            o.setdefault('d', d.get('date'))
            o.setdefault('sp', (p['sp'] or '').lower())
            o.setdefault('conv', p.get('conv', 'Medium'))
            hist.append(o)
json.dump(hist, open(os.path.join(out, 'history.json'), 'w', encoding='utf-8'), ensure_ascii=False)
r = subprocess.run([sys.executable, os.path.join(HERE, 'kctrack.py'), os.path.join(out, 'history.json'), out],
                   capture_output=True, text=True, encoding='utf-8')
print(r.stdout[:1500])
if r.returncode:
    print(r.stderr[-800:])
    sys.exit(r.returncode)
