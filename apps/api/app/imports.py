"""CSV import for squads and fixtures (PRD B1, B2). All-or-nothing: any bad row rejects the file.

squads.csv:   team,athlete,position[,jersey]   e.g. MCE,Lookman,GK,white (basketball position may be blank)
              position accepts the usual codes (LB, CB, CM, ST, PG, Libero...) and maps them
              to the app's groups; jersey is a colour name or #RRGGBB, once per team is enough.
fixtures.csv: home_team,away_team,scheduled_start,venue[,code,stage]
              scheduled_start is ISO 8601; times without an offset are read as Lagos time (UTC+1).
              code is the organisers' match code (M4, G5); stage is league (default), semi, final
              or third_place.
"""
import csv
import io
import re
from datetime import datetime, timedelta, timezone

from app.engines.scoring.rules import POSITIONS

LAGOS = timezone(timedelta(hours=1))

# Common position codes on team sheets -> the app's position groups, per sport.
POSITION_ALIASES = {
    "football": {
        "GK": {"GK", "G", "GOALKEEPER", "KEEPER"},
        "DEF": {"DEF", "D", "DF", "CB", "LB", "RB", "LWB", "RWB", "WB", "FB", "SW", "DEFENDER"},
        "MID": {"MID", "M", "MF", "CM", "DM", "CDM", "AM", "CAM", "LM", "RM", "MIDFIELDER"},
        "FWD": {"FWD", "F", "FW", "ST", "CF", "SS", "LW", "RW", "ATT", "STRIKER", "FORWARD", "WINGER"},
    },
    "basketball": {
        "G": {"G", "PG", "SG", "GUARD", "POINT GUARD", "SHOOTING GUARD"},
        "F": {"F", "SF", "PF", "FORWARD", "SMALL FORWARD", "POWER FORWARD"},
        "C": {"C", "CENTER", "CENTRE"},
        "P": {"", "P", "PLAYER"},   # positionless basketball: a blank position is fine
    },
    "volleyball": {
        "S": {"S", "SETTER"},
        "OH": {"OH", "OUTSIDE", "OUTSIDE HITTER", "WS", "WING SPIKER", "LH"},
        "OPP": {"OPP", "OP", "RS", "OPPOSITE", "RIGHT SIDE"},
        "MB": {"MB", "MIDDLE", "MIDDLE BLOCKER"},
        "L": {"L", "LIBERO"},
    },
}

JERSEY_COLOURS = {
    "white": "#FAFAFA", "black": "#212121", "blue": "#1565C0", "royal blue": "#1565C0", "navy": "#1A237E",
    "sky blue": "#4FC3F7", "light blue": "#4FC3F7", "red": "#C62828", "maroon": "#7B1F2B", "wine": "#7B1F2B",
    "yellow": "#FDD835", "gold": "#F9A825", "orange": "#EF6C00", "green": "#2E7D32", "lime": "#7CB342",
    "purple": "#6A1B9A", "pink": "#EC407A", "grey": "#9E9E9E", "gray": "#9E9E9E", "brown": "#6D4C41",
    "ash": "#9E9E9E",
}


def normalise_position(sport: str, raw: str) -> str | None:
    code = " ".join(raw.upper().split())
    for pos, names in POSITION_ALIASES[sport].items():
        if code in names:
            return pos
    return None


def jersey_hex(raw: str) -> str | None:
    value = raw.strip().lower()
    if re.fullmatch(r"#[0-9a-f]{6}", value):
        return value.upper()
    return JERSEY_COLOURS.get(" ".join(value.split()))


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
    """Returns ([(team, athlete, position)], {team: '#RRGGBB'}, errors)."""
    rows, errors = _read(text, ("team", "athlete", "position"))
    out, seen, colours = [], set(), {}
    for line, r in rows:
        team, athlete = r["team"], r["athlete"]
        if not team or not athlete:
            errors.append({"row": line, "message": "team and athlete are required"})
            continue
        pos = normalise_position(sport, r["position"])
        if pos is None:
            errors.append({"row": line, "message": f"position {r['position']!r} is not valid for {sport} "
                                                   f"(use {', '.join(sorted(POSITIONS[sport]))} or common codes "
                                                   f"like {'CB, CM, ST' if sport == 'football' else 'PG, SF'})"})
            continue
        if r.get("jersey"):
            colour = jersey_hex(r["jersey"])
            if colour is None:
                errors.append({"row": line, "message": f"jersey colour {r['jersey']!r} isn't recognised "
                                                       f"(use a name like white or blue, or #RRGGBB)"})
                continue
            if colours.setdefault(team.lower(), colour) != colour:
                errors.append({"row": line, "message": f"{team} is given two different jersey colours"})
                continue
        key = (team.lower(), athlete.lower())
        if key in seen:
            errors.append({"row": line, "message": f"{athlete} is listed twice for {team}"})
            continue
        seen.add(key)
        out.append((team, athlete, pos))
    return out, colours, errors


