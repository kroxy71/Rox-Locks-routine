#!/usr/bin/env python3
"""Build the results email (morning "Last Night's Results" or a weekend "KingCap Results Update").

Usage: python3 render_results.py graded.json state.json outdir --mode morning|update --today YYYY-MM-DD [--tracker DIR]
  graded.json  written by kctrack.py
  state.json   data/state.json from the repo (list "reported" holds pick keys already sent)
Writes outdir/subject.txt, email.html, email.txt, web.json, reported.json (new keys) and prints a one-line summary.
If nothing is new and mode is update, writes outdir/NOTHING and sends nothing.
"""
import argparse
import datetime
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_picks import (CONV_COLOR, CONV_WORD, SPORT_COLOR, OTHER, WRAP, card, chip, cat_chip, h3, sp_key)  # noqa: E402

E = html.escape
GREEN, RED, GRAY = '#2E7D32', '#C62828', '#777'


def key_of(p):
    name = p.get('player') or p.get('team') or '/'.join(p.get('teams') or [])
    return '%s|%s|%s|%s' % (p['d'], p['t'], name, p.get('stat') or '')


def title_of(p):
    t = p['t']
    if t == 'atg':
        return '%s anytime goal' % p['player']
    if t == 'atd':
        return '%s anytime TD' % p['player']
    if t == 'prop':
        line = p.get('line')
        return '%s %s %s %s' % (p['player'], (p.get('stat') or '').upper() if p.get('stat') == 'pra' else p.get('stat'),
                                p.get('ou', 'over'), ('%g' % line) if line is not None else '')
    if t == 'total':
        line = p.get('line')
        return '%s %s %s' % ('/'.join(p['teams']), p.get('ou', 'over'), ('%g' % line) if line is not None else '')
    if t == 'h1ml':
        return '%s 1st half over %s' % (p['team'], p.get('opp', ''))
    if t == 'spread':
        line = p.get('line')
        return '%s %s' % (p['team'], ('%+g' % line) if line is not None else 'spread')
    return '%s ML' % p['team']


def result_card(p):
    sp = sp_key(p['sp'])
    color = SPORT_COLOR.get(sp, OTHER)
    r = p['result']
    if r == 'WIN':
        res = "<div style='margin-top:3px;color:%s'><b>&#10003; HIT</b> <span style='font-size:12px'>%s</span></div>" % (GREEN, E(p.get('detail', '')))
    elif r == 'LOSS':
        res = "<div style='margin-top:3px;color:%s'><b>&#10007; MISS</b> <span style='font-size:12px'>%s</span></div>" % (RED, E(p.get('detail', '')))
    else:
        res = "<div style='margin-top:3px;color:%s'><b>%s</b> <span style='font-size:12px'>%s</span></div>" % (GRAY, E(r), E(p.get('detail', '')))
    conv = p.get('conv', 'Medium')
    inner = '%s <b>%s</b> <span style=\'padding:2px 8px;border-radius:10px;font-size:12px;font-weight:bold;color:#fff;background:%s\'>%s</span> %s%s' % (
        chip(sp), E(title_of(p)), CONV_COLOR.get(conv, '#B8860B'), CONV_WORD.get(conv, 'MEDIUM'), cat_chip(p.get('cat', '')), res)
    return card(color, inner)


