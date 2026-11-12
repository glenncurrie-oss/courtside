"""Courtside WNBL 2026-27 diagnostic. Read-only; does not alter game data."""
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = 'https://prod.rosetta.nbl.com.au/get/wnbl'
URLS = {
    'rosters': BASE + '/players/in/season/2027',
    'matches': BASE + '/matches/in/season/2027/regular',
}
NAMES = ('jade melbourne', 'nyadiew puoch', 'isobel borlase')


def get(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; Courtside-WNBL/3.2)',
        'Accept': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.load(response)


def inspect(label, payload):
    print(f'\n=== {label.upper()} ===')
    print('Top-level type:', type(payload).__name__)
    if isinstance(payload, dict):
        print('Top-level keys:', list(payload)[:35])
        for key, value in payload.items():
            if isinstance(value, list):
                print(f'Array {key}: {len(value)} records')
                if value and isinstance(value[0], dict):
                    print('Sample record keys:', list(value[0])[:60])
            elif isinstance(value, dict):
                print(f'Object {key}: keys {list(value)[:30]}')
    elif isinstance(payload, list):
        print('Records:', len(payload))
        if payload and isinstance(payload[0], dict):
            print('Sample record keys:', list(payload[0])[:60])
    matches = []
    def walk(obj, path='$', depth=0):
        if depth > 8 or len(matches) >= 20:
            return
        if isinstance(obj, dict):
            # Avoid dumping the whole dataset or unrelated personal information.
            if any(n in json.dumps(obj, ensure_ascii=False).casefold() for n in NAMES):
                # Show only a few matched record paths and their keys/selected values.
                if any(n in str(obj.get(k, '')).casefold() for k in ('name', 'fullName', 'full_name', 'displayName', 'firstName', 'lastName', 'person')):
                    matches.append((path, list(obj)[:45], {k: str(v)[:100] for k, v in obj.items() if k.lower() in ('id','name','fullname','firstname','lastname','team','teamname','personid','playerid')}))
            for k, v in obj.items():
                if isinstance(v, (list, dict)):
                    walk(v, f'{path}.{k}', depth+1)
        elif isinstance(obj, list):
            for i, v in enumerate(obj[:1200]):
                walk(v, f'{path}[{i}]', depth+1)
    walk(payload)
    print('Direct player-name matches:', len(matches))
    for path, keys, values in matches[:12]:
        print('Matched record:', path, 'keys=', keys, 'identifiers=', values)


def main():
    out = {'checkedAt': datetime.now(timezone.utc).isoformat(), 'checks': {}}
    failures = 0
    for label, url in URLS.items():
        print('\nRequest:', label, url)
        try:
            payload = get(url)
            inspect(label, payload)
            out['checks'][label] = {'ok': True, 'topLevelType': type(payload).__name__, 'topLevelKeys': list(payload)[:35] if isinstance(payload, dict) else None, 'count': len(payload) if isinstance(payload, list) else None}
        except Exception as exc:
            failures += 1
            out['checks'][label] = {'ok': False, 'error': str(exc)[:300]}
            print('FAILED:', type(exc).__name__, str(exc)[:300])
    Path('wnbl-diagnostic.json').write_text(json.dumps(out, indent=2), encoding='utf-8')
    if failures:
        raise SystemExit(f'{failures} WNBL source checks failed; see log and diagnostic artifact')


if __name__ == '__main__':
    main()
