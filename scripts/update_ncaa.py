"""Courtside NCAA MBB/WBB pilot. Uses unofficial ESPN endpoints.
Only records athlete lines that match the configured full name exactly.
"""
import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {'mens-college-basketball': ['Dallas Loughridge'],
           'womens-college-basketball': ['Monique Bobongie', 'Dallas Loughridge']}
# Target names are searched independently in each league; no league is inferred from gender/name.

def get(url):
    request = urllib.request.Request(url, headers={'User-Agent':'Courtside/3.0 (personal basketball tracker)', 'Accept':'application/json'})
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)

def collect(league, targets, backfill=False):
    out = ROOT / 'data' / ('ncaa_mbb.json' if league.startswith('mens-') else 'ncaa_wbb.json')
    old = json.loads(out.read_text()) if out.exists() else {}
    games = {(str(g.get('id')), g.get('player')):g for g in old.get('games', [])}
    today = dt.datetime.now(dt.timezone.utc).date()
    start = dt.date(today.year, 10, 1) if backfill and today.month >= 10 else (dt.date(today.year-1, 10, 1) if backfill else today-dt.timedelta(days=10))
    end = today + dt.timedelta(days=10)
    base = 'https://site.api.espn.com/apis/site/v2/sports/basketball/' + league
    successes = 0; errors=[]; matches=0
    for offset in range((end-start).days+1):
        date = start + dt.timedelta(days=offset)
        try:
            board = get(base+'/scoreboard?'+urllib.parse.urlencode({'dates':date.strftime('%Y%m%d'),'limit':500,'groups':50}))
            successes += 1
            for event in board.get('events',[]):
                if event.get('status',{}).get('type',{}).get('state') != 'post': continue
                eid = str(event.get('id',''))
                if not eid: continue
                if all((eid,p) in games for p in targets): continue
                try:
                    detail = get(base+'/summary?event='+urllib.parse.quote(eid))
                    sides = (event.get('competitions') or [{}])[0].get('competitors',[])
                    for group in detail.get('boxscore',{}).get('players',[]):
                        team = group.get('team') or {}; teamid=str(team.get('id',''))
                        ours=next((s for s in sides if str(s.get('team',{}).get('id',''))==teamid),None)
                        opponent=next((s for s in sides if s is not ours),None)
                        for section in group.get('statistics',[]):
                            labels=section.get('labels') or []
                            for row in section.get('athletes',[]):
                                athlete=row.get('athlete') or {}; name=athlete.get('displayName','')
                                target=next((p for p in targets if p.casefold()==name.casefold()),None)
                                if not target: continue
                                values=row.get('stats') or []
                                if not values: continue
                                games[(eid,target)]={'id':eid,'player':target,'league':'NCAA MBB' if league.startswith('mens-') else 'NCAA WBB',
                                    'date':event.get('date'),'team':team.get('displayName') or team.get('name'),
                                    'opponent':(opponent or {}).get('team',{}).get('displayName','Unknown'),
                                    'teamScore':(ours or {}).get('score'),'opponentScore':(opponent or {}).get('score'),
                                    'home':(ours or {}).get('homeAway')=='home','status':'post',
                                    'stats':dict(zip(labels,values)), 'athleteId':str(athlete.get('id') or ''),
                                    'headshot':(athlete.get('headshot') or {}).get('href')}
                                matches+=1
                    time.sleep(.05)
                except Exception as exc: errors.append('summary '+eid+': '+str(exc)[:110])
            time.sleep(.05)
        except Exception as exc: errors.append(str(date)+': '+str(exc)[:110])
    if not successes: raise RuntimeError('No successful scoreboard requests for '+league)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({'source':'ESPN NCAA endpoints (unofficial)','updatedAt':dt.datetime.now(dt.timezone.utc).isoformat(),
        'players':targets,'games':sorted(games.values(),key=lambda g:g.get('date') or '',reverse=True),
        'upcoming':[],'warnings':errors[:20], 'successful':True,'backfill':backfill},indent=2)+'\n')
    print(league, 'successful days',successes,'new matches',matches,'total games',len(games),'errors',len(errors))

if __name__=='__main__':
    backfill=os.environ.get('COURTSIDE_NCAA_BACKFILL')=='1'
    failures=[]
    for league,targets in TARGETS.items():
        try: collect(league,targets,backfill)
        except Exception as exc: print('FAILED',league,exc);failures.append(league)
    if failures: raise SystemExit('Failed NCAA leagues: '+', '.join(failures))