def txt_line(p):
    word = {'WIN': 'HIT', 'LOSS': 'MISS'}.get(p['result'], p['result'])
    return '[%s] %s - %s (%s)' % (sp_key(p['sp']), title_of(p), word, p.get('detail', ''))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('graded')
    ap.add_argument('state')
    ap.add_argument('outdir')
    ap.add_argument('--mode', choices=['morning', 'update'], required=True)
    ap.add_argument('--today', required=True)
    ap.add_argument('--tracker', default='')
    ap.add_argument('--time', default='')
    a = ap.parse_args()
    G = json.load(open(a.graded, encoding='utf-8'))
    try:
        reported = set(json.load(open(a.state, encoding='utf-8')).get('reported', []))
    except Exception:
        reported = set()
    today = datetime.date.fromisoformat(a.today)
    cutoff = (today - datetime.timedelta(days=3)).isoformat()
    live = [p for p in G if not p.get('res')]
    fin = [p for p in live if p['d'] >= cutoff and p['result'] in ('WIN', 'LOSS', 'PUSH', 'VOID')]
    new = [p for p in fin if key_of(p) not in reported]
    pending = [p for p in live if p['d'] >= cutoff and p['result'] == 'PENDING']
    noline = [p for p in live if p['d'] >= cutoff and p['result'] == 'NOLINE']
    os.makedirs(a.outdir, exist_ok=True)
    w = lambda n, s: open(os.path.join(a.outdir, n), 'w', encoding='utf-8', newline='\n').write(s)
    if not new and a.mode == 'update':
        w('NOTHING', 'No new results')
        print('No new results')
        return
    th = tt = ''
    if a.tracker:
        th = open(os.path.join(a.tracker, 'tracker.html'), encoding='utf-8').read()
        tt = open(os.path.join(a.tracker, 'tracker.txt'), encoding='utf-8').read()
    hits = [p for p in new if p['result'] == 'WIN']
    miss = [p for p in new if p['result'] == 'LOSS']
    other = [p for p in new if p['result'] in ('PUSH', 'VOID')]
    ds = lambda d: datetime.date.fromisoformat(d)
    if a.mode == 'morning':
        subject = "Last Night's Results"
        head = "Last Night's Results"
    else:
        d = today
        subject = 'KingCap Results Update - %s %d/%d, %s' % (d.strftime('%a'), d.month, d.day, a.time or '')
        subject = subject.rstrip(', ')
        head = 'KingCap Results Update'
    summary = '%d picks just finished: %d HIT, %d MISS%s.' % (
        len(new), len(hits), len(miss), (', %d push/void' % len(other)) if other else '')
    h = ["<div style='%s'>" % WRAP, "<p><b style='font-size:17px'>%s</b></p>" % E(head)]
    t = [head, '']
    if new:
        h.append('<p>%s</p>' % E(summary))
        t.append(summary)
        by_date = {}
        for p in new:
            by_date.setdefault(p['d'], []).append(p)
        for d in sorted(by_date, reverse=True):
            h.append(h3('#1565C0', ds(d).strftime('%A, %b ') + str(ds(d).day)))
            t.append('')
            t.append(ds(d).strftime('%A, %b ') + str(ds(d).day))
            grp = sorted(by_date[d], key=lambda p: {'WIN': 0, 'LOSS': 1}.get(p['result'], 2))
            for p in grp:
                h.append(result_card(p))
                t.append(txt_line(p))
    else:
        h.append('<p>No new results since the last update.</p>')
        t.append('No new results since the last update.')
    if a.mode == 'morning':
        y = (today - datetime.timedelta(days=1)).isoformat()
        yp = [p for p in live if p['d'] == y]
        h.append(h3('#AD1457', 'YESTERDAY SCORECARD'))
        t.append('')
        t.append('YESTERDAY SCORECARD')
        if not yp:
            h.append('<p>No picks yesterday.</p>')
            t.append('No picks yesterday.')
        else:
            yw = sum(p['result'] == 'WIN' for p in yp)
            yl = sum(p['result'] == 'LOSS' for p in yp)
            yd = sum(p['result'] == 'PENDING' for p in yp)
            line = 'Yesterday: %d hit, %d miss, %d pending' % (yw, yl, yd)
            h.append('<p><b>%s</b></p>' % E(line))
            t.append(line)
            for p in sorted(yp, key=lambda p: {'WIN': 0, 'LOSS': 1, 'PUSH': 2, 'VOID': 2}.get(p['result'], 3)):
                if p['result'] in ('WIN', 'LOSS', 'PUSH', 'VOID'):
                    h.append(result_card(p))
                    t.append(txt_line(p))
    status = 'Still pending: %d picks' % len(pending)
    if noline:
        status += ' | Not gradeable (no line stated): %d' % len(noline)
    h.append("<p style='color:#555;font-size:13px'>%s</p>" % E(status))
    t.extend(['', status])
    if th:
        h.append(th)
        t.extend(['', tt])
    h.append('</div>')
    html_out = '\n'.join(h)
    text_out = '\n'.join(t)
    keys = [key_of(p) for p in new]
    full = text_out + '\n' + '\n'.join('KCRES:' + k for k in keys)
    sent = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    w('subject.txt', subject)
    w('email.html', html_out)
    w('email.txt', full)
    w('web.json', json.dumps({'kind': 'results', 'subject': subject, 'sent': sent, 'html': html_out, 'text': text_out}, ensure_ascii=False))
    w('reported.json', json.dumps(keys))
    print('Sent-ready results: %d hit, %d miss%s | subject: %s' % (len(hits), len(miss), (', %d push/void' % len(other)) if other else '', subject))


if __name__ == '__main__':
    main()
