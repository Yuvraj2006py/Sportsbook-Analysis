# main.py
from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone

from db import SessionLocal
import models

app = FastAPI(title="Arbitrage API")

# ---- CORS (dev-friendly) ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # during local dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- DB dependency ----
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------- Helpers ----------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    # Return ISO in UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()

def _coerce_line(line_val: Optional[str]) -> Optional[str]:
    """
    Normalize line so we can compare like-for-like.
    Leave None for H2H.
    For numeric-like strings, keep the original string form to ensure exact match.
    """
    if line_val is None:
        return None
    s = str(line_val).strip()
    return s if s else None

def _apply_row_level_filters(
    rows: List[models.Odds],
    leagues: Optional[set],
    markets: Optional[set],
    sportsbooks: Optional[set],
    min_hours_ahead: float
) -> List[models.Odds]:
    """Filter raw odds rows early, before grouping."""
    cutoff = _now_utc() + timedelta(hours=min_hours_ahead)
    out = []
    for o in rows:
        # Time filter (exclude live/started or too soon)
        if o.commence_time is None:
            # If we don't know the time, skip (safer)
            continue
        # Treat naive as UTC if it slipped in
        ct = o.commence_time if o.commence_time.tzinfo else o.commence_time.replace(tzinfo=timezone.utc)
        if ct <= cutoff:
            continue

        if leagues and (o.league or "").lower() not in leagues:
            continue
        if markets and (o.market or "").lower() not in markets:
            continue
        if sportsbooks and (o.sportsbook or "") not in sportsbooks:
            continue

        out.append(o)
    return out

def _group_by_event_market_line(rows: List[models.Odds]) -> Dict[Tuple[str, str, Optional[str]], List[models.Odds]]:
    """
    Group rows by (event, market, line_key).
    - H2H: line_key=None
    - Totals: line_key=exact total points (string normalized)
    - Spreads: line_key=absolute value of spread (e.g., 2.5 groups +2.5 with -2.5)
    """
    from collections import defaultdict

    def norm_abs_spread(line_val: Optional[str]) -> Optional[str]:
        if line_val is None:
            return None
        try:
            v = abs(float(str(line_val).strip()))
            # Canonical format without trailing zeros
            s = ("%g" % round(v, 3))
            return s
        except Exception:
            # Fallback to raw string if not numeric
            return _coerce_line(line_val)

    buckets: Dict[Tuple[str, str, Optional[str]], List[models.Odds]] = defaultdict(list)
    for o in rows:
        mkt = (o.market or "").lower()
        if mkt == "spreads":
            line_key = norm_abs_spread(o.line)
        elif mkt == "totals":
            line_key = _coerce_line(o.line)
        else:
            line_key = None
        key = (o.event or "", mkt, line_key)
        buckets[key].append(o)
    return buckets

def _best_price_by_outcome(group_rows: List[models.Odds]) -> Dict[str, models.Odds]:
    """
    For a group (same event/market/line_key), choose the single best (max) odds per outcome across sportsbooks.
    Special handling for spreads: collapse outcomes into two sides by sign (plus/minus) at the same absolute line.
    """
    best: Dict[str, models.Odds] = {}
    if not group_rows:
        return best

    mkt = (group_rows[0].market or "").lower()
    spreads = (mkt == "spreads")

    for o in group_rows:
        if spreads:
            side_key = None
            try:
                ln = float(str(o.line))
                side_key = "plus" if ln >= 0 else "minus"
            except Exception:
                # If we can't parse, fall back to outcome string
                side_key = o.outcome or ""
            outcome_key = side_key
        else:
            outcome_key = o.outcome or ""

        prev = best.get(outcome_key)
        if prev is None or (o.odds_decimal or 0.0) > (prev.odds_decimal or 0.0):
            best[outcome_key] = o
    return best

def _calc_arb_margin(best_by_outcome: Dict[str, models.Odds]) -> float:
    """
    Return margin as a percent (e.g., 1.23 for 1.23%).
    Arbitrage when inverse-sum < 1
    """
    inv_sum = 0.0
    for o in best_by_outcome.values():
        odd = float(o.odds_decimal or 0.0)
        if odd <= 0:
            return 0.0
        inv_sum += 1.0 / odd
    if inv_sum < 1.0:
        return (1.0 - inv_sum) * 100.0
    return 0.0

