#!/usr/bin/env python3
"""Courtside WNBL fixture collector. Public fixture feed; no individual box scores."""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

FEED = 'https://fixturedownload.azurewebsites.net/feed/json/wnbl-2026'
OUT = Path(__file__).resolve().parents[1] / 'data' / 'wnbl.json'
# Confirmed target-team associations; team fixtures do not guarantee participation.
TRACKED = {
    'Bendigo Spirit': ['Jade Melbourne', 'Isobel Borlase'],
    'UC Capitals': ['Nyadiew Puoch'],
}

def utc_iso(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Missing DateUtc')
    parsed = datetime.fromisoformat(value.strip().replace(' ', 'T').replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('DateUtc missing timezone')
    return parsed.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')

def main():
    request = urllib.request.Request(FEED, headers={'User-Agent': 'Courtside-fixture-collector/1.0', 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = json.load(response)
    if not isinstance(raw, list) or not raw:
        raise ValueError('Fixture feed empty or not a list; existing data left untouched')
    now = datetime.now(timezone.utc)
    upcoming = []
    seen = set()
    matches = 0
    for match in raw:
        if not isinstance(match, dict):
            continue
        home, away = match.get('HomeTeam'), match.get('AwayTeam')
        if not isinstance(home, str) or not isinstance(away, str):
            continue
        try:
            date = utc_iso(match.get('DateUtc'))
            dt = datetime.fromisoformat(date.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            continue
        matches += 1
        if dt < now:
            continue
        for team in (home, away):
            for player in TRACKED.get(team, []):
                key = (match.get('MatchNumber'), date, home, away, player)
                if key in seen:
                    continue
                seen.add(key)
                upcoming.append({
                    'player': player,
                    'league': 'WNBL',
                    'team': team,
                    'opponent': away if team == home else home,
                    'home': team == home,
                    'date': date,
                    'status': 'Scheduled',
                    'venue': match.get('Location') or '',
                    'round': match.get('RoundNumber'),
                    'matchNumber': match.get('MatchNumber'),
                    'broadcast': {'providers': ['9Now', 'Disney+'], 'note': 'League-wide Australian coverage; verify specific stream'},
                })
    if matches < 10:
        raise ValueError(f'Only {matches} valid matches; refusing to overwrite existing data')
    upcoming.sort(key=lambda x: (x['date'], x['player']))
    # Preserve existing verified game records, if added by a future collector.
    existing_games = []
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text(encoding='utf-8'))
            if isinstance(previous.get('games'), list):
                existing_games = previous['games']
        except (OSError, ValueError, AttributeError):
            pass
    output = {
        'league': 'WNBL',
        'season': '2026-27',
        'updatedAt': now.isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'source': FEED,
        'games': existing_games,
        'upcoming': upcoming,
        'notes': 'Team fixtures only. Player participation not guaranteed. Individual WNBL box scores not yet connected.',
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(output, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(temp, OUT)
    print(f'Validated {matches} fixture records; wrote {len(upcoming)} player-fixture entries, preserved {len(existing_games)} game logs')
    for player in ('Jade Melbourne', 'Nyadiew Puoch', 'Isobel Borlase'):
        print(f'  {player}: {sum(x["player"] == player for x in upcoming)} upcoming fixtures')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'WNBL collection failed; existing data preserved: {exc}', file=sys.stderr)
        sys.exit(1)
