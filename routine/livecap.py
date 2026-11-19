#!/usr/bin/env python3
"""Record KingCap's live audio in 5-minute pieces and transcribe each piece while the stream is still running,
so only the last few minutes are left to do when it ends.  Run it in the background:

  nohup $PY routine/livecap.py watch --out /tmp/kc --until 21:30 > /tmp/kc/livecap.log 2>&1 &

Files in --out (default /tmp/kc):
  cap/status.json      {"state": waiting|live|ended|none, ...} - poll this
  cap/live.txt         transcript so far, lines "[mm:ss] text", mm:ss = time in the Twitch video
  cap/seg_*.aac        the audio pieces (deleted when transcribed unless --keep)
  cap/DONE             written when the stream has ended and every piece is transcribed

Other commands:
  livecap.py fill VIDEO_ID --out /tmp/kc    transcribe the part of the video before the recording began (and any gap)
                                            then writes <out>/<VIDEO_ID>.txt = fill + live, sorted
  livecap.py vod VIDEO_ID --out /tmp/kc     transcribe a whole archived video (fallback when no live capture exists)

Needs (in the venv): yt-dlp imageio-ffmpeg faster-whisper numpy.  Times: --until is Eastern HH:MM.
"""
import argparse
import datetime
import glob
import json
import os
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
CHANNEL = 'https://www.twitch.tv/kingcap702'
SEG = 300
PROMPT = ('Sports betting live stream. Picks, spreads, moneyline, over/under, parlay, PRA, props, units. '
          'NFL, college football, NBA, NHL, UFC names.')


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def ytdlp(*args, timeout=90):
    r = subprocess.run([sys.executable, '-m', 'yt_dlp'] + list(args), capture_output=True, text=True, timeout=timeout,
                       encoding='utf-8', errors='replace')
    return (r.stdout + r.stderr).strip()


def live_info():
    """-> (url, stream_epoch) when live, else (None, None)."""
    o = ytdlp('--skip-download', '--print', '%(timestamp)s', CHANNEL)
    last = o.splitlines()[-1] if o else ''
    if 'not currently live' in o or not last.strip().isdigit():
        return None, None
    u = ytdlp('-g', '-f', 'audio_only/worst', CHANNEL)
    url = [x for x in u.splitlines() if x.startswith('http')]
    return (url[0], int(last)) if url else (None, None)


