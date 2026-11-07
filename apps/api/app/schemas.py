from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ProfileIn(BaseModel):
    school_id: UUID
    team_name: str = Field(min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_ .-]+$")
    dob: date
    referral_code: str | None = Field(default=None, max_length=12)


class SchoolIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class TournamentIn(BaseModel):
    school_id: UUID
    sport: str
    name: str = Field(min_length=2, max_length=120)
    match_minutes: int = Field(ge=0, le=200, description="Scheduled length; 0 for untimed sports")
    starts_on: date | None = None
    ends_on: date | None = None


class LineupIn(BaseModel):
    starters: list[UUID] = Field(min_length=1)
    bench: list[UUID] = []


class ScorersIn(BaseModel):
    user_ids: list[UUID] = Field(min_length=1, max_length=2)


class RolesIn(BaseModel):
    roles: list[Literal["player", "scorer", "admin", "superadmin"]]


class ReopenIn(BaseModel):
    scorer_id: UUID


class ConfirmIn(BaseModel):
    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)
    shootout_winner: Literal["home", "away"] | None = None
    official_scorer_id: UUID


class WalkoverIn(BaseModel):
    winner: Literal["home", "away"]


class KnockoutIn(BaseModel):
    stage: Literal["semi", "final", "third_place"]
    home_team_id: UUID
    away_team_id: UUID
    scheduled_start: datetime
    code: str | None = Field(default=None, max_length=12)
    venue: str | None = Field(default=None, max_length=120)


class TournamentPatch(BaseModel):
    match_minutes: int = Field(ge=0, le=200)


class TeamPatch(BaseModel):
    logo_url: str | None = Field(default=None, max_length=500)   # "" clears it
    colour: str | None = Field(default=None, max_length=20)


class AthletePatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=60)
    position: str | None = Field(default=None, max_length=20)
    active: bool | None = None


class PostponeIn(BaseModel):
    new_start: datetime | None = None


class PickIn(BaseModel):
    athlete_id: UUID
    role: Literal["none", "captain", "vice_captain", "key"] = "none"


class TeamIn(BaseModel):
    picks: list[PickIn] = Field(min_length=1, max_length=20)