def _collect_books_summary(rows: List[models.Odds]) -> Dict[str, Any]:
    """
    Tiny helper for a heatmap/summary: how often each book offers the best price in its group.
    We compute on a 'per (event, market, line, outcome)' basis.
    """
    summary: Dict[str, Dict[str, float]] = {}
    # group by (event, market, line, outcome)
    from collections import defaultdict
    by_emo: Dict[Tuple[str, str, Optional[str], str], List[models.Odds]] = defaultdict(list)
    for o in rows:
        by_emo[(o.event or "", (o.market or "").lower(), _coerce_line(o.line), (o.outcome or ""))].append(o)

    best_counts: Dict[str, int] = {}
    avg_odds_sum: Dict[str, float] = {}
    avg_odds_n: Dict[str, int] = {}

    for _, lst in by_emo.items():
        # find the single best
        best = None
        for o in lst:
            if best is None or (o.odds_decimal or 0.0) > (best.odds_decimal or 0.0):
                best = o
        if best and best.sportsbook:
            best_counts[best.sportsbook] = best_counts.get(best.sportsbook, 0) + 1

        # accumulate average odds per book
        for o in lst:
            if not o.sportsbook:
                continue
            avg_odds_sum[o.sportsbook] = avg_odds_sum.get(o.sportsbook, 0.0) + float(o.odds_decimal or 0.0)
            avg_odds_n[o.sportsbook] = avg_odds_n.get(o.sportsbook, 0) + 1

    books = set(list(best_counts.keys()) + list(avg_odds_sum.keys()))
    for b in books:
        summary[b] = {
            "best_price_count": best_counts.get(b, 0),
            "avg_offered_decimal": (avg_odds_sum[b] / avg_odds_n[b]) if avg_odds_n.get(b) else None,
        }
    return summary

def _detect_middles_totals(
    rows: List[models.Odds],
    min_width: float = 0.5,
    min_price: float = 1.87,
) -> List[Dict[str, Any]]:
    """
    Conservative, totals-only middles:
      - For a given event, look at totals market.
      - If Over line at book A is strictly less than Under line at book B, that's a 'gap' (potential middle).
      - Require both prices >= 1.87 (~ -115) to avoid trash.
    NOTE: This is not guaranteed profit; it's just a candidate where a 'middle' can occur.
    """
    candidates: List[Dict[str, Any]] = []
    # Group by event
    from collections import defaultdict
    by_event: Dict[str, List[models.Odds]] = defaultdict(list)
    for o in rows:
        if (o.market or "").lower() != "totals":
            continue
        by_event[o.event or ""].append(o)

    for event, lst in by_event.items():
        # Partition by outcome
        overs = [o for o in lst if (o.outcome or "").lower().startswith("over")]
        unders = [o for o in lst if (o.outcome or "").lower().startswith("under")]
        if not overs or not unders:
            continue

        # Parse numeric lines; skip non-numeric
        def read_line(x: models.Odds) -> Optional[float]:
            try:
                return float(str(x.line))
            except Exception:
                return None

        # Build per-book best Over (max odds) per distinct line and same for Under
        from collections import defaultdict
        best_over_by_line: Dict[float, models.Odds] = {}
        best_under_by_line: Dict[float, models.Odds] = {}

        for o in overs:
            l = read_line(o)
            if l is None:
                continue
            prev = best_over_by_line.get(l)
            if prev is None or (o.odds_decimal or 0.0) > (prev.odds_decimal or 0.0):
                best_over_by_line[l] = o
        for u in unders:
            l = read_line(u)
            if l is None:
                continue
            prev = best_under_by_line.get(l)
            if prev is None or (u.odds_decimal or 0.0) > (prev.odds_decimal or 0.0):
                best_under_by_line[l] = u

        if not best_over_by_line or not best_under_by_line:
            continue

        # Try pairs: Over at lower total, Under at higher total
        over_lines = sorted(best_over_by_line.keys())
        under_lines = sorted(best_under_by_line.keys())

        for lo in over_lines:
            over_row = best_over_by_line[lo]
            over_price = float(over_row.odds_decimal or 0.0)
            if over_price < float(min_price):
                continue
            for lu in under_lines:
                if lu <= lo:
                    continue
                under_row = best_under_by_line[lu]
                under_price = float(under_row.odds_decimal or 0.0)
                if under_price < float(min_price):
                    continue

                width = lu - lo
                if width < float(min_width):  # require minimum gap
                    continue

                # Candidate
                ct = over_row.commence_time or under_row.commence_time
                candidates.append({
                    "event": event,
                    "market": "totals",
                    "over": {
                        "sportsbook": over_row.sportsbook,
                        "line": str(lo),
                        "odds_decimal": over_row.odds_decimal,
                        "odds_american": over_row.odds_american,
                    },
                    "under": {
                        "sportsbook": under_row.sportsbook,
                        "line": str(lu),
                        "odds_decimal": under_row.odds_decimal,
                        "odds_american": under_row.odds_american,
                    },
                    "middle_width": width,
                    "commence_time": _iso(ct),
                    "event_date": getattr(over_row, "event_date", None) or getattr(under_row, "event_date", None),
                    "note": "Totals middle candidate (not guaranteed profit).",
                })
    return candidates


# ---------- Endpoints ----------

@app.get("/health")
def health():
    return {"ok": True, "time": _iso(_now_utc())}

@app.get("/leagues")
def list_leagues(db: Session = Depends(get_db)):
    q = db.query(models.Odds.league).distinct().all()
    leagues = sorted({(row[0] or "").lower() for row in q if row[0]})
    return {"leagues": leagues}

@app.get("/markets")
def list_markets(db: Session = Depends(get_db)):
    q = db.query(models.Odds.market).distinct().all()
    markets = sorted({(row[0] or "").lower() for row in q if row[0]})
    return {"markets": markets}

