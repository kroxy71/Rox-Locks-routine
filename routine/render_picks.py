#!/usr/bin/env python3
"""Render a KingCap picks email from one JSON file, so the HTML, the plain text, the
KCDATA/KCSLIP lines and the site copy always match.

Usage: python3 render_picks.py picks.json outdir
  picks.json  see routine/PROCEDURE.md ("picks.json format")
  outdir      gets subject.txt, email.html, email.txt, web.json (the site copy)

Never needs a network. Pure standard library.
"""
import datetime
import html
import json
import os
import re
import sys

E = html.escape
SPORT_COLOR = {'NFL': '#1A3C8C', 'NHL': '#00838F', 'NBA': '#E65100', 'MLB': '#6A1B9A', 'NCAAF': '#6D4C41'}
SPORT_EMOJI = {'NFL': '\U0001F3C8', 'NCAAF': '\U0001F3C8', 'NHL': '\U0001F3D2', 'NBA': '\U0001F3C0', 'MLB': '⚾'}
OTHER = '#546E7A'
CONV_COLOR = {'High': '#2E7D32', 'Medium': '#B8860B', 'Low': '#C62828'}
CONV_WORD = {'High': 'HIGH', 'Medium': 'MEDIUM', 'Low': 'LOW'}
CONV_SHORT = {'High': 'HIGH', 'Medium': 'MED', 'Low': 'LOW'}
CAT = {'ml': 'Moneyline / spread', 'spread': 'Moneyline / spread', 'h1ml': 'Moneyline / spread',
       'total': 'Over/under', 'atd': 'Anytime TD scorer', 'atg': 'Anytime goal scorer',
       'prop': 'Other player props'}
CAT_ORDER = ['Anytime TD scorer', 'Anytime goal scorer', 'Moneyline / spread', 'Over/under', 'Other player props']
VERDICT_COLOR = {'agrees': '#2E7D32', 'disagrees': '#C62828', 'neutral': '#777'}
WRAP = "font-family:Arial,sans-serif;font-size:14px;color:#222;max-width:680px"


def sp_key(sp):
    s = (sp or '').upper()
    return {'COLLEGE FOOTBALL': 'NCAAF', 'NCAAB': 'NCAAB'}.get(s, s)


def chip(sp):
    k = sp_key(sp)
    col = SPORT_COLOR.get(k, OTHER)
    emo = SPORT_EMOJI.get(k)
    label = (emo + ' ' if emo else '') + k
    return ("<span style='padding:1px 7px;border-radius:4px;font-size:11px;font-weight:bold;color:#fff;"
            "background:%s'>%s</span>" % (col, E(label)))


def badge(conv):
    return ("<span style='padding:2px 8px;border-radius:10px;font-size:12px;font-weight:bold;color:#fff;"
            "background:%s'>%s</span>" % (CONV_COLOR[conv], CONV_WORD[conv]))


def cat_chip(cat):
    return ("<span style='padding:1px 7px;border-radius:4px;font-size:11px;font-weight:bold;color:#37474F;"
            "background:#ECEFF1;border:1px solid #CFD8DC'>%s</span>" % E(cat))


def card(color, inner):
    return ("<div style='border:1px solid #ddd;border-left:5px solid %s;border-radius:8px;padding:10px 12px;"
            "margin:8px 0'>%s</div>" % (color, inner))


def h3(color, text):
    return "<h3 style='color:%s;margin:18px 0 6px'>%s</h3>" % (color, E(text))


def live_line(s):
    """One line from the STEP 5D fields (or a ready-made s['live'] string)."""
    if s.get('live'):
        return s['live']
    if not s.get('live_odds'):
        return ''
    parts = ['Live odds %s' % s['live_odds']]
    if s.get('pays10'):
        parts.append(s['pays10'])
    if s.get('odds_at'):
        parts.append('%s as of %s' % (s.get('odds_src') or 'FanDuel', s['odds_at']))
    if s.get('flags'):
        parts.append(s['flags'])
    return ' · '.join(parts)


