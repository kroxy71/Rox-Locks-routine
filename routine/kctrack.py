#!/usr/bin/env python3
"""KingCap tracker: grade picks with ESPN data and build the accuracy tracker.
Usage: python3 kctrack.py history.json [outdir]   -> writes tracker.html, tracker.txt, graded.json (and a cache/ folder) into outdir."""
import json,os,re,sys,html,unicodedata,difflib,datetime,collections,urllib.request
HERE=os.path.abspath(sys.argv[2]) if len(sys.argv)>2 else os.path.dirname(os.path.abspath(__file__))
CACHE=os.path.join(HERE,'cache')
os.makedirs(CACHE,exist_ok=True)
BASE='https://site.api.espn.com/apis/site/v2/sports/'
PATH={'nfl':'football/nfl','ncaaf':'football/college-football','nba':'basketball/nba',
  'nhl':'hockey/nhl','mlb':'baseball/mlb'}
EXTRA={'ncaaf':'&groups=80&limit=300'}
CAT={'ml':'Moneyline / spread','spread':'Moneyline / spread','h1ml':'Moneyline / spread',
 'total':'Over/under','atd':'Anytime TD scorer','atg':'Anytime goal scorer',
 'prop':'Other player props'}
CAT_ORDER=['Anytime TD scorer','Anytime goal scorer','Moneyline / spread','Over/under','Other player props']
SPORT={'nfl':'NFL','ncaaf':'College football','nba':'NBA','nhl':'NHL','mlb':'MLB'}
RES={'W':'WIN','L':'LOSS','P':'PUSH','V':'VOID','N':'NOLINE'}
GREEN,RED,GRAY='#2E7D32','#C62828','#777'
TBL="border-collapse:collapse;width:100%;max-width:380px;table-layout:fixed;font-size:13px"
CW=['58%','21%','21%']
def get(url):
 fp=os.path.join(CACHE,re.sub(r'[^A-Za-z0-9]','_',url)[-180:]+'.json')
 if os.path.exists(fp):
  return json.load(open(fp,encoding='utf8'))
 d=json.load(urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=40))
 json.dump(d,open(fp,'w',encoding='utf8'))
 return d
def norm(s):
 s=unicodedata.normalize('NFKD',s or '').encode('ascii','ignore').decode().lower()
 return re.sub(r'[^a-z0-9 ]','',s).strip()
def events(sp,date):
 d1=date.replace('-','')
 d2=(datetime.date.fromisoformat(date)+datetime.timedelta(days=1)).strftime('%Y%m%d')
 out={}
 for dd in(d1,d2):
  try:
   s=get(f"{BASE}{PATH[sp]}/scoreboard?dates={dd}{EXTRA.get(sp, '')}")
  except Exception:
   continue
  for e in s.get('events',[]):
   e['_q']=dd
   out.setdefault(e['id'],e)
 return list(out.values())
def tmatch(name,comp):
 n=norm(name)
 t=comp['team']
 c=[norm(t.get(k))for k in('displayName','location','shortDisplayName','name','abbreviation')]
 return bool(n)and any(n==x or(len(n)>3 and n in x)for x in c if x)
def find_event(sp,date,teams):
 best=None
 for e in events(sp,date):
  comps=e['competitions'][0]['competitors']
  if all(any(tmatch(t,c)for c in comps)for t in teams if t):
   if best is None or e['_q']==date.replace('-',''):
    best=e
 return best
def summary(sp,eid):
 return get(f"{BASE}{PATH[sp]}/summary?event={eid}")
def odds(e,sp):
 o=e['competitions'][0].get('odds')or[]
 if o:
  return o[0].get('overUnder'),o[0].get('details')
 try:
  pc=summary(sp,e['id']).get('pickcenter')or[]
  if pc:
   return pc[0].get('overUnder'),pc[0].get('details')
 except Exception:
  pass
 return None,None
def athletes(sp,eid):
 for t in summary(sp,eid).get('boxscore',{}).get('players',[]):
  for grp in t.get('statistics',[]):
   keys=grp.get('keys')or grp.get('names')or[]
   for a in grp.get('athletes',[]):
    yield t['team']['displayName'],a['athlete']['displayName'],dict(zip(keys,a.get('stats',[]))),grp.get('name','')
