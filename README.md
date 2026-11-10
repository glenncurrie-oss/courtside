# Courtside — free NBA integration (phase 1)

This builds on the working standalone Courtside prototype. The watchlist remains in the browser's localStorage (`courtside-watchlist-v1`), so the six initial players and additions are preserved **when opened at the same browser origin**. Moving from a local file to GitHub Pages uses a different origin: export your watchlist from the old app and import it on the hosted version.

## Deploy for free
1. Create a free GitHub account if needed, then create a **public** repository named `courtside`.
2. Upload **the contents** of this folder (including `.github/workflows/update.yml`, `scripts/update_nba.py`, `data/nba.json` and `index.html`) to the repository root. The hidden `.github` folder is essential.
3. Under **Settings → Pages**, choose **Deploy from a branch**, branch `main`, folder `/ (root)`, and save.
4. Under **Actions → Update Courtside NBA data**, choose **Run workflow**. Wait for success; it commits the refreshed JSON data to the repository.
5. Visit `https://YOUR-USERNAME.github.io/courtside/`. Updates are scheduled every six hours (GitHub schedule timing is approximate).

## Data and limitations
- ESPN's public endpoints are **unofficial and undocumented**; they may change, be unavailable or restrict automated use. Verify permission and reliability before relying on them long term.
- The script requests Chicago Bulls fixtures for a 31-day rolling window and box scores for finished games. It accumulates game history on each successful run; it does not backfill an entire career in one run.
- Player box-score extraction is matched by exact name and team. Missing statistics show `—`, never fabricated zeros. Scheduled team games do not guarantee that Josh will play.
- The initial JSON is intentionally empty; this environment could not reach the endpoint to prepopulate verified results.
- Hosting and public-repository GitHub Actions can be free subject to GitHub policies. The website and data are public; do not put private keys in the repository.
- Other leagues and international games are **not yet integrated**.
- If GitHub Actions cannot push, review repository **Settings → Actions → General → Workflow permissions**, and permit read/write access.

## Local development
Run `python -m http.server 8000` in this folder and open `http://localhost:8000`. Run `python scripts/update_nba.py` to fetch current data if your network permits. Opening `index.html` as `file://` can block JSON fetches, so test the hosted URL or local HTTP server.
