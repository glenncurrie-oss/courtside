# Courtside: Australian NBA broadcast evidence (safe pilot)

This is a **verified-data pipeline and schedule overlay**, not an automated Australian broadcaster scraper. ESPN's public scoreboard API can supply NBA fixtures and US broadcaster hints, but those hints are **not evidence of Australian coverage**. This release deliberately does **not** automatically label games as ESPN Australia or Prime Video Australia.

## Upload to GitHub

Upload these paths to your `glenncurrie-oss/courtside` repository (preserving the folders):

- `index.html` — replace the existing root website.
- `scripts/update_broadcasts.py` — new script; does not modify NBA/WNBL collectors.
- `data/broadcast_verified_au.json` — new editable verified game list.
- `.github/workflows/broadcasts-au.yml` — new daily workflow.

Run **Actions → Courtside Australian NBA broadcasts → Run workflow**. It creates `data/broadcasts_au.json`. The website reads this file and only shows a **verified Australian broadcaster** when a matching record exists in the verified list.

## Adding a verified Australian listing

After confirming a particular game on an Australian broadcaster's official game page, add a record to `data/broadcast_verified_au.json`:

```json
{
  "games": [
    {
      "homeTeam": "Chicago Bulls",
      "awayTeam": "Minnesota Timberwolves",
      "date": "2026-11-15T01:00:00Z",
      "providers": ["Prime Video"],
      "sourceUrl": "https://REPLACE-WITH-ACTUAL-GAME-SPECIFIC-SOURCE",
      "checkedAt": "2026-11-12"
    }
  ]
}
```

**Example only:** The game, date, provider and URL in the example are placeholders; do not use them without verification. Use the **exact** UTC tip-off timestamp from the Courtside fixture feed, and the exact home/away team names. Alternatively specify an `espnEventId` if the Courtside game record also contains it. The collector validates providers and requires source evidence. Run the workflow again after changing the verified list.

Accepted providers: Prime Video, ESPN, Disney+, Foxtel, Foxtel Now, Kayo Sports, NBA League Pass, SBS, SBS On Demand, 9Now.

For a verified ESPN Australia game, list the ESPN channel and the relevant Australian subscription access routes if confirmed for that game. Do not copy US ESPN or US Prime Video listings directly into the Australian verified list.

## Reliability

- If ESPN is unavailable, the collector preserves previous schedule candidates; verified records still flow through.
- The collector is independent of existing NBA/WNBL data updates.
- The website clearly says *Australian broadcast not yet verified* when there is no verified match.
- US broadcaster hints are stored only as diagnostic candidates, never rendered as Australian availability.
- The workflow needs GitHub Actions write permission for committing generated data.

## Future step

For truly automated **confirmed** AU listings, integrate a licensed or officially documented Australian TV-guide API that provides per-game channel and streaming metadata. A US NBA schedule alone cannot reliably confirm Australian availability.
