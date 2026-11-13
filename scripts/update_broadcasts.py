#!/usr/bin/env python3
"""Courtside Australian NBA broadcast collector.

ESPN scoreboard broadcast names are US hints, NEVER Australian verification.
Foxtel EPG listings are matched to NBA fixtures by both teams and start time.
Existing manually verified entries remain supported.
"""
import json
import html
from html.parser import HTMLParser
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
EASTERN = ZoneInfo('America/New_York')
PRIME_URL = 'https://www.nba.com/news/every-nba-game-on-prime-video-in-2026-27'
PRIME_AU_URL = 'https://www.primevideo.com/region/fe/tournament/amzn1.dv.icid.cf75b42a-68cd-4a1c-993a-a0b3f0575c5f'
PRIME_ENRICH_URL = 'https://www.primevideo.com/region/fe/api/enrichItemMetadata'

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


class ListItems(HTMLParser):
    """Extract text from HTML list items without third-party dependencies."""
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.current = []
        self.items = []

    def handle_starttag(self, tag, attrs):
        if tag == 'li':
            if self.depth == 0:
                self.current = []
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == 'li' and self.depth:
            self.depth -= 1
            if not self.depth:
                self.items.append(html.unescape(' '.join(self.current)).strip())

    def handle_data(self, data):
        if self.depth:
            self.current.append(data)


def fetch_prime_listings():
    req = urllib.request.Request(PRIME_URL, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; Courtside/1.2)',
        'Accept': 'text/html',
    })
    with urllib.request.urlopen(req, timeout=20) as response:
        document = response.read().decode('utf-8', errors='replace')
    parser = ListItems()
    parser.feed(document)
    # Official schedule uses US Eastern dates and times; convert using DST-aware zone.
    pattern = re.compile(r'\b([A-Z][a-z]{2})\.?\s+(\d{1,2}):\s*(.*?)\s+[—–-]\s*(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\s*ET\b', re.I)
    months = {name: i for i, name in enumerate(('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'), 1)}
    listings = []
    for item in parser.items:
        match = pattern.search(' '.join(item.split()))
        if not match:
            continue
        month, day, matchup, hour, minute, meridiem = match.groups()
        month_num = months.get(month.title())
        if not month_num:
            continue
        year = 2026 if month_num >= 10 else 2027
        hour = int(hour) % 12 + (12 if meridiem.lower().startswith('p') else 0)
        local = datetime(year, month_num, int(day), hour, int(minute or 0), tzinfo=EASTERN)
        listings.append({'matchup': matchup.strip(), 'startUtc': local.astimezone(timezone.utc), 'publishedText': item})
    if not listings:
        raise ValueError('No dated Prime Video games parsed; official page may have changed')
    return listings


def prime_matches(listings, candidates):
    """Conservative exact game matching; source is US/global, not AU verification."""
    found = {}
    for listing in listings:
        matchup = listing['matchup']
        parts = re.split(r'\s+(?:vs\.?|at|@)\s+', matchup, maxsplit=1, flags=re.I)
        if len(parts) != 2:
            continue
        matching = []
        for candidate in candidates:
            start = parse_date(candidate.get('date'))
            if not start or abs((start - listing['startUtc']).total_seconds()) > 90 * 60:
                continue
            home, away = candidate.get('homeTeam', ''), candidate.get('awayTeam', '')
            if ((team_mentioned(parts[0], home) and team_mentioned(parts[1], away)) or
                (team_mentioned(parts[1], home) and team_mentioned(parts[0], away))):
                matching.append(candidate)
        if len(matching) == 1:
            candidate = matching[0]
            found[candidate['espnEventId']] = {
                'espnEventId': candidate['espnEventId'], 'date': candidate['date'],
                'homeTeam': candidate['homeTeam'], 'awayTeam': candidate['awayTeam'],
                'provider': 'Prime Video', 'sourceUrl': PRIME_URL,
                'sourceMarket': 'US/global', 'market': 'AU', 'status': 'candidate',
                'note': 'Official Prime Video schedule match; Australian availability NOT independently verified',
            }
    return list(found.values())



