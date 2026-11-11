"""Non-destructive WNBL source diagnostic. No fabricated game records."""
import json
import urllib.request
from pathlib import Path
url='https://prod.rosetta.nbl.com.au/get/wnbl/players/in/season/2027'
req=urllib.request.Request(url,headers={'User-Agent':'Courtside/3.0','Accept':'application/json'})
with urllib.request.urlopen(req,timeout=30) as response:
    obj=json.load(response)
print('Response top-level type:',type(obj).__name__)
if isinstance(obj,dict):
    print('Top-level keys:',list(obj)[:20])
    for key,value in obj.items():
        if isinstance(value,list):
            print('List field:',key,'count:',len(value))
            if value and isinstance(value[0],dict):print('Sample row keys:',list(value[0])[:30])
            for row in value:
                if isinstance(row,dict) and any(name in json.dumps(row).casefold() for name in ['jade melbourne','nyadiew puoch','isobel borlase']):
                    print('Matched roster row:',json.dumps(row,ensure_ascii=False)[:1800])
else: print('List count:',len(obj))
