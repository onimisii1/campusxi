"""CSV import for squads and fixtures (PRD B1, B2). All-or-nothing: any bad row rejects the file.

squads.csv:   team,athlete,position          e.g. Engineering,Tunde Bello,MID
fixtures.csv: home_team,away_team,scheduled_start,venue
              scheduled_start is ISO 8601; times without an offset are read as Lagos time (UTC+1).
"""
import csv
import io
from datetime import datetime, timedelta, timezone

from app.engines.scoring.rules import POSITIONS

LAGOS = timezone(timedelta(hours=1))


def _read(text: str, required: tuple) -> tuple:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [h for h in required if h not in headers]
    if missing:
        return [], [{"row": 1, "message": f"missing columns: {', '.join(missing)}"}]
    rows = []
    for line, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if any(row.values()):
            rows.append((line, row))
    if not rows:
        return [], [{"row": 1, "message": "the file has no rows"}]
    return rows, []


def parse_squads(text: str, sport: str) -> tuple:
    rows, errors = _read(text, ("team", "athlete", "position"))
    out, seen = [], set()
    for line, r in rows:
        team, athlete, pos = r["team"], r["athlete"], r["position"].upper()
        if not team or not athlete:
            errors.append({"row": line, "message": "team and athlete are required"})
            continue
        if pos not in POSITIONS[sport]:
            errors.append({"row": line, "message": f"position {r['position']!r} is not valid for {sport} "
                                                   f"(use {', '.join(sorted(POSITIONS[sport]))})"})
            continue
        key = (team.lower(), athlete.lower())
        if key in seen:
            errors.append({"row": line, "message": f"{athlete} is listed twice for {team}"})
            continue
        seen.add(key)
        out.append((team, athlete, pos))
    return out, errors


def parse_fixtures(text: str, team_names: set) -> tuple:
    rows, errors = _read(text, ("home_team", "away_team", "scheduled_start"))
    known = {n.lower(): n for n in team_names}
    out = []
    for line, r in rows:
        home, away = known.get(r["home_team"].lower()), known.get(r["away_team"].lower())
        problems = [f"unknown team {name!r} (import squads first)"
                    for name, hit in ((r["home_team"], home), (r["away_team"], away)) if not hit]
        if home and home == away:
            problems.append("a team can't play itself")
        try:
            start = datetime.fromisoformat(r["scheduled_start"])
            if start.tzinfo is None:
                start = start.replace(tzinfo=LAGOS)
        except ValueError:
            problems.append(f"scheduled_start {r['scheduled_start']!r} is not an ISO date-time")
            start = None
        if problems:
            errors.extend({"row": line, "message": m} for m in problems)
            continue
        out.append((home, away, start, r.get("venue") or None))
    return out, errors