class PrimeAUCards(HTMLParser):
    """Read server-rendered Amazon event cards; ignore unrelated team and promo cards."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards = []
        self.depth = 0
        self.card = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.card is None and tag == 'article' and attrs.get('data-card-entity-type') == 'EVENT':
            self.card = {'title': html.unescape(attrs.get('data-card-title', '')),
                         'entitlement': attrs.get('data-card-entitlement', ''),
                         'text': [], 'evidence': [], 'hrefs': [], 'amazonIds': []}
            self.depth = 1
        elif self.card is not None:
            self.depth += 1 if tag == 'article' else 0
        if self.card is not None:
            for key in ('alt', 'aria-label', 'title', 'src', 'srcset'):
                if attrs.get(key):
                    self.card['evidence'].append(attrs[key])
            if tag == 'a' and attrs.get('href'):
                self.card['hrefs'].append(attrs['href'])
            # Only collect IDs that occur INSIDE this specific card. Never
            # associate IDs based on their order elsewhere in the page.
            for value in attrs.values():
                if isinstance(value, str):
                    self.card['amazonIds'].extend(re.findall(
                        r'amzn1\.dv\.gti\.[0-9a-f-]{36}', value, re.I))

    def handle_endtag(self, tag):
        if self.card is not None and tag == 'article':
            self.depth -= 1
            if self.depth == 0:
                self.card['text'] = ' '.join(' '.join(self.card['text']).split())
                self.card['evidence'] = ' '.join(self.card['evidence']).lower()
                self.cards.append(self.card)
                self.card = None

    def handle_data(self, data):
        if self.card is not None:
            self.card['text'].append(data)


def fetch_prime_au_cards():
    req = urllib.request.Request(PRIME_AU_URL, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-AU,en;q=0.9',
    })
    with urllib.request.urlopen(req, timeout=25) as response:
        document = response.read().decode('utf-8', errors='replace')
    parser = PrimeAUCards()
    parser.feed(document)
    if not parser.cards:
        raise ValueError('No event cards in Amazon AU HTML (possibly geo-blocked or page changed)')
    return parser.cards


def prime_au_enrich(cards):
    """Best-effort, unauthenticated Amazon enrichment probe.

    This is an undocumented endpoint. Never send cookies, browser tokens,
    copied impressionData or credentials. Only use provider data when its
    response key directly matches an ID attached to the SAME event card.
    """
    stats = {'requestedIds': 0, 'returnedIds': 0, 'mappedCards': 0,
             'primeLabels': 0, 'leaguePassLabels': 0, 'status': 'not attempted'}
    # Prefer Amazon's global title IDs; some cards expose only detail IDs.
    card_ids = {}
    for i, card in enumerate(cards):
        ids = set(card.get('amazonIds') or [])
        for href in card.get('hrefs', []):
            m = re.search(r'/detail/([A-Z0-9]{20,40})', href, re.I)
            if m:
                ids.add(m.group(1))
        if ids:
            card_ids[i] = ids
    all_ids = sorted(set().union(*card_ids.values())) if card_ids else []
    if not all_ids:
        stats['status'] = 'no card IDs'
        return stats
    stats['requestedIds'] = len(all_ids)
    payload = urllib.parse.urlencode({
        'metadataToEnrich': json.dumps({
            'placement': 'HOVER', 'playback': True, 'preroll': True,
            'trailer': True, 'watchlist': False,
        }, separators=(',', ':')),
        'titleIDsToEnrich': json.dumps(all_ids),
        'journeyIngressContext': '',
        'currentUrl': PRIME_AU_URL,
    }).encode('utf-8')
    request = urllib.request.Request(PRIME_ENRICH_URL, data=payload, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36',
        'Accept': 'application/json',
        'Accept-Language': 'en-AU,en;q=0.9',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Origin': 'https://www.primevideo.com',
        'Referer': PRIME_AU_URL,
        'X-Requested-With': 'XMLHttpRequest',
    }, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response_json = json.load(response)
        enrichments = response_json.get('enrichments', {})
        if not isinstance(enrichments, dict):
            raise ValueError('missing enrichments object')
        stats['returnedIds'] = len(enrichments)
        for i, ids in card_ids.items():
            matching = [enrichments[k] for k in ids if isinstance(enrichments.get(k), dict)]
            if not matching:
                continue
            labels = set()
            for record in matching:
                cues = record.get('entitlementCues') or {}
                logo = (cues.get('providerLogo') or {}).get('message', '')
                if normalise(logo) == 'nba league pass':
                    labels.add('NBA League Pass')
                elif normalise(logo) == 'prime video' and (
                    (cues.get('focusMessage') or {}).get('message', '').lower() == 'included with prime'
                    or cues.get('entitlementType') == 'Entitled'
                ):
                    labels.add('Prime Video')
            if len(labels) == 1:
                cards[i]['apiProvider'] = next(iter(labels))
                stats['mappedCards'] += 1
                if cards[i]['apiProvider'] == 'Prime Video':
                    stats['primeLabels'] += 1
                else:
                    stats['leaguePassLabels'] += 1
        stats['status'] = 'ok'
    except Exception as exc:
        # Expected possibility: Amazon may require signed impressionData.
        # Never fail the working Foxtel collector because of this probe.
        stats['status'] = f'unavailable ({type(exc).__name__}: {str(exc)[:100]})'
    return stats


def prime_au_provider(card):
    """Require provider-specific evidence; account entitlement by itself is NOT proof."""
    if card.get('apiProvider') in ('Prime Video', 'NBA League Pass'):
        return card['apiProvider']
    evidence = card['evidence']
    entitlement = card['entitlement'].lower()
    if 'nba league pass' in evidence or 'nba-league-pass' in evidence:
        return 'NBA League Pass'
    # Amazon Prime branding is commonly an image; do not infer Prime solely from Entitled.
    if entitlement == 'entitled' and re.search(r'prime.video|prime[_/-]logo|/prime/logos|included with prime', evidence):
        return 'Prime Video'
    return None


def prime_au_matches(cards, candidates, now):
    """Match unique NBA opponents within the upcoming window, without card dates.

    Amazon's server-rendered EVENT cards often omit dates entirely. An undated
    matchup is safe to associate only when exactly one fixture has those teams
    within the candidate window. Provider verification still requires explicit
    provider branding; an account's Entitled flag is insufficient.
    """
    matches = {}
    stats = {'eventCards': len(cards), 'matchedFixtures': 0, 'verifiedAustralianGames': 0,
             'primeIncluded': 0, 'leaguePass': 0, 'unclassified': 0,
             'ambiguousFixtures': 0, 'noFixture': 0, 'undatedMatches': 0,
             'providerEvidenceMissing': 0}
    for card in cards:
        title = card['title']
        sides = re.split(r'\s+(?:vs\.?|v\.?|at|@)\s+', title, maxsplit=1, flags=re.I)
        if len(sides) != 2:
            continue
        matching = []
        for candidate in candidates:
            start = parse_date(candidate.get('date'))
            if not start:
                continue
            home, away = candidate.get('homeTeam', ''), candidate.get('awayTeam', '')
            if ((team_mentioned(sides[0], home) and team_mentioned(sides[1], away)) or
                (team_mentioned(sides[1], home) and team_mentioned(sides[0], away))):
                matching.append(candidate)
        # Don't assume which of two rematches the undated Amazon card means.
        unique = {c['espnEventId']: c for c in matching if c.get('espnEventId')}
        if not unique:
            stats['noFixture'] += 1
            continue
        if len(unique) != 1:
            stats['ambiguousFixtures'] += 1
            continue
        stats['matchedFixtures'] += 1
        stats['undatedMatches'] += 1
        provider = prime_au_provider(card)
        if not provider:
            stats['unclassified'] += 1
            stats['providerEvidenceMissing'] += 1
            continue
        candidate = next(iter(unique.values()))
        event_id = candidate['espnEventId']
        url = PRIME_AU_URL
        for href in card['hrefs']:
            if '/detail/' in href:
                url = urllib.parse.urljoin('https://www.primevideo.com', href)
                break
        entry = {
            'espnEventId': event_id, 'date': candidate['date'],
            'homeTeam': candidate['homeTeam'], 'awayTeam': candidate['awayTeam'],
            'providers': [provider], 'sourceUrl': url,
            'checkedAt': now.isoformat(timespec='seconds').replace('+00:00', 'Z'),
            'league': 'NBA', 'market': 'AU', 'status': 'verified',
            'verificationMethod': 'prime_au_html_unique_matchup_provider_badge',
            'primeEntitlement': card['entitlement'],
        }
        if event_id in matches:
            if matches[event_id] is None or matches[event_id]['providers'] != [provider]:
                matches[event_id] = None
        else:
            matches[event_id] = entry
    matches = {key: value for key, value in matches.items() if value is not None}
    stats['verifiedAustralianGames'] = len(matches)
    stats['primeIncluded'] = sum('Prime Video' in v['providers'] for v in matches.values())
    stats['leaguePass'] = sum('NBA League Pass' in v['providers'] for v in matches.values())
    return list(matches.values()), stats


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

    prime_listings = []
    prime_candidates = []
    try:
        prime_listings = fetch_prime_listings()
        prime_candidates = prime_matches(prime_listings, candidates)
    except Exception as exc:
        errors.append(f'Prime Video official schedule: {exc}')
        # Preserve earlier Prime candidates if official page is temporarily unavailable.
        if OUT.exists():
            prime_candidates = read_json(OUT, {}).get('primeCandidates', [])

    prime_au_verified = []
    prime_au_stats = {'eventCards': 0, 'matchedFixtures': 0, 'verifiedAustralianGames': 0,
                      'primeIncluded': 0, 'leaguePass': 0, 'unclassified': 0,
                      'ambiguousFixtures': 0, 'noFixture': 0, 'undatedMatches': 0,
                      'providerEvidenceMissing': 0}
    prime_api_stats = {'status': 'not attempted'}
    try:
        prime_cards = fetch_prime_au_cards()
        prime_api_stats = prime_au_enrich(prime_cards)
        prime_au_verified, prime_au_stats = prime_au_matches(prime_cards, candidates, now)
    except Exception as exc:
        errors.append(f'Prime Video AU tournament: {exc}')

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
    for entry in list(foxtel_matches.values()) + prime_au_verified:
        existing = next((r for r in verified if str(r.get('espnEventId', '')) == entry['espnEventId']), None)
        if existing:
            existing['providers'] = list(dict.fromkeys(existing['providers'] + entry['providers']))
            existing.setdefault('additionalSources', []).append({
                'provider': entry['providers'][0], 'channel': entry.get('channel'),
                'sourceUrl': entry['sourceUrl'], 'checkedAt': entry['checkedAt'],
                'programTitle': entry.get('programTitle'),
            })
        else:
            verified.append(entry)

    result = {
        'market': 'AU', 'league': 'NBA',
        'updatedAt': now.isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'verified': verified, 'candidates': candidates, 'primeCandidates': prime_candidates, 'errors': errors,
        'primeStats': {'publishedListings': len(prime_listings), 'matchedCandidates': len(prime_candidates), 'verifiedAustralianGames': len(prime_au_verified)},
        'primeAuStats': prime_au_stats, 'primeApiStats': prime_api_stats,
        'foxtelStats': {'programsFetched': foxtel_programs, 'liveNbaListings': foxtel_live_nba,
                        'matchedListings': len(foxtel_matches)},
        'notes': 'ESPN verified through Foxtel AU EPG. Prime Video AU event cards verified only when a matchup uniquely identifies an upcoming fixture and explicit provider branding is present. API enrichment is experimental and never uses account credentials. US/global Prime schedule remains candidates only.',
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUT.with_suffix('.tmp')
    temp.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(temp, OUT)
    print(f'AU broadcasts: {len(verified)} verified games; {len(candidates)} NBA schedule candidates; {len(errors)} fetch warnings')
    print(f'Foxtel: {foxtel_programs} programmes; {foxtel_live_nba} live NBA listings; {len(foxtel_matches)} matched ESPN channel listings')
    print(f'Prime Video US: {len(prime_listings)} published listings; {len(prime_candidates)} NBA candidates matched')
    print(f'Prime Video AU: {prime_au_stats["eventCards"]} event cards; {prime_au_stats["matchedFixtures"]} matched; {prime_au_stats["primeIncluded"]} included with Prime; {prime_au_stats["leaguePass"]} League Pass; {prime_au_stats["unclassified"]} unclassified; {prime_au_stats["ambiguousFixtures"]} ambiguous; {prime_au_stats["noFixture"]} without fixture')
    print(f'Prime Video API: {prime_api_stats.get("status")}; {prime_api_stats.get("requestedIds", 0)} IDs requested; {prime_api_stats.get("returnedIds", 0)} returned; {prime_api_stats.get("mappedCards", 0)} cards labelled')
    for error in errors[:5]:
        print('Warning:', error, file=sys.stderr)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Broadcast collector failed; prior data preserved: {exc}', file=sys.stderr)
        sys.exit(1)