def pick_cat(p):
    return p.get('cat') or CAT.get((p.get('kc') or {}).get('t'), 'Other player props')


def verdict_html(v):
    v = (v or 'neutral').lower()
    key = 'agrees' if v.startswith('agree') else 'disagrees' if v.startswith('disagree') else 'neutral'
    word = {'agrees': 'Agrees', 'disagrees': 'Disagrees', 'neutral': 'Neutral'}[key]
    return "<span style='color:%s;font-weight:bold'>%s</span>" % (VERDICT_COLOR[key], word)


def pick_card_html(p):
    sp = sp_key(p['sp'])
    color = SPORT_COLOR.get(sp, OTHER)
    conv = p.get('conf') or p.get('conv', 'Medium')
    title = [chip(sp), '<b>%s</b>' % E(p['bet']), badge(conv)]
    title.append(cat_chip(pick_cat(p)))
    if p.get('shown'):
        title.append("<span style='padding:1px 7px;border-radius:4px;font-size:11px;font-weight:bold;color:#fff;"
                     "background:#2E7D32'>SHOWN ON STREAM</span>")
    if p.get('early'):
        title.append("<span style='padding:1px 7px;border-radius:4px;font-size:11px;font-weight:bold;color:#fff;"
                     "background:#546E7A'>ALREADY SENT EARLY</span>")
    inner = ' '.join(title)
    meta = ' · '.join(x for x in [E(sp), E(p.get('game', '')), E(p.get('time', '')), E(p.get('tv', '')),
                                      E(p.get('line', '')), E(p.get('status', ''))] if x)
    if meta:
        inner += "<div style='font-size:13px;color:#555'>%s</div>" % meta
    if p.get('quote'):
        inner += "<div style='font-size:13px;color:#555'>KingCap: %s</div>" % E(p['quote'])
    sites = p.get('sites') or []
    if sites:
        parts = ['%s - %s - %s' % (E(s[0]), E(s[1]), verdict_html(s[2] if len(s) > 2 else 'neutral')) for s in sites]
        inner += "<div style='font-size:13px;color:#555'>Sites: %s</div>" % '; '.join(parts)
    elif p.get('sites_note'):
        inner += "<div style='font-size:13px;color:#555'>Sites: %s</div>" % E(p['sites_note'])
    if p.get('reason'):
        inner += "<div style='font-size:12px;color:#777'>%s</div>" % E(p['reason'])
    return card(color, inner)


def slip_html(s):
    legs = ''
    for lg in s.get('legs', []):
        legs += '<div>%s %s%s</div>' % (chip(lg.get('sp', '')), E(lg['text']),
                                        (' · ' + E(lg['odds'])) if lg.get('odds') else '')
    head = "<b>%s</b> · [%s] · %s · %s · %s" % (
        E(s.get('book', '')), E(s['t']), E(s.get('title', '')), E(s.get('odds', 'odds unreadable')),
        E(s.get('wager', 'no wager entered')))
    inner = head + legs
    if live_line(s):
        inner += ("<div style='margin:6px 0;padding:6px 8px;background:#E8F5E9;border-radius:6px'>%s</div>"
                  % E(live_line(s)))
    else:
        inner += "<div style='margin:6px 0;padding:6px 8px;border-radius:6px'><i>live odds unavailable</i></div>"
    if s.get('note'):
        inner += "<div style='font-size:12px;color:#777'>%s</div>" % E(s['note'])
    if s.get('link'):
        inner += "<a href='%s'>Watch this slip on stream</a>" % E(s['link'], quote=True)
    return card('#2E7D32', inner)