def find_player(sp,date,player,team):
 n=norm(player)
 hits=[]
 for e in events(sp,date):
  comps=e['competitions'][0]['competitors']
  if team and not any(tmatch(team,c)for c in comps):
   continue
  try:
   for tn,name,st,g in athletes(sp,e['id']):
    nn=norm(name)
    r=difflib.SequenceMatcher(None,n,nn).ratio()
    if r>0.82 or(n.split()[-1]==nn.split()[-1]and r>0.6):
     hits.append((r,e,tn,name,st,g))
  except Exception:
   continue
 return hits
def num(x):
 try:
  return float(str(x).split('-')[0])
 except Exception:
  return 0.0
def grade(p):
 sp,t=p['sp'],p['t']
 try:
  if t in('ml','spread','h1ml'):
   e=find_event(sp,p['d'],[p['team'],p.get('opp')])
   if not e:
    return 'UNKNOWN','game not found'
   if not e['status']['type'].get('completed'):
    return 'PENDING','not final'
   comps=e['competitions'][0]['competitors']
   mine=next(c for c in comps if tmatch(p['team'],c))
   oth=next(c for c in comps if c is not mine)
   ms,os_=float(mine['score']),float(oth['score'])
   if t=='h1ml':
    a=sum(float(x['value'])for x in mine.get('linescores',[])[:2])
    b=sum(float(x['value'])for x in oth.get('linescores',[])[:2])
    return('WIN' if a>b else 'PUSH' if a==b else 'LOSS'),f"1H {int(a)}-{int(b)} (final {int(ms)}-{int(os_)})"
   if t=='ml':
    return('WIN' if ms>os_ else 'PUSH' if ms==os_ else 'LOSS'),f"{int(ms)}-{int(os_)}"
   line=p.get('line')
   if line is None:
    _,det=odds(e,sp)
    m=re.match(r'([A-Z]+)\s+([+-]?[\d.]+)',det or '')
    if m:
     line=float(m.group(2))if mine['team']['abbreviation']==m.group(1)else-float(m.group(2))
   if line is None:
    return 'NOLINE','no spread available'
   d=ms-os_+line
   return('WIN' if d>0 else 'LOSS' if d<0 else 'PUSH'),f"{line:+g}: {int(ms)}-{int(os_)}"
  if t=='total':
   e=find_event(sp,p['d'],p['teams'])
   if not e:
    return 'UNKNOWN','game not found'
   if not e['status']['type'].get('completed'):
    return 'PENDING','not final'
   tot=sum(float(c['score'])for c in e['competitions'][0]['competitors'])
   line=p.get('line')
   if line is None:
    line,_=odds(e,sp)
   if line is None:
    return 'NOLINE',f'total {int(tot)}, no line available'
   over=p['ou']=='over'
   return('PUSH' if tot==line else 'WIN' if(tot>line)==over else 'LOSS'),f"total {int(tot)} vs {p['ou']} {line:g}"
  if t in('atd','atg','prop'):
   if t=='prop' and p.get('line')is None:
    return 'NOLINE','no line stated'
   hits=find_player(sp,p['d'],p['player'],p.get('team'))
   if not hits:
    return('PENDING' if events(sp,p['d'])and not all(x['status']['type'].get('completed')for x in events(sp,p['d']))else 'VOID'),'player not in box score'
   hits.sort(key=lambda h:-h[0])
   _,e,tn,name,st,g=hits[0]
   if not e['status']['type'].get('completed'):
    return 'PENDING','not final'
   merged={}
   for h in hits:
    if h[3]==name:
     for k,v in h[4].items():
      merged[f"{h[5]}.{k}"]=v
   if t=='atg':
    n=sum(num(v)for k,v in merged.items()if k.endswith('.goals'))
    return('WIN' if n>=1 else 'LOSS'),f"{name}: {int(n)} goal(s)"
   if t=='atd':
    n=sum(num(v)for k,v in merged.items()if 'touchdown' in k.lower()and 'passing' not in k.lower()and 'kicking' not in k.lower())
    return('WIN' if n>=1 else 'LOSS'),f"{name}: {int(n)} TD"
   stat=p['stat']
   if sp=='nba':
    def nb(k):
     return next((num(v)for kk,v in merged.items()if kk.endswith('.'+k)),0.0)
    if nb('minutes')==0:
     return 'VOID',f'{name} DNP'
    pts,reb,ast=nb('points'),nb('rebounds'),nb('assists')
    val={'pra':pts+reb+ast,'pr':pts+reb,'points':pts,'rebounds':reb,'assists':ast,
     'steals':nb('steals'),'blocks':nb('blocks'),
     'threes':nb('threePointFieldGoalsMade-threePointFieldGoalsAttempted')}.get(stat)
   else:
    k={'rushYds':'rushingYards','recYds':'receivingYards','passYds':'passingYards'}.get(stat)
    val=next((num(v)for kk,v in merged.items()if k and kk.endswith('.'+k)),0.0)
   if val is None:
    return 'NOLINE','stat not supported'
   line,over=p['line'],p.get('ou','over')=='over'
   return('PUSH' if val==line else 'WIN' if(val>line)==over else 'LOSS'),f"{name}: {stat} {val:g} vs {p.get('ou', 'over')} {line:g}"
 except Exception as ex:
  return 'ERROR',repr(ex)[:100]
 return 'PENDING',''
