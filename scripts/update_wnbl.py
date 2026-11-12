#!/usr/bin/env python3
"""Courtside WNBL: preserve fixture feed and backfill official regular-season box scores."""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

FEED = 'https://fixturedownload.azurewebsites.net/feed/json/wnbl-2026'
SCHEDULE = 'https://schedule.wnbl.com.au/api/calendar/schedule?league=wnbl&limit=500&offset=0&year=2026'
MATCH_API = 'https://schedule.wnbl.com.au/api/calendar/match'
OUT = Path(__file__).resolve().parents[1] / 'data' / 'wnbl.json'
TRACKED = {'Bendigo Spirit': ['Jade Melbourne', 'Isobel Borlase'], 'UC Capitals': ['Nyadiew Puoch']}


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; Courtside-WNBL/2.0)', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=35) as response:
        return json.load(response)


def utc_iso(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Missing DateUtc')
    parsed = datetime.fromisoformat(value.strip().replace(' ', 'T').replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('DateUtc missing timezone')
    return parsed.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def player_name(obj):
    if not isinstance(obj, dict):
        return ''
    return (obj.get('full_name') or obj.get('fullName') or ' '.join(filter(None, [obj.get('first_name'), obj.get('last_name')]))).strip()


def full_game_stats(payload):
    match = payload.get('match', {})
    if not isinstance(match, dict):
        return []
    rows = match.get('player_match_statistics', [])
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and str(r.get('period')) == '0']


def make_record(row, scheduled, team, player):
    home = scheduled['home']['name']
    away = scheduled['away']['name']
    home_side = team == home
    match_id = scheduled['id']
    date = datetime.fromtimestamp(scheduled['starts_at_ms'] / 1000, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    stats = {
        'points': 'points', 'rebounds': 'rebounds', 'assists': 'assists',
        'steals': 'steals', 'blocks': 'blocks', 'turnovers': 'turnovers',
        'minutes': 'minutes', 'fieldGoalsMade': 'field_goals_made',
        'fieldGoalsAttempted': 'field_goals_attempted',
        'threePointsMade': 'three_points_made', 'threePointsAttempted': 'three_points_attempted',
        'freeThrowsMade': 'free_throws_made', 'freeThrowsAttempted': 'free_throws_attempted',
    }
    result = {
        'player': player, 'league': 'WNBL', 'team': team,
        'opponent': away if home_side else home, 'home': home_side,
        'date': date, 'status': 'Final', 'venue': scheduled.get('venue_name') or '',
        'round': scheduled.get('round_label'), 'matchId': match_id,
        'id': 'wnbl:' + match_id + ':' + player.lower().replace(' ', '-'),
        'homeScore': scheduled.get('home_score'), 'awayScore': scheduled.get('away_score'),
        'teamScore': scheduled.get('home_score') if home_side else scheduled.get('away_score'),
        'opponentScore': scheduled.get('away_score') if home_side else scheduled.get('home_score'),
        'source': MATCH_API + '?' + urllib.parse.urlencode({'match': match_id, 'league': 'wnbl'}),
    }
    for target, source in stats.items():
        result[target] = row.get(source)
    return result


def main():
    now = datetime.now(timezone.utc)
    raw = fetch(FEED)
    if not isinstance(raw, list) or len(raw) < 10:
        raise ValueError('Fixture feed invalid; existing data left untouched')
    upcoming, seen = [], set()
    valid = 0
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
        valid += 1
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
                    'date': date, 'status': 'Scheduled', 'venue': match.get('Location') or '',
                    'round': match.get('RoundNumber'), 'matchNumber': match.get('MatchNumber'),
                    'broadcast': {'providers': ['9Now', 'Disney+'], 'note': 'League-wide Australian coverage; verify specific stream'},
                })
    if valid < 10:
        raise ValueError('Too few valid fixtures; existing data left untouched')
    upcoming.sort(key=lambda r: (r['date'], r['player']))

    previous = {}
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            print('WARNING: Previous WNBL JSON unreadable; continuing with new data', file=sys.stderr)
    games = {r['id']: r for r in previous.get('games', []) if isinstance(r, dict) and r.get('id')}
    schedule_count = 0
    matched_count = 0
    failed = 0
    try:
        schedule = fetch(SCHEDULE)
        schedule_matches = schedule.get('matches', [])
        if not isinstance(schedule_matches, list) or not schedule_matches:
            raise ValueError('Official schedule has no matches')
        schedule_count = len(schedule_matches)
        for match in schedule_matches:
            if not isinstance(match, dict) or match.get('season_type') != 'regular' or match.get('phase') != 'complete':
                continue
            home = match.get('home') or {}
            away = match.get('away') or {}
            if not isinstance(home, dict) or not isinstance(away, dict):
                continue
            teams = [t for t in (home.get('name'), away.get('name')) if t in TRACKED]
            if not teams or not isinstance(match.get('id'), str):
                continue
            matched_count += 1
            # Refresh all completed games: corrections to official box scores propagate.
            url = MATCH_API + '?' + urllib.parse.urlencode({'match': match['id'], 'league': 'wnbl'})
            try:
                payload = fetch(url)
                rows = full_game_stats(payload)
                if not rows:
                    raise ValueError('No full-game player stats')
                added = 0
                for team in teams:
                    for player in TRACKED[team]:
                        candidates = [r for r in rows if player_name(r.get('player')) .casefold() == player.casefold()]
                        if not candidates:
                            continue  # Player did not appear in this box score.
                        record = make_record(candidates[0], match, team, player)
                        games[record['id']] = record
                        added += 1
                print(f'{match["id"]}: {home.get("name")} vs {away.get("name")}: {added} tracked players')
            except Exception as exc:
                failed += 1
                print(f'WARNING: Match {match["id"]} unavailable: {exc}', file=sys.stderr)
    except Exception as exc:
        print(f'WARNING: Official schedule unavailable; preserving existing game stats: {exc}', file=sys.stderr)
        failed += 1

    output = {
        'league': 'WNBL', 'season': '2026-27',
        'updatedAt': now.isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'source': FEED, 'statsSource': SCHEDULE,
        'games': sorted(games.values(), key=lambda r: (r.get('date') or '', r.get('player') or ''), reverse=True),
        'upcoming': upcoming,
        'notes': 'Fixtures from public fixture feed; official regular-season player box scores from WNBL Game Centre. Team fixtures do not guarantee participation.',
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(output, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(temp, OUT)
    print(f'Validated {valid} fixtures; {len(upcoming)} upcoming player entries; official schedule {schedule_count} matches; {matched_count} completed tracked-team games; {len(games)} player game records; {failed} API errors')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'WNBL collection failed; existing data preserved: {exc}', file=sys.stderr)
        sys.exit(1)