def pick_text(p):
    sp = sp_key(p['sp'])
    lines = ['[%s] %s - %s' % (sp, p['bet'], CONV_WORD.get(p.get('conf') or p.get('conv', 'Medium'), 'MEDIUM'))]
    lines.append('Category: %s' % pick_cat(p))
    meta = ' | '.join(x for x in [p.get('game', ''), p.get('time', ''), p.get('tv', ''), p.get('line', ''),
                                  p.get('status', '')] if x)
    if meta:
        lines.append(meta)
    if p.get('shown'):
        lines.append('SHOWN ON STREAM')
    if p.get('early'):
        lines.append('ALREADY SENT EARLY')
    if p.get('quote'):
        lines.append('KingCap: %s' % p['quote'])
    sites = p.get('sites') or []
    if sites:
        lines.append('Sites: ' + '; '.join('%s - %s - %s' % (s[0], s[1], (s[2] if len(s) > 2 else 'neutral').capitalize())
                                            for s in sites))
    elif p.get('sites_note'):
        lines.append('Sites: ' + p['sites_note'])
    if p.get('reason'):
        lines.append(p['reason'])
    return '\n'.join(lines)


def cat_rows(picks):
    rows = {}
    for p in picks:
        if p.get('lean'):
            continue
        rows.setdefault(pick_cat(p), []).append(p)
    return [(c, rows[c]) for c in CAT_ORDER if c in rows] + [(c, v) for c, v in rows.items() if c not in CAT_ORDER]


