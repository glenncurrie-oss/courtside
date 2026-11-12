"""Courtside NCAA: retain historical games and collect team-specific future fixtures.
Unofficial ESPN data; schedules may change. No player participation implied.
"""
import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    'mens-college-basketball': [],
    'womens-college-basketball': ['Monique Bobongie', 'Dallas Loughridge'],
}

def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Courtside/3.1 (personal basketball tracker)', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)

def collect(league, targets, backfill=False):
    path = ROOT / 'data' / ('ncaa_mbb.json' if league.startswith('mens-') else 'ncaa_wbb.json')
    old = json.loads(path.read_text()) if path.exists() else {}
    games = {(str(g.get('id')), g.get('player')): g for g in old.get('games', [])}
    today = dt.datetime.now(dt.timezone.utc).date()
    start = (dt.date(today.year if today.month >= 10 else today.year-1, 10, 1)
             if backfill else today - dt.timedelta(days=10))
    end = today + dt.timedelta(days=35)
    base = 'https://site.api.espn.com/apis/site/v2/sports/basketball/' + league
    # Identify teams from verified prior athlete box scores. Do not guess teams from names.
    teams = {}
    for g in sorted(games.values(), key=lambda x: x.get('date') or '', reverse=True):
        if g.get('player') in targets and g.get('team'):
            teams.setdefault(g['player'], g['team'])
    upcoming = {}
    errors = []
    successful = 0
    matches = 0
    for offset in range((end-start).days + 1):
        date = start + dt.timedelta(days=offset)
        try:
            board = get(base + '/scoreboard?' + urllib.parse.urlencode({'dates': date.strftime('%Y%m%d'), 'limit': 500, 'groups': 50}))
            successful += 1
        except Exception as exc:
            errors.append(f'{date}: {str(exc)[:100]}')
            continue
        for event in board.get('events', []):
            eid = str(event.get('id') or '')
            if not eid:
                continue
            status = event.get('status', {}).get('type', {}).get('state')
            sides = (event.get('competitions') or [{}])[0].get('competitors') or []
            if status == 'pre':
                for player, teamname in teams.items():
                    ours = next((s for s in sides if (s.get('team', {}).get('displayName') or '').casefold() == teamname.casefold()), None)
                    if not ours:
                        continue
                    opp = next((s for s in sides if s is not ours), None)
                    if not opp:
                        continue
                    item = {'id': eid, 'player': player,
                            'league': 'NCAA MBB' if league.startswith('mens-') else 'NCAA WBB',
                            'date': event.get('date'), 'team': teamname,
                            'opponent': opp.get('team', {}).get('displayName') or 'Unknown',
                            'home': ours.get('homeAway') == 'home', 'status': 'pre'}
                    # ESPN sometimes supplies US broadcast listings; do not present them as Australian availability.
                    upcoming[(eid, player)] = item
                continue
            if status != 'post' or all((eid, p) in games for p in targets):
                continue
            try:
                detail = get(base + '/summary?event=' + urllib.parse.quote(eid))
                for group in detail.get('boxscore', {}).get('players', []):
                    team = group.get('team') or {}
                    tid = str(team.get('id') or '')
                    ours = next((s for s in sides if str(s.get('team', {}).get('id') or '') == tid), None)
                    opp = next((s for s in sides if s is not ours), None)
                    for section in group.get('statistics', []):
                        labels = section.get('labels') or []
                        for row in section.get('athletes', []):
                            athlete = row.get('athlete') or {}
                            name = athlete.get('displayName') or ''
                            player = next((p for p in targets if p.casefold() == name.casefold()), None)
                            if not player or not row.get('stats'):
                                continue
                            teamname = team.get('displayName') or team.get('name') or ''
                            games[(eid, player)] = {
                                'id': eid, 'player': player,
                                'league': 'NCAA MBB' if league.startswith('mens-') else 'NCAA WBB',
                                'date': event.get('date'), 'team': teamname,
                                'opponent': (opp or {}).get('team', {}).get('displayName', 'Unknown'),
                                'teamScore': (ours or {}).get('score'), 'opponentScore': (opp or {}).get('score'),
                                'home': (ours or {}).get('homeAway') == 'home', 'status': 'post',
                                'stats': dict(zip(labels, row['stats'])),
                                'athleteId': str(athlete.get('id') or ''),
                                'headshot': (athlete.get('headshot') or {}).get('href')}
                            matches += 1
                            if teamname:
                                teams[player] = teamname
                time.sleep(.04)
            except Exception as exc:
                errors.append(f'summary {eid}: {str(exc)[:100]}')
        time.sleep(.025)
    if not successful:
        raise RuntimeError('No successful NCAA scoreboard responses for ' + league)
    # Retain earlier future fixtures only when still in the future and not superseded.
    for g in old.get('upcoming', []):
        try:
            if dt.datetime.fromisoformat(g['date'].replace('Z', '+00:00')).date() >= today:
                upcoming.setdefault((str(g.get('id')), g.get('player')), g)
        except (ValueError, KeyError, TypeError):
            pass
    output = {'source': 'ESPN NCAA endpoints (unofficial)', 'updatedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
              'players': targets, 'games': sorted(games.values(), key=lambda x: x.get('date') or '', reverse=True),
              'upcoming': sorted(upcoming.values(), key=lambda x: x.get('date') or ''),
              'warnings': errors[:30], 'successful': True, 'backfill': backfill}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2) + '\n')
    print(f'{league}: {successful} successful dates, {matches} new player lines, {len(games)} saved games, {len(upcoming)} upcoming fixtures, {len(errors)} errors')

if __name__ == '__main__':
    backfill = os.environ.get('COURTSIDE_NCAA_BACKFILL') == '1'
    failures = []
    for league, targets in TARGETS.items():
        try:
            collect(league, targets, backfill)
        except Exception as exc:
            print('FAILED', league, repr(exc))
            failures.append(league)
    if failures:
        raise SystemExit('Failed NCAA leagues: ' + ', '.join(failures))
