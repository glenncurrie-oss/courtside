#!/usr/bin/env python3
"""Read-only WNBL Game Centre HTML diagnostic. Does not change Courtside data."""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

SCHEDULE = 'https://schedule.wnbl.com.au/wnbl/2026'
# Known public, completed 2026-27 WNBL game page (Sydney v Adelaide).
SAMPLE = ('https://schedule.wnbl.com.au/match?from=%2Fwnbl%2F2026'
          '&league=WNBL&match=69b992d1-7351-11f1-be5e-4906b15ebe56'
          '&scheduleUi=v2&season=3145d6e5-36b0-4646-8bd1-0e422681ead0&year=2026')
TARGETS = ['Jade Melbourne', 'Nyadiew Puoch', 'Isobel Borlase']

class Reader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text=[]; self.links=[]; self.current=None
    def handle_starttag(self, tag, attrs):
        if tag=='a': self.current=dict(attrs).get('href')
    def handle_endtag(self, tag):
        if tag=='a': self.current=None
    def handle_data(self, data):
        s=' '.join(data.split())
        if s:
            self.text.append(s)
            if self.current and '/match?' in self.current:
                self.links.append(self.current)

def check(url):
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; Courtside/1.0; +https://github.com/glenncurrie-oss/courtside)','Accept':'text/html'})
    with urllib.request.urlopen(req,timeout=35) as res:
        body=res.read(3_000_000).decode('utf-8','replace')
        status=res.status
    parser=Reader();parser.feed(body)
    content=' '.join(parser.text)
    return {'httpStatus':status,'htmlBytes':len(body),'visibleTextChars':len(content),
            'hasBoxScoreLabel':bool(re.search(r'Box\s*Score',content,re.I)),
            'hasPlayerStatHeaders':all(re.search(r'\b'+x+r'\b',content,re.I) for x in ('PTS','REB','AST')),
            'hasFullPlayerNames':{name: name.casefold() in content.casefold() for name in TARGETS},
            'matchLinksFound':len(set(parser.links)),
            'sampleMatchLinks':list(dict.fromkeys(parser.links))[:5],
            'textExcerpt':content[:700]}

def main():
    result={'checkedAt':datetime.now(timezone.utc).isoformat(),'purpose':'Read-only HTML accessibility diagnostic; no stats written','checks':{}}
    for label,url in [('completedGame',SAMPLE),('seasonSchedule',SCHEDULE)]:
        try:
            result['checks'][label]=check(url)
        except Exception as exc:
            result['checks'][label]={'error':str(exc),'ok':False}
    out=Path('wnbl-boxscore-diagnostic.json')
    out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2,ensure_ascii=False))
    game=result['checks']['completedGame']
    if not (game.get('hasBoxScoreLabel') and game.get('hasPlayerStatHeaders')):
        print('Game Centre HTML did not expose readable box-score data; inspect diagnostic before building collector.',file=sys.stderr)
        sys.exit(1)
    print('Public game page exposed box-score labels and stat headers. Next step: test parsing player rows and match IDs.')

if __name__=='__main__':main()
