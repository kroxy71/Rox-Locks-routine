#!/usr/bin/env python3
"""KingCap tracker: grade picks with ESPN data and build the accuracy tracker.
Usage: python3 kctrack.py history.json [outdir]   -> writes tracker.html, tracker.txt, graded.json (and a cache/ folder) into outdir."""
import json,os,re,sys,html,hashlib,unicodedata,difflib,datetime,collections,urllib.request
HERE=os.path.abspath(sys.argv[2]) if len(sys.argv)>2 else os.path.dirname(os.path.abspath(__file__))
CACHE=os.path.join(HERE,'cache')
os.makedirs(CACHE,exist_ok=True)
BASE='https://site.api.espn.com/apis/site/v2/sports/'
PATH={'nfl':'football/nfl','ncaaf':'football/college-football','nba':'basketball/nba',
  'nhl':'hockey/nhl','mlb':'baseball/mlb'}
EXTRA={'ncaaf':'&groups=80&limit=300'}
CAT={'ml':'Moneyline / spread','spread':'Moneyline / spread','h1ml':'1st Half ML','h1spread':'1st Half spread','h1total':'1st Half total',
 'total':'Over/under','atd':'Anytime TD scorer','atg':'Anytime goal scorer',
 'prop':'Other player props','parlay':'Parlays'}
CAT_ORDER=['Anytime TD scorer','Anytime goal scorer','Moneyline / spread','1st Half ML','1st Half spread','1st Half total','Over/under','Other player props']
SPORT={'nfl':'NFL','ncaaf':'College football','nba':'NBA','nhl':'NHL','mlb':'MLB'}
RES={'W':'WIN','L':'LOSS','P':'PUSH','V':'VOID','N':'NOLINE'}
GREEN,RED,GRAY='#2E7D32','#C62828','#777'
TBL="border-collapse:collapse;width:100%;max-width:380px;table-layout:fixed;font-size:13px"
CW=['58%','21%','21%']
def get(url):
 fp=os.path.join(CACHE,re.sub(r'[^A-Za-z0-9]','_',url)[-60:]+'_'+hashlib.md5(url.encode()).hexdigest()[:10]+'.json')
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
    st=dict(zip(keys,a.get('stats',[])))
    st['_id']=str(a['athlete'].get('id',''))
    yield t['team']['displayName'],a['athlete']['displayName'],st,grp.get('name','')
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
# ---- line fallbacks (same rules as the Rox Locks page): his bet slip that day, then DraftKings' line on ESPN ----
SLIPS=None
SLIP_STAT=[(r'shots?(?:\s+on\s+goal)?|sog','sog'),(r'pra|pts\+reb\+ast','pra'),(r'threes?|3-?pointers?|3pm','threes'),
 (r'steals?','steals'),(r'blocks?','blocks'),(r'rec(?:eiving)? (?:yards|yds)','recYds'),(r'rush(?:ing)? (?:yards|yds)','rushYds'),
 (r'pass(?:ing)? (?:yards|yds)','passYds'),(r'receptions?','rec'),(r'points','points'),(r'rebounds','rebounds'),(r'assists','assists')]
def slip_line(d,player,stat):
 global SLIPS
 if SLIPS is None:
  try:
   SLIPS=json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'data','slips.json'),encoding='utf8'))
  except Exception:
   SLIPS=[]
 words='|'.join(w for w,_ in SLIP_STAT)
 rx=re.compile(r'^(.+?)\s+(\d+)\+\s+('+words+r')\b',re.I)
 for v in SLIPS:
  if v.get('date')!=d:
   continue
  for lg in v.get('legs')or[]:
   t=re.sub(r'\s*\(.*$','',re.sub(r'^SGP:\s*','',str(lg.get('text','')).split(' · ')[0],flags=re.I))
   for part in re.split(r'\s+and\s+',t,flags=re.I):
    m=rx.match(part.strip())
    if not m:
     continue
    sx=next((k for w,k in SLIP_STAT if re.fullmatch(w,m.group(3),re.I)),None)
    a,b=norm(player),norm(m.group(1))
    if sx==stat and(a==b or difflib.SequenceMatcher(None,a,b).ratio()>0.82 or(a.split()[-1:]==b.split()[-1:]and difflib.SequenceMatcher(None,a,b).ratio()>0.6)):
     return int(m.group(2))-0.5
 return None
