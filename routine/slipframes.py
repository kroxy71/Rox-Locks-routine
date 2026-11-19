#!/usr/bin/env python3
"""Find the bet slips KingCap shows on screen.

  python3 routine/slipframes.py sheets VIDEO_ID TRANSCRIPT.txt --out /tmp/kc/fr [--duration SECONDS]
      grabs frames in parallel (no download of the video): a sweep every 3 minutes, every minute in the last 15,
      and 2 frames at every transcript line that talks about a bet; builds labeled 2x2 contact sheets
      sheet_00.jpg, sheet_01.jpg ... in --out.  Look at them with the Read tool (sportsbook slip = selections,
      odds, wager, to-win).  Prints a short index: sheet -> times.
  python3 routine/slipframes.py full VIDEO_ID T1 T2 ... --out /tmp/kc/fr
      full-size frames at those seconds (full_<T>.jpg) so the odds are readable.
  python3 routine/slipframes.py crop full_T.jpg X0,Y0,X1,Y1 --date YYYY-MM-DD --t mm:ss --dest /tmp/kc/slips
      crops to the slip area, scales to ~600 px wide, JPEG under 150 KB -> slip_<date>_<mm-ss>.jpg

Needs yt-dlp, imageio-ffmpeg, pillow in the venv.
"""
import argparse
import concurrent.futures as cf
import os
import re
import subprocess
import sys

KEY = re.compile(r'(?i)bet slip|\bslip\b|ticket|placing|placed|put in|putting in|locked in|i\'m on|my bet|to win|\bunits?\b|'
                 r'wager|let me show|on the screen|draftkings|fanduel|betmgm|caesars|bet365|fanatics|espn bet|hard rock|betrivers|circa|westgate')


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def video_url(vid):
    r = subprocess.run([sys.executable, '-m', 'yt_dlp', '-g', '-f', 'best[height<=720]/best',
                        'https://www.twitch.tv/videos/' + vid.lstrip('v')], capture_output=True, text=True, timeout=120)
    u = [x for x in r.stdout.splitlines() if x.startswith('http')]
    if not u:
        raise SystemExit('no video url: ' + (r.stderr or '')[-200:])
    return u[0]


def grab(url, t, dest, scale=True):
    cmd = [ffmpeg(), '-nostdin', '-loglevel', 'error', '-ss', str(int(t)), '-i', url, '-frames:v', '1']
    if scale:
        cmd += ['-vf', 'scale=480:-1', '-q:v', '4']
    else:
        cmd += ['-q:v', '2']
    subprocess.run(cmd + ['-y', dest], timeout=120)
    return dest if os.path.exists(dest) else None


def secs(stamp):
    p = [int(x) for x in stamp.split(':')]
    return sum(x * 60 ** i for i, x in enumerate(reversed(p)))


def sheets(a):
    from PIL import Image, ImageDraw
    os.makedirs(a.out, exist_ok=True)
    lines = [l for l in open(a.transcript, encoding='utf-8') if l.startswith('[')]
    last = secs(lines[-1][1:lines[-1].index(']')]) + 60 if lines else 0
    dur = a.duration or last
    times = set(range(0, int(dur), 180)) | set(range(max(0, int(dur) - 900), int(dur), 60))
    for l in lines:
        if KEY.search(l):
            t = secs(l[1:l.index(']')])
            times |= {t, t + 15}
    times = sorted(t for t in times if t < dur)
    url = video_url(a.vid)
    paths = {}
    with cf.ThreadPoolExecutor(6) as ex:
        futs = {ex.submit(grab, url, t, os.path.join(a.out, 'f_%05d.jpg' % t)): t for t in times}
        for f in cf.as_completed(futs):
            if f.result():
                paths[futs[f]] = f.result()
    ts = sorted(paths)
    index = []
    for i in range(0, len(ts), 4):
        ch = ts[i:i + 4]
        ims = [Image.open(paths[t]) for t in ch]
        w, h = ims[0].size
        sh = Image.new('RGB', (w * 2, h * 2))
        for j, (t, im) in enumerate(zip(ch, ims)):
            sh.paste(im, ((j % 2) * w, (j // 2) * h))
            ImageDraw.Draw(sh).text(((j % 2) * w + 4, (j // 2) * h + 4), '%d:%02d' % (t // 60, t % 60), fill=(255, 255, 0))
        name = os.path.join(a.out, 'sheet_%02d.jpg' % (i // 4))
        sh.save(name, quality=80)
        index.append('%s: %s' % (os.path.basename(name), ' '.join('%d:%02d' % (t // 60, t % 60) for t in ch)))
    print('%d frames, %d sheets (last sheets = end of stream, where slips usually are)' % (len(ts), len(index)))
    print('\n'.join(index))


def full(a):
    url = video_url(a.vid)
    os.makedirs(a.out, exist_ok=True)
    with cf.ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda t: grab(url, t, os.path.join(a.out, 'full_%d.jpg' % t), scale=False), [int(x) for x in a.times]))
    print('\n'.join(r for r in res if r))


def crop(a):
    from PIL import Image
    im = Image.open(a.image)
    x0, y0, x1, y1 = [int(v) for v in a.box.split(',')]
    im = im.crop((x0, y0, x1, y1))
    w = 600
    im = im.resize((w, max(1, int(im.height * w / im.width))))
    os.makedirs(a.dest, exist_ok=True)
    out = os.path.join(a.dest, 'slip_%s_%s.jpg' % (a.date, a.t.replace(':', '-')))
    q = 72
    while True:
        im.convert('RGB').save(out, quality=q)
        if os.path.getsize(out) < 150000 or q < 40:
            break
        q -= 8
    print(out, os.path.getsize(out))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('sheets')
    s.add_argument('vid')
    s.add_argument('transcript')
    s.add_argument('--out', default='/tmp/kc/fr')
    s.add_argument('--duration', type=int, default=0)
    f = sub.add_parser('full')
    f.add_argument('vid')
    f.add_argument('times', nargs='+')
    f.add_argument('--out', default='/tmp/kc/fr')
    c = sub.add_parser('crop')
    c.add_argument('image')
    c.add_argument('box')
    c.add_argument('--date', required=True)
    c.add_argument('--t', required=True)
    c.add_argument('--dest', default='/tmp/kc/slips')
    a = ap.parse_args()
    {'sheets': sheets, 'full': full, 'crop': crop}[a.cmd](a)


if __name__ == '__main__':
    main()
