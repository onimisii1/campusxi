"""Profile creation (PRD A1, A2): permanent team name, school, and a declared 18+ date of birth."""
from fastapi import APIRouter, Depends

from app.auth import Identity, current_identity, current_user
from app.clock import utcnow
from app.db import get_conn
from app.errors import ApiError
from app.schemas import ProfileIn

router = APIRouter(tags=["me"])


def age_on(dob, today) -> int:
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


@router.post("/me", status_code=201)
def create_profile(body: ProfileIn, identity: Identity = Depends(current_identity),
                   conn=Depends(get_conn), now=Depends(utcnow)):
    if conn.execute("select 1 from users where id = %s", (identity.user_id,)).fetchone():
        raise ApiError(409, "profile_exists", "you already have a profile")
    if age_on(body.dob, now.date()) < 18:
        raise ApiError(422, "under_18", "CampusXI is for players aged 18 and over")
    if not conn.execute("select 1 from schools where id = %s", (body.school_id,)).fetchone():
        raise ApiError(422, "unknown_school", "choose a school from the list")
    if conn.execute("select 1 from users where lower(team_name) = lower(%s)", (body.team_name,)).fetchone():
        raise ApiError(409, "team_name_taken", "that team name is taken")
    # created_at comes from the same clock as the age check, so the DB's 18+ constraint agrees.
    return conn.execute(
        "insert into users (id, school_id, team_name, dob, created_at) values (%s, %s, %s, %s, %s) returning *",
        (identity.user_id, body.school_id, body.team_name.strip(), body.dob, now),
    ).fetchone()


@router.get("/me")
def get_profile(user: dict = Depends(current_user)):
    return user