@app.get("/books")
def list_books(db: Session = Depends(get_db)):
    q = db.query(models.Odds.sportsbook).distinct().all()
    books = sorted({row[0] for row in q if row[0]})
    return {"sportsbooks": books}


@app.get("/arbitrage")
def get_arbitrage(
    db: Session = Depends(get_db),
    leagues: Optional[str] = Query(None, description="Comma-separated league keys (lowercase)"),
    markets: Optional[str] = Query(None, description="Comma-separated markets, e.g. h2h,spreads,totals"),
    sportsbooks: Optional[str] = Query(None, description="Comma-separated sportsbook titles to include"),
    min_margin: float = Query(0.0, description="Minimum arbitrage margin in percent (e.g. 1.0 for 1%)"),
    min_hours_ahead: float = Query(0.0, alias="time", description="Exclude games starting before X hours from now"),
    show_middles: bool = Query(False, description="Include totals 'middle' candidates"),
    middle_min_width: float = Query(0.5, description="Minimum gap between Over and Under totals for middle"),
    middle_min_price: float = Query(1.87, description="Minimum decimal price for Over/Under in middle"),
    sort_by: str = Query("profit", description="profit|date|league|event"),
    sort_dir: str = Query("desc", description="asc|desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
):
    """
    Find arbitrage opportunities with filters & sorting.
    - Requires same exact line for spreads/totals; H2H has no line.
    - Excludes games starting before `min_hours_ahead`.
    - Returns pagination + optional middles (+ a small books summary).

    NOTES:
    - min_margin is in PERCENT.
    - leagues/markets/sportsbooks accept comma-separated values.
    """

    # Parse multi-select filters
    leagues_set = {s.strip().lower() for s in leagues.split(",")} if leagues else None
    markets_set = {s.strip().lower() for s in markets.split(",")} if markets else None
    books_set = {s.strip() for s in sportsbooks.split(",")} if sportsbooks else None

    # Load and pre-filter rows
    rows = db.query(models.Odds).all()
    rows = _apply_row_level_filters(rows, leagues_set, markets_set, books_set, min_hours_ahead)

    # Books summary for heatmap/analytics
    books_summary = _collect_books_summary(rows)

    # Group and compute arbs
    groups = _group_by_event_market_line(rows)
    opportunities: List[Dict[str, Any]] = []

    for (event, market, line_norm), group_rows in groups.items():
        # Collate best price per outcome
        best_by_outcome = _best_price_by_outcome(group_rows)

        # If there's only one outcome, skip
        if len(best_by_outcome) < 2:
            continue

        # Require same line within group (already enforced by grouping key)
        # Compute margin
        margin = _calc_arb_margin(best_by_outcome)
        if margin <= 0 or margin < float(min_margin):
            continue

        # Pick a commence_time & league from any row (they're same event)
        sample = group_rows[0]
        ct = sample.commence_time
        league_val = (sample.league or "").lower()
        event_date = getattr(sample, "event_date", None)

        # Build best-odds payload
        best_list = []
        for outc, row in best_by_outcome.items():
            best_list.append({
                "sportsbook": row.sportsbook,
                "outcome": outc,
                "odds_decimal": float(row.odds_decimal or 0.0),
                "odds_american": row.odds_american,
                "line": _coerce_line(row.line),
            })

        opportunities.append({
            "event": event,
            "league": league_val,
            "market": market,
            "line": line_norm,  # None for h2h
            "commence_time": _iso(ct),
            "event_date": event_date,
            "profit_margin": round(margin, 3),
            "best_odds": best_list,
        })

    # Sorting
    reverse = (sort_dir.lower() == "desc")

    def sort_key(item: Dict[str, Any]):
        if sort_by == "date":
            return item.get("commence_time") or ""
        if sort_by == "league":
            return item.get("league") or ""
        if sort_by == "event":
            return item.get("event") or ""
        # default: profit
        return item.get("profit_margin", 0.0)

    opportunities.sort(key=sort_key, reverse=reverse)

    # Pagination
    total = len(opportunities)
    start = (page - 1) * limit
    end = start + limit
    opportunities_page = opportunities[start:end]

    # Optional middles (totals-only)
    middles: List[Dict[str, Any]] = []
    if show_middles:
        middles = _detect_middles_totals(rows, min_width=middle_min_width, min_price=middle_min_price)
        # sort middles by width descending, then date
        middles.sort(key=lambda x: (x.get("middle_width", 0.0), x.get("commence_time", "")), reverse=True)

    return {
        "filters": {
            "leagues": sorted(list(leagues_set)) if leagues_set else None,
            "markets": sorted(list(markets_set)) if markets_set else None,
            "sportsbooks": sorted(list(books_set)) if books_set else None,
            "min_margin": float(min_margin),
            "min_hours_ahead": float(min_hours_ahead),
            "show_middles": show_middles,
            "middle_min_width": float(middle_min_width),
            "middle_min_price": float(middle_min_price),
        },
        "sort": {"by": sort_by, "dir": sort_dir},
        "page": page,
        "limit": limit,
        "total": total,
        "opportunities": opportunities_page,
        "middles": middles,
        "books_summary": books_summary,
        "generated_at": _iso(_now_utc()),
    }