PROPTYPE={'pra':'90','points':'1','rebounds':'3','assists':'2','threes':'4','steals':'5','blocks':'6'}
MILETYPE={'steals':'222','blocks':'223'}
def dk_line(sp,eid,aid,stat):
 if sp!='nba' or not aid:
  return None
 try:
  items=[]
  for pg in range(1,5):
   j=get(f"https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{eid}/competitions/{eid}/odds/100/propBets?limit=500&page={pg}")
   items+=j.get('items',[])
   if pg>=(j.get('pageCount')or 1):
    break
  mine=[it for it in items if re.search(r'athletes/'+aid+r'\b',(it.get('athlete')or{}).get('$ref',''))]
  if stat in PROPTYPE:
   for it in mine:
    tot=((it.get('odds')or{}).get('total')or{}).get('value')
    if (it.get('type')or{}).get('id')==PROPTYPE[stat] and tot is not None:
     return float(tot)
  if stat in MILETYPE:
   ms=[it for it in mine if (it.get('type')or{}).get('id')==MILETYPE[stat] and re.search(r'\d',((it.get('current')or{}).get('target')or{}).get('displayValue',''))]
   def dec(a):
    return 1+a/100 if a>0 else 1+100/-a if a else 99
   ms.sort(key=lambda it:abs(dec(int(((it.get('odds')or{}).get('american')or{}).get('value')or 0))-2))
   if ms:
    return int(re.match(r'\d+',ms[0]['current']['target']['displayValue']).group())-0.5
 except Exception:
  return None
 return None
def num(x):
 try:
  return float(str(x).split('-')[0])
 except Exception:
  return 0.0
CORE={'nba':'basketball/leagues/nba','nfl':'football/leagues/nfl','ncaaf':'football/leagues/college-football'}
def half(c,sp):
 """1st-half points for one competitor: the first two quarters (college basketball plays halves)."""
 ls=[float(x.get('value',0))for x in c.get('linescores',[])]
 n=1 if sp=='ncaab' else 2
 return sum(ls[:n])if len(ls)>=n else None
def dk_half(sp,e,mk,team_id=None):
 """DraftKings 1st-half line from ESPN (72 = 1st Half Total, 74 = 1st Half Spread); None when ESPN has none."""
 if sp not in CORE:
  return None
 try:
  eid=e['id']
  j=get(f"https://sports.core.api.espn.com/v2/sports/{CORE[sp]}/events/{eid}/competitions/{eid}/odds/100/propBets?limit=500")
  for it in j.get('items',[]):
   if(it.get('type')or{}).get('id')!=mk:
    continue
   if team_id and not re.search(r'/teams/'+str(team_id)+r'\b',(it.get('team')or{}).get('$ref','')):
    continue
   v=((it.get('odds')or{}).get('total')or{}).get('value')
   if v is not None:
    return float(v)
 except Exception:
  return None
 return None
