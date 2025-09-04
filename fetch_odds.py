import os
import requests
from typing import List, Dict, Any
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from db import SessionLocal
import models
from datetime import datetime

# Load API key from .env
load_dotenv()
API_KEY = os.getenv("ODDS_API_KEY")
if not API_KEY:
    raise RuntimeError("Missing ODDS_API_KEY in .env")

BASE = "https://api.the-odds-api.com/v4"

# Allowed sportsbooks
ALLOWED_BOOKS = {
    "DraftKings",
    "FanDuel",
    "BetRivers",
    "BetMGM",
    "theScore",
    "Bet365",
    "PointsBet",
    "Caesars",
    "888sport",
    "Sports Interaction",
    "BET99",
    "BetVictor",
    "TonyBet",
    "PowerPlay",
    "Tooniebet",
    "NorthStar Bets",
    "LeoVegas",
    "Rivalry",
    "STX",
    "PROLINE+"
}

# Sports you care about
INTERESTED_SPORTS = {
    # Baseball
    "baseball_mlb",

    # Soccer --- big active leagues
    "soccer_epl",                  # English Premier League
    "soccer_uefa_champs_league",   # UEFA Champions League
    "soccer_spain_la_liga",        # Spain La Liga
    "soccer_germany_bundesliga",   # Germany Bundesliga
    "soccer_france_ligue_one",     # France Ligue 1
    "soccer_italy_serie_a",        # Italy Serie A
    "soccer_usa_mls",              # Major League Soccer (ongoing in US/Canada)

    # Cricket --- active tournaments/leagues
    "cricket_big_bash",
    "cricket_caribbean_premier_league",
    "cricket_the_hundred",

    # Tennis --- Grand Slams & tours
    "tennis_atp_us_open",
    "tennis_wta_us_open"
}

BASE_PARAMS = {
    "regions": "us",
    "markets": "h2h,spreads,totals",
    "oddsFormat": "decimal"
}

def decimal_to_american(decimal):
    if decimal >= 2.0:
        return f"+{int((decimal - 1) * 100)}"
    else:
        return f"{int(-100 / (decimal - 1))}"


def upsert_odds(db: Session, rows: List[Dict[str, Any]]):
    """Insert or update odds rows in the DB"""
    for r in rows:
        existing = db.query(models.Odds).filter_by(
            sportsbook=r["sportsbook"],
            league=r["league"],
            event=r["event"],
            market=r["market"],
            outcome=r["outcome"],
            line=r["line"]
        ).first()

        if existing:
            existing.odds_decimal = r["odds_decimal"]
            existing.odds_american = r["odds_american"]
            existing.commence_time = r.get("commence_time")
            existing.event_date = r.get("event_date")
        else:
            db.add(models.Odds(**r))

    db.commit()

def normalize_payload(payload) -> List[Dict[str, Any]]:
    """Convert API response to DB rows"""
    rows = []
    for event in payload:
        league_guess = event.get("sport_title", "") or event.get("sport_key", "")
        title = f'{event.get("home_team", "")} vs {event.get("away_team", "")}'

        commence_time_raw = event.get("commence_time")
        commence_time = None
        event_date = None
        if commence_time_raw:
            try:
                commence_time = datetime.fromisoformat(commence_time_raw.replace("Z", "+00:00"))
                event_date = commence_time.date().isoformat()  # --- just the date
            except Exception:
                pass

        for book in event.get("bookmakers", []):
            sportsbook = book.get("title") or book.get("key")
            if sportsbook not in ALLOWED_BOOKS:
                continue

            for m in book.get("markets", []):
                market_key = m.get("key", "h2h").lower()
                if "lay" in market_key:
                    continue

                for o in m.get("outcomes", []):
                    try:
                        odds_val = float(o.get("price", 0))
                    except:
                        odds_val = 0.0

                    line_val = o.get("point")
                    american_val = decimal_to_american(odds_val)

                    rows.append({
                        "sportsbook": sportsbook,
                        "league": league_guess.lower(),
                        "event": title,
                        "market": market_key,
                        "outcome": o.get("name", ""),
                        "line": str(line_val) if line_val is not None else None,
                        "odds_decimal": odds_val,
                        "odds_american": american_val,   # --- store American odds
                        "commence_time": commence_time,
                        "event_date": event_date          # --- store event date
                    })
    return rows

def main():
    db = SessionLocal()
    try:
        sports_resp = requests.get(
            f"{BASE}/sports/",
            params={"apiKey": API_KEY},
            timeout=20
        )
        sports_resp.raise_for_status()
        sports_list = sports_resp.json()

        print(f"Found {len(sports_list)} sports...")

        total_rows = 0
        for sport in sports_list:
            sport_key = sport["key"]

            if sport_key not in INTERESTED_SPORTS:
                continue
            if "_winner" in sport_key:
                print(f"Skipping {sport_key} (outrights only)")
                continue

            endpoint = f"{BASE}/sports/{sport_key}/odds"
            print(f"Fetching odds for {sport_key}...")

            try:
                resp = requests.get(
                    endpoint,
                    params={**BASE_PARAMS, "apiKey": API_KEY},
                    timeout=20
                )
                if resp.status_code == 200:
                    payload = resp.json()
                    rows = normalize_payload(payload)
                    print(f"Parsed {len(rows)} rows for {sport_key}")
                    upsert_odds(db, rows)
                    total_rows += len(rows)
                else:
                    msg = resp.json().get("message", resp.text)
                    print(f"Skipped {sport_key}: HTTP {resp.status_code} - {msg}")
            except Exception as e:
                print(f"Error fetching {sport_key}: {e}")

        print(f"Done. Total odds rows saved: {total_rows}")
    finally:
        db.close()

if __name__ == "__main__":
    main()


