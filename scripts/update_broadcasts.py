#!/usr/bin/env python3
"""Courtside Australian NBA broadcast collector.

ESPN scoreboard broadcast names are US hints, NEVER Australian verification.
Foxtel EPG listings are matched to NBA fixtures by both teams and start time.
Existing manually verified entries remain supported.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'broadcasts_au.json'
VERIFIED = ROOT / 'data' / 'broadcast_verified_au.json'
SCOREBOARD = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard'
FOX_BASE = 'https://www.foxtel.com.au/webepg/ws/foxtel/channel'
FOX_REGION = os.environ.get('COURTSIDE_FOXTEL_REGION', '8336')
CHANNELS = {'ESP': 'ESPN', 'ES2': 'ESPN2'}
ALLOWED = {'Prime Video', 'ESPN', 'Disney+', 'Foxtel', 'Foxtel Now', 'Kayo Sports', 'NBA League Pass', 'SBS', 'SBS On Demand', '9Now'}
SYDNEY = ZoneInfo('Australia/Sydney')

TEAM_ALIASES = {
    'Atlanta Hawks': ['atlanta', 'hawks'], 'Boston Celtics': ['boston', 'celtics'],
    'Brooklyn Nets': ['brooklyn', 'nets'], 'Charlotte Hornets': ['charlotte', 'hornets'],
    'Chicago Bulls': ['chicago', 'bulls'], 'Cleveland Cavaliers': ['cleveland', 'cavaliers', 'cavs'],
    'Dallas Mavericks': ['dallas', 'mavericks', 'mavs'], 'Denver Nuggets': ['denver', 'nuggets'],
    'Detroit Pistons': ['detroit', 'pistons'], 'Golden State Warriors': ['golden state', 'warriors'],
    'Houston Rockets': ['houston', 'rockets'], 'Indiana Pacers': ['indiana', 'pacers'],
    'LA Clippers': ['la clippers', 'los angeles clippers', 'clippers'],
    'Los Angeles Lakers': ['los angeles lakers', 'la lakers', 'lakers'],
    'Memphis Grizzlies': ['memphis', 'grizzlies'], 'Miami Heat': ['miami', 'heat'],
    'Milwaukee Bucks': ['milwaukee', 'bucks'], 'Minnesota Timberwolves': ['minnesota', 'timberwolves', 'wolves'],
    'New Orleans Pelicans': ['new orleans', 'pelicans'], 'New York Knicks': ['new york', 'knicks'],
    'Oklahoma City Thunder': ['oklahoma city', 'thunder', 'okc'], 'Orlando Magic': ['orlando', 'magic'],
    'Philadelphia 76ers': ['philadelphia', '76ers', 'sixers'], 'Phoenix Suns': ['phoenix', 'suns'],
    'Portland Trail Blazers': ['portland', 'trail blazers', 'trailblazers', 'blazers'],
    'Sacramento Kings': ['sacramento', 'kings'], 'San Antonio Spurs': ['san antonio', 'spurs'],
    'Toronto Raptors': ['toronto', 'raptors'], 'Utah Jazz': ['utah', 'jazz'],
    'Washington Wizards': ['washington', 'wizards'],
}


def read_json(path, fallback):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else fallback


def fetch_json(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; Courtside/1.1; Australian basketball schedule)',
        'Accept': 'application/json', 'Referer': 'https://www.foxtel.com.au/tv-guide/',
    })
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def get_day(day):
    return fetch_json(f'{SCOREBOARD}?dates={day:%Y%m%d}&limit=100').get('events', [])


def parse_date(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def normalise(value):
    return re.sub(r'[^a-z0-9]+', ' ', str(value).lower()).strip()


def team_mentioned(text, team):
    aliases = TEAM_ALIASES.get(team, [team])
    cleaned = f' {normalise(text)} '
    return any(f' {normalise(alias)} ' in cleaned for alias in aliases)


def is_live_nba_game(event):
    title = str(event.get('programTitle') or '')
    episode = str(event.get('episodeTitle') or '')
    combined = normalise(title + ' ' + episode)
    if not re.search(r'\bnba\b', combined):
        return False
    if re.search(r'\b(mini|minis|today|countdown|highlights|replay|classic|classics|recap|review|preview|studio|sportscenter|the jump|nba action)\b', combined):
        return False
    # Require an explicit LIVE indicator to avoid replay/mini misclassification.
    if event.get('pashTag') != 'LIVE' and not title.lower().startswith('live:'):
        return False
    return True


def foxtel_events(channel, day):
    # Local midnight boundaries correctly handle Australian daylight saving time.
    start = datetime(day.year, day.month, day.day, tzinfo=SYDNEY)
    end = start + timedelta(days=1)
    params = urllib.parse.urlencode({
        'movieHeight': 110, 'tvShowHeight': 90,
        'startDate': int(start.timestamp() * 1000),
        'endDate': int(end.timestamp() * 1000) - 1,
        'regionId': FOX_REGION,
    })
    url = f'{FOX_BASE}/{channel}/events?{params}'
    payload = fetch_json(url)
    if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
        raise ValueError(f'Unexpected Foxtel response for {channel} on {day}')
    return payload['events'], url


def candidate_from_event(event):
    competitions = event.get('competitions') or []
    if not competitions:
        return None
    comp = competitions[0]
    competitors = comp.get('competitors') or []
    home = next((c for c in competitors if c.get('homeAway') == 'home'), {})
    away = next((c for c in competitors if c.get('homeAway') == 'away'), {})
    us = [name for b in comp.get('broadcasts', []) for name in (b.get('names') or [])]
    return {
        'espnEventId': str(event.get('id', '')), 'date': event.get('date'),
        'homeTeam': home.get('team', {}).get('displayName', ''),
        'awayTeam': away.get('team', {}).get('displayName', ''),
        'usBroadcastHints': sorted(set(us)),
        'note': 'US-oriented source; NOT Australian broadcast confirmation',
    }


def match_foxtel(event, candidates):
    title = str(event.get('programTitle') or '')
    episode = str(event.get('episodeTitle') or '')
    combined = title + ' ' + episode
    start_ms = event.get('scheduledDate')
    if not isinstance(start_ms, (int, float)) or not is_live_nba_game(event):
        return None
    broadcast_start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
    matches = []
    for candidate in candidates:
        game_start = parse_date(candidate.get('date'))
        if not game_start:
            continue
        # Broadcast may begin before tip-off (pregame), or a little after.
        delta = (broadcast_start - game_start).total_seconds() / 60
        if not -120 <= delta <= 60:
            continue
        if team_mentioned(combined, candidate.get('homeTeam', '')) and team_mentioned(combined, candidate.get('awayTeam', '')):
            matches.append((abs(delta), candidate))
    # Ambiguous team/title matches are not verified automatically.
    if len(matches) != 1:
        return None
    return matches[0][1]


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
        if not str(record.get('sourceUrl', '')).startswith('https://') or not record.get('checkedAt'):
            raise ValueError('Verified games require sourceUrl (https) and checkedAt')
        if not (record.get('espnEventId') or (record.get('homeTeam') and record.get('awayTeam') and record.get('date'))):
            raise ValueError('Verified games need espnEventId or both teams and ISO date')
        verified.append({**record, 'league': 'NBA', 'market': 'AU', 'status': 'verified'})

    candidates, errors = [], []
    for offset in range(8):
        day = (now + timedelta(days=offset)).date()
        try:
            candidates.extend(c for e in get_day(day) if (c := candidate_from_event(e)))
        except Exception as exc:
            errors.append(f'NBA {day}: {exc}')
    if not candidates and OUT.exists():
        candidates = read_json(OUT, {}).get('candidates', [])

    foxtel_programs = 0
    foxtel_live_nba = 0
    foxtel_matches = {}
    local_today = now.astimezone(SYDNEY).date()
    for offset in range(8):
        day = local_today + timedelta(days=offset)
        for tag, channel_name in CHANNELS.items():
            try:
                events, url = foxtel_events(tag, day)
                foxtel_programs += len(events)
                for event in events:
                    if not is_live_nba_game(event):
                        continue
                    foxtel_live_nba += 1
                    match = match_foxtel(event, candidates)
                    if not match:
                        continue
                    event_id = match['espnEventId']
                    if not event_id:
                        continue
                    key = (event_id, channel_name)
                    foxtel_matches[key] = {
                        'espnEventId': event_id, 'date': match['date'],
                        'homeTeam': match['homeTeam'], 'awayTeam': match['awayTeam'],
                        'providers': ['ESPN'], 'channel': channel_name,
                        'sourceUrl': url, 'checkedAt': now.isoformat(timespec='seconds').replace('+00:00', 'Z'),
                        'programTitle': event.get('programTitle'), 'episodeTitle': event.get('episodeTitle'),
                        'broadcastStart': datetime.fromtimestamp(event['scheduledDate'] / 1000, tz=timezone.utc).isoformat().replace('+00:00', 'Z'),
                        'league': 'NBA', 'market': 'AU', 'status': 'verified', 'verificationMethod': 'foxtel_epg_team_and_time',
                    }
            except Exception as exc:
                errors.append(f'Foxtel {channel_name} {day}: {exc}')

    # Combine manual and automated evidence; retain manually supplied providers.
    for entry in foxtel_matches.values():
        existing = next((r for r in verified if str(r.get('espnEventId', '')) == entry['espnEventId']), None)
        if existing:
            existing['providers'] = list(dict.fromkeys(existing['providers'] + entry['providers']))
            existing.setdefault('additionalSources', []).append({
                'provider': 'ESPN', 'channel': entry['channel'], 'sourceUrl': entry['sourceUrl'],
                'checkedAt': entry['checkedAt'], 'programTitle': entry['programTitle'],
            })
        else:
            verified.append(entry)

    result = {
        'market': 'AU', 'league': 'NBA',
        'updatedAt': now.isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'verified': verified, 'candidates': candidates, 'errors': errors,
        'foxtelStats': {'programsFetched': foxtel_programs, 'liveNbaListings': foxtel_live_nba,
                        'matchedListings': len(foxtel_matches)},
        'notes': 'ESPN scoreboard hints are US-oriented. ESPN is confirmed only by a live Foxtel EPG listing matching both teams and tip-off time. Other providers require independent evidence.',
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUT.with_suffix('.tmp')
    temp.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(temp, OUT)
    print(f'AU broadcasts: {len(verified)} verified games; {len(candidates)} NBA schedule candidates; {len(errors)} fetch warnings')
    print(f'Foxtel: {foxtel_programs} programmes; {foxtel_live_nba} live NBA listings; {len(foxtel_matches)} matched ESPN channel listings')
    for error in errors[:5]:
        print('Warning:', error, file=sys.stderr)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Broadcast collector failed; prior data preserved: {exc}', file=sys.stderr)
        sys.exit(1)