def grade(p):
 sp,t=p['sp'],p['t']
 try:
  if t in('h1spread','h1total'):
   names=[p['team'],p.get('opp')]if t=='h1spread' else p['teams']
   e=find_event(sp,p['d'],names)
   if not e:
    return 'UNKNOWN','game not found'
   comps=e['competitions'][0]['competitors']
   st=e['status']
   if not(st['type'].get('completed')or(st.get('period')or 0)>=(2 if sp=='ncaab' else 3)):
    return 'PENDING','1st half not over'
   if t=='h1spread':
    mine=next(c for c in comps if tmatch(p['team'],c))
    oth=next(c for c in comps if c is not mine)
    a,b=half(mine,sp),half(oth,sp)
    if a is None or b is None:
     return 'UNKNOWN','no quarter scores'
    line,src=p.get('line'),''
    if line is None:
     line,src=dk_half(sp,e,'74',mine['team']['id']),' (DraftKings 1H line)'
    if line is None:
     return 'NOLINE',f"1H {int(a)}-{int(b)}, no line"
    d=a-b+line
    return('WIN' if d>0 else 'LOSS' if d<0 else 'PUSH'),f"1H {line:+g}: {int(a)}-{int(b)}{src}"
   hs=[half(c,sp)for c in comps]
   if None in hs:
    return 'UNKNOWN','no quarter scores'
   tot=sum(hs)
   line,src=p.get('line'),''
   if line is None:
    line,src=dk_half(sp,e,'72'),' (DraftKings 1H line)'
   if line is None:
    return 'NOLINE',f"1H total {int(tot)}, no line"
   over=p.get('ou','over')=='over'
   return('PUSH' if tot==line else 'WIN' if(tot>line)==over else 'LOSS'),f"1H total {int(tot)} vs {p.get('ou','over')} {line:g}{src}"
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
   hits=find_player(sp,p['d'],p['player'],p.get('team'))
   if not hits:
    return('PENDING' if events(sp,p['d'])and not all(x['status']['type'].get('completed')for x in events(sp,p['d']))else 'VOID'),'player not in box score'
   hits.sort(key=lambda h:-h[0])
   _,e,tn,name,st,g=hits[0]
   if not e['status']['type'].get('completed'):
    return 'PENDING','not final'
   merged={}
   merged_id=st.get('_id','')
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
   elif sp=='nhl':
    val={'sog':sum(num(v)for kk,v in merged.items()if kk.endswith('.shotsTotal')),
     'points':sum(num(v)for kk,v in merged.items()if kk.endswith('.goals')or kk.endswith('.assists'))}.get(stat)
   else:
    k={'rushYds':'rushingYards','recYds':'receivingYards','passYds':'passingYards','rec':'receptions'}.get(stat)
    val=next((num(v)for kk,v in merged.items()if k and kk.endswith('.'+k)),0.0)
   if val is None:
    return 'NOLINE','stat not supported'
   line,over,src=p.get('line'),p.get('ou','over')=='over',''
   if line is None:
    line,src=slip_line(p['d'],p['player'],stat),' (from his bet slip)'
   if line is None:
    line,src=dk_line(sp,e['id'],merged_id,stat),' (DraftKings line, none stated)'
   if line is None:
    return 'NOLINE','no line stated'
   return('PUSH' if val==line else 'WIN' if(val>line)==over else 'LOSS'),f"{name}: {stat} {val:g} vs {p.get('ou', 'over')} {line:g}{src}"
 except Exception as ex:
  return 'ERROR',repr(ex)[:100]
 return 'PENDING',''
