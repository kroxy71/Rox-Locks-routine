#!/usr/bin/env python3
"""Shared by tracker.py and publish.py: turn picks.json "parlays" into data/history.json entries."""


def parlay_entries(d):
    """History entries for the parlays in a picks.json (whole tickets; their legs are graded together)."""
    out = []
    for pl in d.get('parlays', []):
        legs = [dict(lg) for lg in pl.get('legs', []) if lg.get('t')]
        if len(legs) < 2 or pl.get('early'):
            continue
        sps = sorted({(lg.get('sp') or '').lower() for lg in legs} - {''})
        for lg in legs:
            lg['sp'] = (lg.get('sp') or (sps[0] if len(sps) == 1 else '')).lower()
        o = {'t': 'parlay', 'd': d.get('date'), 'sp': sps[0] if len(sps) == 1 else 'multi',
             'conv': pl.get('conv', 'High'), 'src': pl.get('src', 'spoken'), 'title': pl.get('title', ''),
             'odds': pl.get('odds', ''), 'at': pl.get('at', ''), 'legs': legs}
        out.append(o)
    return out
