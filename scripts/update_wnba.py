"""Incrementally collect verified WNBA box scores for followed players.
Unofficial ESPN endpoint; availability and reuse permissions are not guaranteed.
"""
import datetime as dt, json, time, urllib.request, os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data'/'wnba.json'
BASE='https://site.api.espn.com/apis/site/v2/sports/basketball/wnba'
TARGETS=['Isobel Borlase','Jade Melbourne','Nyadiew Puoch']
def get(path):
    req=urllib.request.Request(BASE+path,headers={'User-Agent':'CourtsidePersonalTracker/2.0','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=20) as r:return json.load(r)
def main():
    old={}
    if OUT.exists():
        try:old=json.loads(OUT.read_text())
        except (ValueError,OSError):pass
    games={str(g['id'])+'|'+g['player']:g for g in old.get('games',[]) if g.get('id') and g.get('player')}
    upcoming={}
    errors=[];success=0
    today=dt.datetime.now(dt.timezone.utc).date()
    # WNBA is seasonal. Keep accumulated history between runs and across seasons.
    # Full season once on demand; subsequent scheduled runs stay lightweight.
    # Set COURTSIDE_WNBA_BACKFILL=1 in workflow dispatch to force a rescan.
    backfill=os.getenv('COURTSIDE_WNBA_BACKFILL')=='1'
    start=dt.date(today.year, 5, 1) if backfill else today-dt.timedelta(days=21)
    end=today+dt.timedelta(days=21)
    days=(end-start).days+1
    print('WNBA date range:',start,end,'days:',days)
    for offset in range(days):
        day=start+dt.timedelta(days=offset)
        try:
            data=get('/scoreboard?dates='+day.strftime('%Y%m%d')+'&limit=100');success+=1
            for event in data.get('events',[]):
                comp=(event.get('competitions') or [{}])[0]
                sides=comp.get('competitors') or []
                if len(sides)<2:continue
                status=event.get('status',{}).get('type',{}).get('state')
                eid=str(event.get('id'))
                if status=='pre':
                    # Without a confirmed active roster, these are league fixtures, not player fixtures.
                    continue
                if status!='post':continue
                if all(eid+'|'+p in games for p in TARGETS):continue
                try:
                    detail=get('/summary?event='+eid)
                    for group in detail.get('boxscore',{}).get('players',[]):
                        team=group.get('team',{})
                        team_id=str(team.get('id',''))
                        ours=next((x for x in sides if str(x.get('team',{}).get('id',''))==team_id),None)
                        other=next((x for x in sides if x is not ours),None)
                        for section in group.get('statistics',[]):
                            labels=section.get('labels',[])
                            for row in section.get('athletes',[]):
                                name=row.get('athlete',{}).get('displayName','')
                                target=next((p for p in TARGETS if p.casefold()==name.casefold()),None)
                                if not target:continue
                                stats=dict(zip(labels,row.get('stats',[]))) if row.get('stats') else None
                                games[eid+'|'+target]={
                                    'id':eid,'player':target,'league':'WNBA','date':event.get('date'),
                                    'team':team.get('displayName') or team.get('name'),
                                    'opponent':other.get('team',{}).get('displayName') if other else 'Unknown',
                                    'teamScore':ours.get('score') if ours else None,
                                    'opponentScore':other.get('score') if other else None,
                                    'home':ours.get('homeAway')=='home' if ours else None,
                                    'status':'post','stats':stats,
                                     'headshot':(row.get('athlete',{}).get('headshot') or {}).get('href'),
                                     'athleteId':str(row.get('athlete',{}).get('id') or '')}
                    time.sleep(.1)
                except Exception as e:errors.append('summary '+eid+': '+str(e)[:90])
            time.sleep(.1)
        except Exception as e:errors.append(str(day)+': '+str(e)[:90])
    result={'source':'ESPN WNBA endpoints (unofficial)','players':TARGETS,
            'updatedAt':dt.datetime.now(dt.timezone.utc).isoformat() if success else old.get('updatedAt'),
            'games':sorted(games.values(),key=lambda g:g.get('date') or '',reverse=True),
            'upcoming':list(upcoming.values()),'warnings':errors[:10],
            'successful':success>0,'backfill':backfill,'note':'WNBA future player fixtures require roster verification; no guesses are made.'}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print('WNBA scoreboards:',success,'matched game logs:',len(games),'errors:',len(errors))
    if not success:raise SystemExit('No successful WNBA scoreboard requests')
if __name__=='__main__':main()