STAGES = ("league", "semi", "final", "third_place")


def parse_fixtures(text: str, team_names: set) -> tuple:
    """Returns ([(home, away, start, venue, code, stage)], errors)."""
    rows, errors = _read(text, ("home_team", "away_team", "scheduled_start"))
    known = {n.lower(): n for n in team_names}
    out, codes = [], set()
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
        code = r.get("code") or None
        if code and len(code) > 12:
            problems.append(f"code {code!r} is longer than 12 characters")
        elif code and code.lower() in codes:
            problems.append(f"code {code!r} is used twice")
        stage = (r.get("stage") or "league").lower().replace(" ", "_").replace("-", "_")
        stage = {"semi_final": "semi", "semifinal": "semi", "3rd_place": "third_place"}.get(stage, stage)
        if stage not in STAGES:
            problems.append(f"stage {r['stage']!r} isn't one of {', '.join(STAGES)}")
        if code:
            codes.add(code.lower())
        if problems:
            errors.extend({"row": line, "message": m} for m in problems)
            continue
        out.append((home, away, start, r.get("venue") or None, code, stage))
    return out, errors


# results.csv:  code,home_team,away_team,home_score,away_score,played_at[,venue]
#               matches played before the app was used (e.g. NUESA Matchday 1).
# stats.csv:    code,team,athlete, then goals,assists (football) or pts,reb,ast,stl,blk (basketball)
RESULT_STAT_COLUMNS = {
    "football": {"goals": "goal", "assists": "assist"},
    "basketball": {"pts": "point", "reb": "rebound", "ast": "assist", "stl": "steal", "blk": "block"},
}


def _count(raw: str):
    raw = raw.strip()
    if raw == "":
        return 0
    return int(raw) if raw.isdigit() else None


def parse_results(text: str, team_names: set, sport: str) -> tuple:
    """Returns ([(code, home, away, home_score, away_score, played_at, venue)], errors)."""
    rows, errors = _read(text, ("code", "home_team", "away_team", "home_score", "away_score", "played_at"))
    known = {n.lower(): n for n in team_names}
    out, codes = [], set()
    for line, r in rows:
        problems = []
        home, away = known.get(r["home_team"].lower()), known.get(r["away_team"].lower())
        problems += [f"unknown team {n!r} (import squads first)" for n, hit in
                     ((r["home_team"], home), (r["away_team"], away)) if not hit]
        if home and home == away:
            problems.append("a team can't play itself")
        code = r["code"]
        if not code or len(code) > 12:
            problems.append("every result needs a code of up to 12 characters (e.g. M1)")
        elif code.lower() in codes:
            problems.append(f"code {code!r} is used twice")
        codes.add(code.lower())
        hs, aws = _count(r["home_score"]), _count(r["away_score"])
        if hs is None or aws is None or r["home_score"] == "" or r["away_score"] == "":
            problems.append("scores must be whole numbers")
        elif hs == aws and sport != "football":
            problems.append(f"{sport} results can't be a draw")
        try:
            played = datetime.fromisoformat(r["played_at"])
            if played.tzinfo is None:
                played = played.replace(tzinfo=LAGOS)
        except ValueError:
            problems.append(f"played_at {r['played_at']!r} is not an ISO date-time")
            played = None
        if problems:
            errors.extend({"row": line, "message": m} for m in problems)
            continue
        out.append((code, home, away, hs, aws, played, r.get("venue") or None))
    return out, errors


def parse_result_stats(text: str, sport: str) -> tuple:
    """Returns ([(row, (code, team, athlete, {event_type: amount}))], errors)."""
    columns = RESULT_STAT_COLUMNS.get(sport)
    if columns is None:
        return [], [{"row": 1, "message": f"stat lines aren't supported for {sport} yet"}]
    rows, errors = _read(text, ("code", "team", "athlete"))
    out = []
    for line, r in rows:
        counts, bad = {}, []
        for col, etype in columns.items():
            n = _count(r.get(col, ""))
            if n is None:
                bad.append(col)
            elif n:
                counts[etype] = n
        if bad:
            errors.append({"row": line, "message": f"{', '.join(bad)} must be whole numbers"})
            continue
        if not (r["code"] and r["team"] and r["athlete"]):
            errors.append({"row": line, "message": "code, team and athlete are required"})
            continue
        out.append((line, (r["code"], r["team"], r["athlete"], counts)))
    return out, errors
