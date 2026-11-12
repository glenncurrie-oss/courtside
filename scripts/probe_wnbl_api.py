#!/usr/bin/env python3
"""Read-only WNBL match API probe. Writes diagnostics only; never changes Courtside data."""
import json, os, sys, urllib.request, urllib.error
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

URL = 'https://schedule.wnbl.com.au/api/calendar/match?match=69dc4125-7351-11f1-a716-5d1a014d3413&league=wnbl'
OUT = Path('wnbl-api-diagnostic.json')
STATS = {'points','rebounds','assists','minutes','field_goals_attempted','field_goals_made'}

def walk(value, path='$', depth=0):
    if depth > 30: return
    if isinstance(value, dict):
        yield path, value
        for k,v in value.items():
            if isinstance(v, (dict,list)):
                yield from walk(v, path+'.'+str(k), depth+1)
    elif isinstance(value, list):
        for i,v in enumerate(value):
            if isinstance(v, (dict,list)):
                yield from walk(v, path+f'[{i}]', depth+1)

def main():
    report={'checkedAt':datetime.now(timezone.utc).isoformat(), 'url':URL, 'purpose':'Read-only direct API diagnostic'}
    try:
        req=urllib.request.Request(URL,headers={'Accept':'application/json','User-Agent':'Mozilla/5.0 (compatible; CourtsideDiagnostic/1.0)','Referer':'https://schedule.wnbl.com.au/wnbl'})
        with urllib.request.urlopen(req,timeout=25) as res:
            raw=res.read(8_000_000)
            report['httpStatus']=res.status
            report['bytes']=len(raw)
            report['contentType']=res.headers.get('Content-Type')
        data=json.loads(raw)
        report['topLevelType']=type(data).__name__
        report['topLevelKeys']=list(data)[:50] if isinstance(data,dict) else []
        matches=[]
        for path, obj in walk(data):
            if not STATS.intersection(obj): continue
            player=obj.get('player')
            if not isinstance(player,dict): continue
            name=player.get('full_name') or ' '.join(str(player.get(x,'')) for x in ('first_name','last_name')).strip()
            matches.append({'path':path,'player':name,'playerId':player.get('id'), 'externalPlayerId':player.get('external_id'), 'period':obj.get('period'), 'periodType':obj.get('period_type'), 'stats':{k:obj.get(k) for k in sorted(STATS) if k in obj}})
        report['statRecordCount']=len(matches)
        report['periodCounts']=dict(Counter(str(m['period']) for m in matches))
        report['jadeRecords']=[m for m in matches if m['player'].casefold()=='jade melbourne'][:30]
        report['sampleStatRecords']=matches[:5]
        report['statRecordPaths']=list(dict.fromkeys(m['path'].rsplit('[',1)[0] for m in matches))[:15]
        report['note']='Do not sum period rows until full-game and period semantics are confirmed.'
        print(f"HTTP {report['httpStatus']}; {len(matches)} player-stat records; period counts: {report['periodCounts']}")
        print('Jade records:',len(report['jadeRecords']))
        if not matches: report['warning']='No player-stat records found; inspect schema.'
    except urllib.error.HTTPError as e:
        report.update({'httpStatus':e.code,'error':str(e),'responseExcerpt':e.read(400).decode('utf-8','replace')})
    except Exception as e:
        report['error']=f'{type(e).__name__}: {e}'
    OUT.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print('Diagnostic written:',OUT)
    if 'error' in report: print('ERROR:',report['error']);return 1
    return 0

if __name__=='__main__':sys.exit(main())