def mmss(sec):
    sec = int(sec)
    return '%02d:%02d' % (sec // 60, sec % 60) if sec < 3600 else '%d:%02d:%02d' % (sec // 3600, sec % 3600 // 60, sec % 60)


class Transcriber:
    def __init__(self):
        import numpy as np
        from faster_whisper import WhisperModel, BatchedInferencePipeline
        self.np = np
        m = WhisperModel('small.en', device='cpu', compute_type='int8', cpu_threads=os.cpu_count() or 4)
        self.pipe = BatchedInferencePipeline(model=m)

    def run(self, path, base, sink):
        """Transcribe one audio file; time of each line = base + position."""
        r = subprocess.run([ffmpeg(), '-nostdin', '-loglevel', 'error', '-i', path, '-f', 's16le', '-ac', '1', '-ar', '16000', '-'],
                           capture_output=True)
        if not r.stdout:
            return 0
        audio = self.np.frombuffer(r.stdout, dtype=self.np.int16).astype(self.np.float32) / 32768
        segs, _ = self.pipe.transcribe(audio, batch_size=8, beam_size=5, vad_filter=True, initial_prompt=PROMPT)
        n = 0
        for s in segs:
            t = s.text.strip()
            if t:
                sink.write('[%s] %s\n' % (mmss(base + s.start), t))
                n += 1
        sink.flush()
        return n


def status(cap, **kw):
    kw['updated'] = int(time.time())
    json.dump(kw, open(os.path.join(cap, 'status.json'), 'w'))


def until_epoch(hhmm):
    h, m = [int(x) for x in hhmm.split(':')]
    now = datetime.datetime.now(ET)
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return t.timestamp()


def watch(a):
    cap = os.path.join(a.out, 'cap')
    os.makedirs(cap, exist_ok=True)
    for f in glob.glob(os.path.join(cap, 'seg_*')) + [os.path.join(cap, 'DONE')]:
        try:
            os.remove(f)
        except OSError:
            pass
    live_txt = open(os.path.join(cap, 'live.txt'), 'a', encoding='utf-8')
    deadline = until_epoch(a.until) if a.until else time.time() + 5 * 3600
    max_wait = time.time() + a.max_hours * 3600
    status(cap, state='waiting')
    tr = None
    runs = []            # (run_offset_seconds, first_index, last_index)
    seg_done = set()
    idx = 0
    stream_epoch = None
    ever_live = False
    while True:
        url, ep = live_info() if a.source is None else (a.source, int(time.time()))
        if not url:
            if ever_live:
                break                      # was live, now offline: the stream ended
            if time.time() > min(deadline, max_wait):
                status(cap, state='none')
                open(os.path.join(cap, 'DONE'), 'w').write('no stream')
                print('no stream before the limit')
                return
            time.sleep(120)
            continue
        ever_live = True
        if stream_epoch is None:
            stream_epoch = ep
        run_offset = max(0, time.time() - stream_epoch) if a.source is None else 0
        first = idx
        status(cap, state='live', stream_epoch=stream_epoch, first_offset=runs[0][0] if runs else run_offset)
        cmd = [ffmpeg(), '-nostdin', '-loglevel', 'error', '-i', url, '-vn', '-c:a', 'copy', '-f', 'segment',
               '-segment_time', str(SEG), '-segment_format', 'adts', '-segment_start_number', str(idx),
               os.path.join(cap, 'seg_%04d.aac')]
        proc = subprocess.Popen(cmd)
        if tr is None:
            tr = Transcriber()
        while True:
            alive = proc.poll() is None
            segs = sorted(glob.glob(os.path.join(cap, 'seg_*.aac')))
            nums = [int(os.path.basename(s)[4:8]) for s in segs]
            for n, path in zip(nums, segs):
                if n in seg_done or n < first:
                    continue
                if alive and n == max(nums):
                    continue                # still being written
                base = run_offset + (n - first) * SEG
                try:
                    k = tr.run(path, base, live_txt)
                except Exception as ex:
                    print('transcribe failed for', path, str(ex)[:100])
                    k = 0
                seg_done.add(n)
                print('seg', n, 'lines', k, 'at', mmss(base))
                if not a.keep:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            if not alive:
                break
            time.sleep(15)
        idx = (max(nums) + 1) if nums else idx
        runs.append((run_offset, first, idx - 1))
        status(cap, state='live', stream_epoch=stream_epoch, first_offset=runs[0][0])
        if a.source is not None:
            break
        time.sleep(20)                      # ffmpeg ended: stream over, or a hiccup; the loop checks again
    status(cap, state='ended', stream_epoch=stream_epoch, first_offset=runs[0][0] if runs else 0,
           runs=runs, lines=sum(1 for _ in open(os.path.join(cap, 'live.txt'), encoding='utf-8')))
    open(os.path.join(cap, 'DONE'), 'w').write('ok')
    print('done')


def merge(out, vid):
    cap = os.path.join(out, 'cap')
    lines = []
    for f in ('fill.txt', 'live.txt'):
        p = os.path.join(cap, f)
        if os.path.exists(p):
            lines += [l.rstrip('\n') for l in open(p, encoding='utf-8') if l.strip()]

    def key(l):
        t = l[1:l.index(']')].split(':')
        return sum(int(x) * 60 ** i for i, x in enumerate(reversed(t)))
    lines.sort(key=key)
    open(os.path.join(out, vid + '.txt'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print('transcript:', os.path.join(out, vid + '.txt'), len(lines), 'lines')


def vod_audio(vid, start, length, dest):
    u = ytdlp('-g', '-f', 'audio_only/worst', 'https://www.twitch.tv/videos/' + vid.lstrip('v'))
    url = [x for x in u.splitlines() if x.startswith('http')][0]
    cmd = [ffmpeg(), '-nostdin', '-loglevel', 'error', '-ss', str(start)] + (['-t', str(length)] if length else []) + \
          ['-i', url, '-vn', '-c:a', 'copy', '-f', 'adts', '-y', dest]
    subprocess.run(cmd, check=True, timeout=1500)


def fill(a):
    cap = os.path.join(a.out, 'cap')
    st = json.load(open(os.path.join(cap, 'status.json')))
    missing = int(st.get('first_offset', 0))
    tr = Transcriber()
    if missing > 90:                          # the recording began late: transcribe the start from the archive
        dest = os.path.join(cap, 'fill.aac')
        vod_audio(a.vid, 0, missing + 20, dest)
        with open(os.path.join(cap, 'fill.txt'), 'w', encoding='utf-8') as f:
            tr.run(dest, 0, f)
    # gaps between runs
    runs = st.get('runs') or []
    for i in range(1, len(runs)):
        prev_end = runs[i - 1][0] + (runs[i - 1][2] - runs[i - 1][1] + 1) * SEG
        gap = runs[i][0] - prev_end
        if gap > 90:
            dest = os.path.join(cap, 'gap%d.aac' % i)
            vod_audio(a.vid, int(prev_end), int(gap + 20), dest)
            with open(os.path.join(cap, 'fill.txt'), 'a', encoding='utf-8') as f:
                tr.run(dest, int(prev_end), f)
    merge(a.out, a.vid)


def vod(a):
    cap = os.path.join(a.out, 'cap')
    os.makedirs(cap, exist_ok=True)
    dest = os.path.join(cap, a.vid + '.aac')
    vod_audio(a.vid, 0, 0, dest)
    tr = Transcriber()
    with open(os.path.join(a.out, a.vid + '.txt'), 'w', encoding='utf-8') as f:
        tr.run(dest, 0, f)
    print('transcript:', os.path.join(a.out, a.vid + '.txt'))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    w = sub.add_parser('watch')
    w.add_argument('--out', default='/tmp/kc')
    w.add_argument('--until', default='')
    w.add_argument('--max-hours', type=float, default=5)
    w.add_argument('--source', default=None, help='test only: record this URL instead of the live channel')
    w.add_argument('--keep', action='store_true')
    f = sub.add_parser('fill')
    f.add_argument('vid')
    f.add_argument('--out', default='/tmp/kc')
    v = sub.add_parser('vod')
    v.add_argument('vid')
    v.add_argument('--out', default='/tmp/kc')
    a = ap.parse_args()
    {'watch': watch, 'fill': fill, 'vod': vod}[a.cmd](a)


if __name__ == '__main__':
    main()
