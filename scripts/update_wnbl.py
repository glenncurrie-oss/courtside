#!/usr/bin/env python3
"""Courtside WNBL: preserve fixture feed and collect verified full-game player stats.

The fixture feed has no Game Centre UUIDs. Add UUIDs to data/wnbl_match_ids.json
as they become known; the confirmed example is seeded below. No speculative IDs.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEED = 'https://fixturedownload.azurewebsites.net/feed/json/wnbl-2026'
API = 'https://schedule.wnbl.com.au/api/calendar/match'
OUT = ROOT / 'data' / 'wnbl.json'
IDS = ROOT / 'data' / 'wnbl_match_ids.json'
TRACKED = {
    'Bendigo Spirit': ['Jade Melbourne', 'Isobel Borlase'],
    'UC Capitals': ['Nyadiew Puoch'],
}
# Proven through the GitHub Actions diagnostic. The match payload contains
# official full-game records; its home/away information determines opponent.
SEED_MATCH_IDS = ['69dc4125-7351-11f1-a716-5d1a014d3413']
JADE_EXTERNAL_ID = '7015a1de-45e3-11f0-85e1-c5864f4b75a8'
UUID = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')


def get_json(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; Courtside/1.0)',
        'Accept': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=35) as response:
        return json.load(response)


def utc_iso(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Missing DateUtc')
    dt = datetime.fromisoformat(value.strip().replace(' ', 'T').replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('DateUtc missing timezone')
    return dt.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def text_name(player):
    return (player.get('full_name') or ' '.join(filter(None, [player.get('first_name'), player.get('last_name')]))).strip()


def player_name(player):
    name = text_name(player).casefold()
    for names in TRACKED.values():
        for candidate in names:
            if name == candidate.casefold():
                return candidate
    # The diagnostic established Jade's external identifier, which is stable
    # across player_match_statistics and calculated_player_statistics.
    if player.get('external_id') == JADE_EXTERNAL_ID or player.get('id') == JADE_EXTERNAL_ID:
        return 'Jade Melbourne'
    return None


def minutes_value(value):
    if isinstance(value, str) and ':' in value:
        return value
    return None  # never substitute unreliable calculated minutes


def parse_match(match_id, payload):
    match = payload.get('match')
    if not isinstance(match, dict):
        raise ValueError('API payload missing match object')
    records = match.get('player_match_statistics')
    if not isinstance(records, list):
        raise ValueError('API payload missing player_match_statistics')
    # The official period 0 record is the entire match; don't sum periods.
    results = []
    seen = set()
    for record in records:
        if not isinstance(record, dict) or str(record.get('period')) != '0':
            continue
        player = record.get('player') or {}
        if not isinstance(player, dict):
            continue
        name = player_name(player)
        if not name or name in seen:
            continue
        seen.add(name)
        minutes = minutes_value(record.get('minutes'))
        if minutes == '00:00':
            continue  # DNP, not a played game
        team = next((t for t, ns in TRACKED.items() if name in ns), '')
        item = {
            'player': name, 'league': 'WNBL', 'team': team,
            'matchId': match_id, 'id': f'wnbl:{match_id}:{name.casefold().replace(" ", "-")}',
            'points': record.get('points'), 'rebounds': record.get('rebounds'),
            'assists': record.get('assists'), 'steals': record.get('steals'),
            'blocks': record.get('blocks'), 'turnovers': record.get('turnovers'),
            'minutes': minutes,
            'fieldGoalsMade': record.get('field_goals_made'),
            'fieldGoalsAttempted': record.get('field_goals_attempted'),
            'threePointsMade': record.get('three_points_made'),
            'threePointsAttempted': record.get('three_points_attempted'),
            'freeThrowsMade': record.get('free_throws_made'),
            'freeThrowsAttempted': record.get('free_throws_attempted'),
            'source': API + '?' + urllib.parse.urlencode({'match': match_id, 'league': 'wnbl'}),
        }
        # Game metadata differs across feeds; use only explicit known fields.
        for field in ('date', 'start_time', 'scheduled', 'scheduled_at', 'tipoff'):
            value = match.get(field)
            if isinstance(value, str) and value:
                try:
                    item['date'] = utc_iso(value)
                    break
                except ValueError:
                    pass
        results.append(item)
    return results


def match_ids():
    ids = list(SEED_MATCH_IDS)
    if IDS.exists():
        loaded = json.loads(IDS.read_text(encoding='utf-8'))
        if isinstance(loaded, dict):
            loaded = loaded.get('matchIds', [])
        if not isinstance(loaded, list):
            raise ValueError('wnbl_match_ids.json must be a list or {"matchIds": [...]}')
        ids.extend(loaded)
    return list(dict.fromkeys(x.lower() for x in ids if isinstance(x, str) and UUID.fullmatch(x)))


def collect_fixtures(now):
    raw = get_json(FEED)
    if not isinstance(raw, list) or not raw:
        raise ValueError('Fixture feed empty or not a list')
    upcoming, seen, matches = [], set(), 0
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
                    'player': player, 'league': 'WNBL', 'team': team,
                    'opponent': away if team == home else home, 'home': team == home,
                    'date': date, 'status': 'Scheduled',
                    'venue': match.get('Location') or '',
                    'round': match.get('RoundNumber'),
                    'matchNumber': match.get('MatchNumber'),
                    'broadcast': {
                        'providers': ['9Now', 'Disney+'],
                        'note': 'League-wide Australian coverage; verify specific stream',
                    },
                })
    if matches < 10:
        raise ValueError(f'Only {matches} valid matches; refusing to overwrite')
    upcoming.sort(key=lambda x: (x['date'], x['player']))
    return matches, upcoming


def main():
    now = datetime.now(timezone.utc)
    # Preserve old records, and do not write anything if fixture validation fails.
    previous = {}
    if OUT.exists():
        previous = json.loads(OUT.read_text(encoding='utf-8'))
        if not isinstance(previous, dict):
            raise ValueError('Existing wnbl.json is not an object')
    count, upcoming = collect_fixtures(now)
    old_games = previous.get('games', [])
    if not isinstance(old_games, list):
        raise ValueError('Existing games is not a list')
    games = list(old_games)
    existing_keys = {(str(g.get('matchId')), str(g.get('player'))) for g in games if isinstance(g, dict)}
    new_count, failures = 0, []
    for mid in match_ids():
        try:
            url = API + '?' + urllib.parse.urlencode({'match': mid, 'league': 'wnbl'})
            extracted = parse_match(mid, get_json(url))
            for game in extracted:
                key = (mid, game['player'])
                if key not in existing_keys:
                    games.append(game)
                    existing_keys.add(key)
                    new_count += 1
        except Exception as exc:
            failures.append(f'{mid}: {exc}')
    # Avoid clobbering good data if all API calls fail; fixtures still update.
    output = {
        'league': 'WNBL', 'season': '2026-27',
        'updatedAt': now.isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'source': FEED, 'games': games, 'upcoming': upcoming,
        'notes': 'Full-game player statistics from official WNBL match API where available; team fixtures do not guarantee participation.',
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(output, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(tmp, OUT)
    print(f'Fixtures: {count} validated, {len(upcoming)} upcoming; game records: {len(games)} ({new_count} new)')
    for failure in failures:
        print('Stats warning:', failure, file=sys.stderr)
    if failures and new_count == 0:
        print('Stats API failed or returned no new records; existing games retained', file=sys.stderr)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'WNBL collection failed; existing data preserved: {exc}', file=sys.stderr)
        sys.exit(1)
