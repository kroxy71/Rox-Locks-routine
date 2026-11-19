#!/usr/bin/env python3
"""Parlay payout math.  python3 parlay.py -165 +100 -185 [--wager 1500]
Prints the combined American odds, what $10 pays, and what the wager pays (decimal odds multiplied)."""
import sys


def dec(a):
    return 1 + a / 100.0 if a > 0 else 1 + 100.0 / -a


def main():
    args = sys.argv[1:]
    wager = None
    if '--wager' in args:
        i = args.index('--wager')
        wager = float(args[i + 1].replace('$', '').replace(',', ''))
        del args[i:i + 2]
    import re
    legs = []
    for x in args:
        m = re.search(r'[+\-−]?\d+', x.replace(',', ''))
        if not m:
            raise SystemExit('cannot read odds: %r' % x)
        legs.append(int(m.group(0).replace('−', '-')))
    D = 1.0
    for a in legs:
        D *= dec(a)
    am = round((D - 1) * 100) if D >= 2 else round(-100 / (D - 1))
    out = 'Live odds %+d | $10 pays $%s (profit $%s)' % (am, format(round(10 * D, 2), ',.2f'), format(round(10 * (D - 1), 2), ',.2f'))
    if wager:
        out += ' | $%s wager pays $%s' % (format(wager, ',.0f'), format(round(wager * D, 2), ',.2f'))
    print(out + ' | %d legs' % len(legs))


if __name__ == '__main__':
    main()
