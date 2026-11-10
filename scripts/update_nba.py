"""Fetch Josh Giddey NBA game logs and Chicago Bulls fixtures from ESPN's public endpoints.
Unofficial endpoint: availability and usage terms may change. Never manufacture statistics.
"""
import datetime as dt, json, os, time, urllib.request
from pathlib import Path
BASE='https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
OUT=Path(__file__).resolve().parents[1]/'data'/'nba.json'
NAME='Josh Giddey'; TEAM='CHI'
def fetch(path):
    req=urllib.request.Request(BASE+path,headers={'User-Agent':'CourtsidePersonalTracker/1.0','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=18) as response: return json.load(response)
def iso(ts):
    return ts if ts else None
def main():
    today=dt.datetime.now(dt.timezone.utc).date()
    previous={}
    if OUT.exists():
        try: previous=json.loads(OUT.read_text())
        except Exception: pass
    logs={g['id']:g for g in previous.get('games',[]) if g.get('id')}
    fixtures={}
    errors=[]
    # One scoreboard call per day; incremental history extends with every daily run.
    for offset in range(-15,16):
        date=today+dt.timedelta(days=offset)
        try:
            data=fetch('/scoreboard?dates='+date.strftime('%Y%m%d')+'&limit=100')
            for event in data.get('events',[]):
                comps=event.get('competitions',[])
                if not comps: continue
                comp=comps[0]; teams=comp.get('competitors',[])
                ours=next((t for t in teams if t.get('team',{}).get('abbreviation')==TEAM),None)
                if not ours: continue
                other=next((t for t in teams if t is not ours),None)
                if not other: continue
                state=event.get('status',{}).get('type',{}).get('state','unknown')
                item={'id':str(event['id']),'date':iso(event.get('date')),'opponent':other.get('team',{}).get('displayName','Unknown'),
                      'home':ours.get('homeAway')=='home','team':'Chicago Bulls','league':'NBA','status':state,
                      'teamScore':ours.get('score') if state=='post' else None,'opponentScore':other.get('score') if state=='post' else None}
                if state=='pre': fixtures[item['id']]=item
                elif state=='post':
                    if item['id'] in logs and logs[item['id']].get('stats'):
                        continue
                    try:
                        summary=fetch('/summary?event='+item['id'])
                        stats=None
                        for group in summary.get('boxscore',{}).get('players',[]):
                            if group.get('team',{}).get('abbreviation')!=TEAM: continue
                            for category in group.get('statistics',[]):
                                labels=category.get('labels',[])
                                for athlete in category.get('athletes',[]):
                                    who=athlete.get('athlete',{}).get('displayName','')
                                    if who.casefold()!=NAME.casefold(): continue
                                    vals=athlete.get('stats',[])
                                    stats=dict(zip(labels,vals)) if vals else None
                        item['stats']=stats
                    except Exception as exc: errors.append('boxscore '+item['id']+': '+str(exc)[:100]);item['stats']=None
                    logs[item['id']]=item
                time.sleep(.08)
        except Exception as exc: errors.append(str(date)+': '+str(exc)[:120])
    games=sorted(logs.values(),key=lambda x:x.get('date') or '',reverse=True)
    upcoming=sorted(fixtures.values(),key=lambda x:x.get('date') or '')
    # Keep previous data if a temporary outage occurs; flag freshness honestly.
    result={'source':'ESPN public NBA endpoints (unofficial)','player':'Josh Giddey','team':'Chicago Bulls',
            'updatedAt':dt.datetime.now(dt.timezone.utc).isoformat(),'games':games,'upcoming':upcoming,
            'warnings':errors[:8],'successful':len(errors)<31}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print('Games:',len(games),'Upcoming:',len(upcoming),'Errors:',len(errors))
    if len(errors)>=31: raise SystemExit('All scoreboard requests failed; no reliable update')
if __name__=='__main__': main()
