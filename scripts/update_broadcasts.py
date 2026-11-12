#!/usr/bin/env python3
"""Courtside AU NBA broadcast evidence pipeline.

ESPN scoreboard broadcast labels are US-oriented and are NEVER interpreted as
Australian availability. AU listings must be game-specific, manually verified
in data/broadcast_verified_au.json, with a URL and date checked.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'broadcasts_au.json'
VERIFIED = ROOT / 'data' / 'broadcast_verified_au.json'
SCOREBOARD = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard'
ALLOWED = {'Prime Video', 'ESPN', 'Disney+', 'Foxtel', 'Foxtel Now', 'Kayo Sports', 'NBA League Pass', 'SBS', 'SBS On Demand', '9Now'}

def read_json(path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding='utf-8'))

def get_day(day):
    url = f'{SCOREBOARD}?dates={day:%Y%m%d}&limit=100'
    req = urllib.request.Request(url, headers={'User-Agent': 'Courtside-broadcast-collector/1.0', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.load(resp).get('events', [])

def main():
    now = datetime.now(timezone.utc)
    manual = read_json(VERIFIED, {'games': []})
    if not isinstance(manual, dict) or not isinstance(manual.get('games'), list):
        raise ValueError('broadcast_verified_au.json must contain a games array')
    verified = []
    for record in manual['games']:
        if not isinstance(record, dict):
            raise ValueError('Each verified game must be an object')
        providers = record.get('providers', [])
        if not isinstance(providers, list) or not providers or any(p not in ALLOWED for p in providers):
            raise ValueError('Each verified game needs recognised providers')
        if not record.get('sourceUrl') or not str(record['sourceUrl']).startswith('https://') or not record.get('checkedAt'):
            raise ValueError('Verified games require sourceUrl (https) and checkedAt')
        if not (record.get('espnEventId') or (record.get('homeTeam') and record.get('awayTeam') and record.get('date'))):
            raise ValueError('Verified games need espnEventId or both teams and ISO date')
        verified.append({**record, 'league': 'NBA', 'market': 'AU', 'status': 'verified'})
    candidates = []
    errors = []
    for offset in range(0, 8):
        day = (now + timedelta(days=offset)).date()
        try:
            for event in get_day(day):
                comps = event.get('competitions') or []
                if not comps:
                    continue
                comp = comps[0]
                competitors = comp.get('competitors') or []
                home = next((c for c in competitors if c.get('homeAway') == 'home'), {})
                away = next((c for c in competitors if c.get('homeAway') == 'away'), {})
                us = []
                for b in comp.get('broadcasts', []):
                    us.extend(b.get('names') or [])
                candidates.append({
                    'espnEventId': str(event.get('id', '')),
                    'date': event.get('date'),
                    'homeTeam': home.get('team', {}).get('displayName', ''),
                    'awayTeam': away.get('team', {}).get('displayName', ''),
                    'usBroadcastHints': sorted(set(us)),
                    'note': 'US-oriented source; NOT Australian broadcast confirmation',
                })
        except Exception as exc:
            errors.append(f'{day}: {exc}')
    # Preserve previous candidate feed when ESPN is temporarily unavailable.
    if not candidates and OUT.exists():
        old = read_json(OUT, {})
        candidates = old.get('candidates', [])
    result = {
        'market': 'AU', 'league': 'NBA',
        'updatedAt': now.isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'verified': verified, 'candidates': candidates,
        'errors': errors,
        'notes': 'Only verified entries have Australian broadcast providers. ESPN broadcast hints are US-oriented and are never treated as AU confirmations.',
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUT.with_suffix('.tmp')
    temp.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(temp, OUT)
    print(f'AU broadcasts: {len(verified)} verified games; {len(candidates)} NBA schedule candidates; {len(errors)} fetch warnings')
    for error in errors[:3]:
        print('Warning:', error, file=sys.stderr)

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Broadcast collector failed; prior data preserved: {exc}', file=sys.stderr)
        sys.exit(1)
