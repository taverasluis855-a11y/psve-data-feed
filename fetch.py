#!/usr/bin/env python3
"""PSVE data feeder: pulls soccer events from Polymarket Gamma API and writes
a pre-filtered data/soccer.json that the PSVE app consumes via GitHub."""

import json
import os
import time
import urllib.request
from datetime import datetime, timezone

GAMMA = "https://gamma-api.polymarket.com"
MIN_VOLUME = 5000  # PSVE v2.1: $5K minimum

SOCCER_HINTS = [
    "premier league", "bundesliga", "la liga", "serie a", "ligue 1",
    "champions league", "europa league", "mls", "eredivisie",
    "soccer", "epl", "ucl", "fc ", "afc", " united", " city",
]


def get(url: str, retries: int = 3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "PSVE-feeder/2.1", "Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2**i)
    raise last


def looks_like_soccer(title: str, slug: str) -> bool:
    t = (title + " " + slug).lower()
    return " vs " in t or " v " in t or any(h in t for h in SOCCER_HINTS)


def parse_teams(title: str):
    parts = title.replace(" vs. ", " vs ").split(" vs ")
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return None


def safe_list(x):
    if isinstance(x, str):
        try:
            x = json.loads(x)
        except Exception:  # noqa: BLE001
            return []
    return [str(v) for v in x] if isinstance(x, list) else []


def main() -> None:
    os.makedirs("data", exist_ok=True)
    health = {
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "ok": False,
        "reason": None,
        "matchCount": 0,
    }
    try:
        events = get(
            f"{GAMMA}/events?active=true&closed=false&limit=200&order=volume24hr&ascending=false"
        )
    except Exception as e:  # noqa: BLE001
        health["reason"] = f"gamma fetch failed: {e}"
        with open("data/health.json", "w") as f:
            json.dump(health, f, indent=2)
        raise

    out = []
    discarded = 0
    for ev in events or []:
        title = ev.get("title", "")
        slug = ev.get("slug", "")
        if not looks_like_soccer(title, slug):
            continue
        teams = parse_teams(title)
        if not teams:
            continue
        volume = float(ev.get("volume") or 0)
        if volume < MIN_VOLUME:
            discarded += 1
            continue
        markets = []
        for mk in ev.get("markets") or []:
            outcomes = safe_list(mk.get("outcomes"))
            prices = [float(p) for p in safe_list(mk.get("outcomePrices"))]
            if len(outcomes) < 2 or len(outcomes) != len(prices):
                continue
            markets.append(
                {
                    "marketType": mk.get("groupItemTitle") or mk.get("question"),
                    "question": mk.get("question"),
                    "outcomes": [
                        {"name": n, "askCents": round(p * 100)} for n, p in zip(outcomes, prices)
                    ],
                    "volumeUsd": float(mk.get("volume") or 0),
                }
            )
        if not markets:
            continue
        out.append(
            {
                "polymarketEventId": str(ev.get("id")),
                "slug": slug,
                "title": title,
                "homeTeam": teams[0],
                "awayTeam": teams[1],
                "league": None,
                "kickoff": ev.get("startDate"),
                "volumeUsd": volume,
                "markets": markets,
            }
        )

    health.update(ok=True, matchCount=len(out), discardedLowVolume=discarded)
    with open("data/soccer.json", "w") as f:
        json.dump({"health": health, "matches": out}, f, indent=1)
    with open("data/health.json", "w") as f:
        json.dump(health, f, indent=2)
    print(f"wrote {len(out)} matches, discarded {discarded}")


if __name__ == "__main__":
    main()