def grade_parlay(p):
 """A parlay wins only if every leg wins (push legs drop out); any lost leg loses it."""
 rs=[]
 for lg in p.get('legs')or[]:
  q=dict(lg)
  q.setdefault('d',p['d'])
  q['sp']=(q.get('sp')or p.get('sp')or'').lower()
  r,dt=grade(q)if q['sp']in PATH and q.get('t')in CAT and q.get('t')!='parlay' else('NOLINE','leg not gradable')
  rs.append((r,dt))
  lg['result'],lg['detail']=r,dt
 if not rs:
  return 'NOLINE','no legs'
 R=[r for r,_ in rs]
 n=len(R)
 if 'LOSS' in R:
  return 'LOSS',f"{R.count('WIN')} of {n} legs hit"
 if any(r in('PENDING','UNKNOWN','ERROR')for r in R):
  return 'PENDING',f"{R.count('WIN')} of {n} legs hit so far"
 if any(r in('NOLINE',)for r in R):
  return 'NOLINE',f"{R.count('WIN')} of {n} legs hit, {R.count('NOLINE')} could not be graded"
 live=[r for r in R if r!='VOID']
 if not live or all(r=='PUSH' for r in live):
  return 'PUSH','all legs pushed or void'
 return 'WIN',f"all {len([r for r in live if r=='WIN'])} legs hit"+(f" ({n-len([r for r in live if r=='WIN'])} push/void)" if n!=len([r for r in live if r=='WIN']) else '')
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
  key=(p['d'],p['sp'],p['t'],p.get('team'),p.get('player'),tuple(p.get('teams')or[]),p.get('stat'),p.get('ou'),
   json.dumps(p.get('legs'),sort_keys=True)if p['t']=='parlay' else '')
  if not p.get('res'):
   if key in seen:
    continue
   seen.add(key)
  p['cat']=CAT[p['t']]
  if p.get('res'):
   p['result']=RES.get(p['res'],p['res'])
  elif p['t']=='parlay':
   p['result'],p['detail']=grade_parlay(p)
  else:
   p['result'],p['detail']=grade(p)
  G.append(p)
 PL=[p for p in G if p['t']=='parlay']
 S=[p for p in G if p['t']!='parlay']
 graded=[p for p in S if p['result']in('WIN','LOSS','PUSH')]
 pending=[p for p in S if p['result']=='PENDING']
 other=[p for p in S if p['result']in('NOLINE','VOID','UNKNOWN','ERROR')]
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
 if PL:
  pg=[p for p in PL if p['result']in('WIN','LOSS','PUSH')]
  pw,pl_,pp=rec(pg)
  npend=sum(p['result']=='PENDING' for p in PL)
  nng=len(PL)-len(pg)-npend
  summ=f"{pw}-{pl_}"+(f"-{pp}" if pp else '')+f" ({pct(pw, pl_)})"
  h+=(f"<p style='margin:12px 0 2px'><b>5. KingCap parlays</b></p>"
   f"<p style='margin:2px 0;font-size:13px'><b style='color:{GREEN if pw and pw >= pl_ else RED}'>{summ}</b> "
   f"<span style='color:#555'>on {len(pg)} graded parlays ({npend} pending, {nng} could not be graded). Counted as whole tickets, separate from the pick record above.</span></p>")
  prow=[]
  t+=f"\n5. KingCap parlays: {summ} on {len(pg)} graded ({npend} pending, {nng} could not be graded)\n"
  for p in sorted(PL,key=lambda x:(x['d'],x.get('at','')),reverse=True)[:15]:
   nm=p.get('title')or f"{len(p.get('legs')or[])}-leg parlay"
   src='slip' if p.get('src')=='slip' else 'said'
   r=p['result']
   col=GREEN if r=='WIN' else RED if r=='LOSS' else GRAY
   prow.append([f"{dfmt(p['d'])}: {html.escape(nm)}"+(f" {html.escape(p['odds'])}" if p.get('odds') else '')+f" <span style='color:#777;font-size:11px'>({src})</span>",
    html.escape(p.get('detail','')),f"<b style='color:{col}'>{r.title() if r in('WIN','LOSS','PUSH','PENDING') else 'n/a'}</b>"])
   t+=f"  {dfmt(p['d'])}: {nm} {p.get('odds','')} ({src}) - {r} - {p.get('detail','')}\n"
  h+=table(prow,['Parlay','Legs','Result'])
 h+=("<p style='font-size:12px;color:#777;margin:10px 0'><b>How it is graded.</b> Final scores and box scores come from ESPN. A line KingCap states is used; "
  "when he gives only the bet (for example \"this game goes over\"), the DraftKings closing line from ESPN is used. Moneyline and 1st-half picks are straight up. "
  "When he gives no line for a player prop, the line from his bet slip that day is used, else DraftKings' line; props are void if the player did not play. Only firm picks count; leans and mentions are not graded. "
  "Streams are transcribed automatically, so a few names or numbers may be off.</p>")
 t+="\nHow it is graded: ESPN final scores and box scores; stated lines used, otherwise the ESPN/DraftKings closing line; props with no line use his slip's line, else DraftKings'; void if player did not play; only firm picks count.\n"
 open(os.path.join(HERE,'tracker.html'),'w',encoding='utf8').write(h)
 open(os.path.join(HERE,'tracker.txt'),'w',encoding='utf8').write(t)
 json.dump(G,open(os.path.join(HERE,'graded.json'),'w'),indent=1)
 # compact copy for the Rox Locks page (data/graded.json): it shows these grades so the page and the emails agree
 def gkey(p):
  if p['t']=='parlay':
   return '|'.join([p['d'],'parlay',p.get('title')or'',str(p.get('at')or'')])
  return '|'.join(str(x)for x in(p['d'],p['sp'],p['t'],p.get('team')or'',p.get('player')or'','/'.join(p.get('teams')or[]),p.get('stat')or'',p.get('ou')or''))
 mini=[{'k':gkey(p),'d':p['d'],'sp':p['sp'],'t':p['t'],'conv':p.get('conv',''),'r':p['result'],
   **({'stat':p['stat']}if p['t']=='prop' and p.get('stat') else{}),
   **({'legs':[lg.get('result','')for lg in p.get('legs')or[]]}if p['t']=='parlay' else{})}for p in G]
 json.dump({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),'picks':mini},
  open(os.path.join(HERE,'graded_min.json'),'w',encoding='utf8'),ensure_ascii=False,separators=(',',':'))
 print(t)
if __name__=='__main__':
 main(sys.argv[1])