def render(d, tracker_html='', tracker_txt=''):
    date = datetime.date.fromisoformat(d['date'])
    ver = d.get('version') or ''
    subject = "KingCap's Picks for %s" % date.strftime('%A, %b ') + '%d, %d' % (date.day, date.year)
    if ver:
        subject += ' (%s)' % ver
    subject = d.get('subject_prefix', '') + subject
    picks = d.get('picks', [])
    firm = [p for p in picks if not p.get('lean')]
    strong = [p for p in firm if p.get('conv') == 'High']
    also = [p for p in firm if p.get('conv') != 'High']
    order = {'High': 0, 'Medium': 1, 'Low': 2}
    strong.sort(key=lambda p: p.get('sort', ''))
    also.sort(key=lambda p: (order.get(p.get('conv'), 1), p.get('sort', '')))

    h = ["<div style='%s'>" % WRAP]
    intro = d.get('intro', '')
    h.append('<p>%s</p>' % E(intro))
    for n in d.get('notes', []):
        h.append("<p style='color:#555;font-size:13px'>%s</p>" % E(n))
    # category index
    rows = cat_rows(firm)
    if rows:
        h.append(h3('#1565C0', 'PICKS BY CATEGORY'))
        h.append("<table style='border-collapse:collapse;font-size:13px;width:100%'>")
        for c, ps in rows:
            items = '; '.join('%s %s (%s)' % (chip(p['sp']), E(p.get('index') or p['bet']), CONV_SHORT.get(p.get('conv'), 'MED'))
                              for p in ps)
            h.append("<tr><td style='padding:4px 8px 4px 0;vertical-align:top;white-space:nowrap'><b>%s</b> (%d)</td>"
                     "<td style='padding:4px 0'>%s</td></tr>" % (E(c), len(ps), items))
        h.append('</table>')
    slips = d.get('slips', [])
    if slips:
        h.append(h3('#2E7D32', 'PARLAYS HE SHOWED ON STREAM'))
        h.extend(slip_html(s) for s in slips)
    elif d.get('no_slips_note', True):
        h.append("<p style='color:#555;font-size:13px'>No bet slips shown on stream.</p>")
    if strong:
        h.append(h3('#C62828', 'STRONGEST PICKS'))
        h.extend(pick_card_html(p) for p in strong)
    if also:
        h.append(h3('#B8860B', 'ALSO RECOMMENDED'))
        h.extend(pick_card_html(p) for p in also)
    leans = d.get('leans', [])
    if leans:
        h.append(h3('#777', 'LEANS / MENTIONS (no firm pick)'))
        h.append("<ul style='font-size:13px'>%s</ul>" % ''.join('<li>%s</li>' % E(x) for x in leans))
    if tracker_html:
        h.append(tracker_html)
    vids = d.get('videos', [])
    src = ' '.join(E(u) for u in d.get('urls', []))
    foot = ("Confidence = KingCap's conviction combined with agreement from public betting sites; it is not a guarantee. "
            "PRA = points + rebounds + assists. Transcribed automatically, names spelled by ear. Lines move - check your book.")
    if d.get('footer_extra'):
        foot += ' ' + d['footer_extra']
    if src:
        foot += ' Source: ' + src
    last = ('Partial: ' + ','.join(vids)) if ver == 'Early' else ('Videos: ' + ','.join(vids))
    h.append("<p style='color:#777;font-size:12px'>%s<br>%s</p>" % (E(foot), E(last)))
    h.append('</div>')
    html_out = '\n'.join(h)

    # plain text
    t = [intro]
    t.extend(d.get('notes', []))
    t.append('')
    if rows:
        t.append('PICKS BY CATEGORY')
        for c, ps in rows:
            t.append('%s (%d): %s' % (c, len(ps), '; '.join('[%s] %s (%s)' % (sp_key(p['sp']), p.get('index') or p['bet'],
                                                                               CONV_SHORT.get(p.get('conf') or p.get('conv'), 'MED')) for p in ps)))
        t.append('')
    if slips:
        t.append('PARLAYS HE SHOWED ON STREAM')
        for s in slips:
            t.append('%s [%s] %s %s, %s. Legs: %s.%s %s' % (
                s.get('book', ''), s['t'], s.get('title', ''), s.get('odds', 'odds unreadable'),
                s.get('wager', 'no wager entered'),
                '; '.join('[%s] %s%s' % (sp_key(lg.get('sp', '')), lg['text'], (' ' + lg['odds']) if lg.get('odds') else '')
                          for lg in s.get('legs', [])),
                (' ' + live_line(s)) if live_line(s) else ' Live odds unavailable.', s.get('link', '')))
        t.append('')
    else:
        t.append('No bet slips shown on stream.')
        t.append('')
    if leans:
        t.append('LEANS / MENTIONS')
        t.extend('- ' + x for x in leans)
        t.append('')
    if tracker_txt:
        t.append(tracker_txt)
    t.append(foot)
    web_text = '\n'.join(t)
    kc = []
    for p in picks:
        if p.get('kc') and not p.get('lean') and not (p.get('early_dup') or p.get('early')):
            o = dict(p['kc'])
            o.setdefault('d', d['date'])
            o.setdefault('sp', sp_key(p['sp']).lower())
            o.setdefault('conv', p.get('conv', 'Medium'))
            kc.append('KCDATA:' + json.dumps(o, separators=(',', ':'), ensure_ascii=False))
    for s in slips:
        legs = ';;'.join('[%s] %s' % (sp_key(lg.get('sp', '')), lg['text'] + ((' ' + lg['odds']) if lg.get('odds') else ''))
                         for lg in s.get('legs', []))
        kc.append('KCSLIP:%s~%s~%s~%s~%s~%s' % (d['date'], s['t'], s.get('book', ''), s.get('odds', 'unreadable'),
                                                 s.get('link', ''), legs))
    full_text = web_text + '\n' + '\n'.join(kc + [last])
    return subject, html_out, full_text, web_text, kc


def main():
    path, outdir = sys.argv[1], sys.argv[2]
    d = json.load(open(path, encoding='utf-8'))
    here = os.path.dirname(os.path.abspath(__file__))
    th = tt = ''
    if d.get('tracker'):
        tp = d['tracker']
        th = open(os.path.join(tp, 'tracker.html'), encoding='utf-8').read()
        tt = open(os.path.join(tp, 'tracker.txt'), encoding='utf-8').read()
    subject, html_out, full_text, web_text, kc = render(d, th, tt)
    os.makedirs(outdir, exist_ok=True)
    w = lambda n, s: open(os.path.join(outdir, n), 'w', encoding='utf-8', newline='\n').write(s)
    w('subject.txt', subject)
    w('email.html', html_out)
    w('email.txt', full_text)
    sent = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    web = {'kind': 'picks', 'subject': subject, 'sent': sent, 'html': html_out, 'text': web_text}
    w('web.json', json.dumps(web, ensure_ascii=False))
    print('subject:', subject)
    print('html chars:', len(html_out), 'text chars:', len(full_text), 'KC lines:', len(kc))


if __name__ == '__main__':
    main()