def pct(w,l):
 return f"{100 * w / (w + l):.0f}%" if w+l else '-'
def rec(rows):
 return(sum(r['result']=='WIN' for r in rows),sum(r['result']=='LOSS' for r in rows),sum(r['result']=='PUSH' for r in rows))
def dfmt(d):
 x=datetime.date.fromisoformat(d)
 return x.strftime('%a %b ')+str(x.day)
def table(rows,header):
 h=''.join(f"<th style='text-align:{'left' if i == 0 else 'right'};width:{CW[i]};padding:4px 8px;border-bottom:2px solid #ccc;font-size:12px;color:#555'>{c}</th>" for i,c in enumerate(header))
 b=''.join('<tr>'+''.join(f"<td style='text-align:{'left' if i == 0 else 'right'};padding:4px 8px;border-bottom:1px solid #eee'>{c}</td>" for i,c in enumerate(r))+'</tr>' for r in rows)
 return f"<table style='{TBL}'><tr>{h}</tr>{b}</table>"
def main(path):
 hist=json.load(open(path,encoding='utf8'))
 seen,G=set(),[]
 for p in hist:
  key=(p['d'],p['sp'],p['t'],p.get('team'),p.get('player'),tuple(p.get('teams')or[]),p.get('stat'),p.get('ou'))
  if not p.get('res'):
   if key in seen:
    continue
   seen.add(key)
  p['cat']=CAT[p['t']]
  if p.get('res'):
   p['result']=RES.get(p['res'],p['res'])
  else:
   p['result'],p['detail']=grade(p)
  G.append(p)
 graded=[p for p in G if p['result']in('WIN','LOSS','PUSH')]
 pending=[p for p in G if p['result']=='PENDING']
 other=[p for p in G if p['result']in('NOLINE','VOID','UNKNOWN','ERROR')]
 W,L,P=rec(graded)
 dates=sorted({p['d']for p in graded})or[datetime.date.today().isoformat()]
 def rows_by(keyfn,order=None):
  d=collections.defaultdict(list)
  for p in graded:
   d[keyfn(p)].append(p)
  out=[]
  for k in(order or sorted(d,key=lambda k:-len(d[k]))):
   if k in d:
    w,l,ps=rec(d[k])
    good=w+l and w/(w+l)>=.5
    out.append([html.escape(str(k)),f"{w}-{l}"+(f"-{ps}" if ps else ''),f"<b style='color:{GREEN if good else RED}'>{pct(w, l)}</b>",pct(w,l)])
  return out
 h="<h3 style='color:#1565C0;margin:24px 0 6px;border-top:2px solid #1565C0;padding-top:12px'>KINGCAP ACCURACY TRACKER</h3>"
 h+=(f"<p style='margin:4px 0'><b style='font-size:18px'>{W}-{L}"+(f"-{P}" if P else '')+
  f"</b> <span style='font-size:18px;font-weight:bold;color:{GREEN if W >= L else RED}'>({pct(W, L)})</span> "
  f"<span style='color:#555'>on {len(graded)} graded picks, {dfmt(dates[0])} - {dfmt(dates[-1])}</span></p>")
 h+=(f"<p style='margin:2px 0 8px;font-size:12px;color:#777'>{len(pending)} pending, {len(other)} could not be graded. "
  f"Hit rate only - it ignores odds, so it is not profit.</p>")
 t=f"\nKINGCAP ACCURACY TRACKER\nOverall: {W}-{L}"+(f"-{P}" if P else '')+f" ({pct(W, L)}) on {len(graded)} graded picks, {dfmt(dates[0])} - {dfmt(dates[-1])}\n{len(pending)} pending, {len(other)} could not be graded. Hit rate only - ignores odds, not profit.\n"
 def block(title,fn,order,head):
  rows=rows_by(fn,order)
  return(f"<p style='margin:12px 0 2px'><b>{title}</b></p>"+table([r[:3]for r in rows],[head,'W-L','Hit %']),
    f"\n{title}\n"+''.join(f"  {html.unescape(r[0])}: {r[1]} ({r[3]})\n" for r in rows))
 for title,fn,order,head in(("1. By KingCap's conviction",lambda p:p['conv'],['High','Medium','Low'],'Conviction'),
        ("2. By bet type",lambda p:p['cat'],CAT_ORDER,'Bet type')):
  bh,bt=block(title,fn,order,head)
  h+=bh
  t+=bt
 def wk(d):
  x=datetime.date.fromisoformat(d)
  return x-datetime.timedelta(days=(x.weekday()+1)%7)
 weeks=collections.OrderedDict()
 for d in dates:
  weeks.setdefault(wk(d),[]).append(d)
 rows_=''
 t+="\n3. By week, with each day underneath\n"
 for ws in sorted(weeks,reverse=True):
  wp=[p for p in graded if wk(p['d'])==ws]
  w,l,ps=rec(wp)
  we=ws+datetime.timedelta(days=6)
  wl=f"Wk {dfmt(ws.isoformat())[4:]} - {dfmt(we.isoformat())[4:]}"
  rows_+=(f"<tr style='background:#F3F6FA'><td style='padding:5px 8px;border-bottom:1px solid #ddd'><b>{wl}</b></td>"
    f"<td style='text-align:right;padding:5px 8px;border-bottom:1px solid #ddd'><b>{w}-{l}"+(f"-{ps}" if ps else '')+"</b></td>"
    f"<td style='text-align:right;padding:5px 8px;border-bottom:1px solid #ddd'><b>{pct(w, l)}</b></td></tr>")
  t+=f"  {wl}: {w}-{l}"+(f"-{ps}" if ps else '')+f" ({pct(w, l)})\n"
  for d in sorted(weeks[ws],reverse=True):
   dw,dl,dps=rec([p for p in graded if p['d']==d])
   rows_+=(f"<tr><td style='padding:3px 8px 3px 20px;border-bottom:1px solid #eee;color:#555;font-size:12px'>{dfmt(d)}</td>"
     f"<td style='text-align:right;padding:3px 8px;border-bottom:1px solid #eee;color:#555;font-size:12px'>{dw}-{dl}"+(f"-{dps}" if dps else '')+"</td>"
     f"<td style='text-align:right;padding:3px 8px;border-bottom:1px solid #eee;color:#555;font-size:12px'>{pct(dw, dl)}</td></tr>")
   t+=f"      {dfmt(d)}: {dw}-{dl}"+(f"-{dps}" if dps else '')+f" ({pct(dw, dl)})\n"
 h+=("<p style='margin:12px 0 2px'><b>3. By week, with each day underneath</b></p>"
  "<table style='"+TBL+"'><tr>"
  "<th style='text-align:left;width:"+CW[0]+";padding:4px 8px;border-bottom:2px solid #ccc;font-size:12px;color:#555'>Week / day</th>"
  "<th style='text-align:right;width:"+CW[1]+";padding:4px 8px;border-bottom:2px solid #ccc;font-size:12px;color:#555'>W-L</th>"
  "<th style='text-align:right;width:"+CW[2]+";padding:4px 8px;border-bottom:2px solid #ccc;font-size:12px;color:#555'>Hit %</th></tr>"+rows_+"</table>")
 bh,bt=block("4. By sport",lambda p:SPORT[p['sp']],None,'Sport')
 h+=bh
 t+=bt
 h+=("<p style='font-size:12px;color:#777;margin:10px 0'><b>How it is graded.</b> Final scores and box scores come from ESPN. A line KingCap states is used; "
  "when he gives only the bet (for example \"this game goes over\"), the DraftKings closing line from ESPN is used. Moneyline and 1st-half picks are straight up. "
  "Player props are void if the player did not play, and props with no stated line cannot be graded. Only firm picks count; leans and mentions are not graded. "
  "Streams are transcribed automatically, so a few names or numbers may be off.</p>")
 t+="\nHow it is graded: ESPN final scores and box scores; stated lines used, otherwise the ESPN/DraftKings closing line; props with no line are not graded; void if player did not play; only firm picks count.\n"
 open(os.path.join(HERE,'tracker.html'),'w',encoding='utf8').write(h)
 open(os.path.join(HERE,'tracker.txt'),'w',encoding='utf8').write(t)
 json.dump(G,open(os.path.join(HERE,'graded.json'),'w'),indent=1)
 print(t)
if __name__=='__main__':
 main(sys.argv[1])
