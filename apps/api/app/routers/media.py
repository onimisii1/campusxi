"""Photos: profile pictures, team crests and match photos.

Images are resized on the phone before upload, sent as the raw request body (Content-Type
image/png, image/jpeg or image/webp), checked by their first bytes (so a renamed script or an SVG
is refused), stored in the media table and served from /media/{id} with a long cache.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.audit import audit
from app.auth import current_user, require_admin
from app.db import get_conn
from app.errors import ApiError

router = APIRouter(tags=["media"])

MAX_BYTES = 1_500_000
SIGNATURES = {
    "image/png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
    "image/webp": lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP",
}


async def _image(request: Request) -> tuple:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in SIGNATURES:
        raise ApiError(415, "unsupported_image", "upload a PNG, JPEG or WebP image")
    body = await request.body()
    if len(body) > MAX_BYTES:
        raise ApiError(413, "image_too_large", "that image is too large (1.5 MB at most)")
    if len(body) < 100 or not SIGNATURES[content_type](body):
        raise ApiError(415, "not_an_image", "that file isn't a valid image")
    return content_type, body


def _store(conn, owner_id, kind: str, content_type: str, body: bytes) -> str:
    row = conn.execute("insert into media (owner_id, kind, content_type, bytes) values (%s, %s, %s, %s) returning id",
                       (owner_id, kind, content_type, body)).fetchone()
    return f"/media/{row['id']}"


@router.get("/media/{media_id}")
def get_media(media_id: UUID, conn=Depends(get_conn)):
    row = conn.execute("select content_type, bytes from media where id = %s", (media_id,)).fetchone()
    if row is None:
        raise ApiError(404, "media_not_found", "image not found")
    return Response(bytes(row["bytes"]), media_type=row["content_type"], headers={
        "Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'"})


@router.put("/me/avatar")
async def set_avatar(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    content_type, body = await _image(request)
    url = _store(conn, user["id"], "avatar", content_type, body)
    conn.execute("update users set avatar_url = %s where id = %s", (url, user["id"]))
    return {"avatar_url": url}


@router.delete("/me/avatar")
def clear_avatar(user=Depends(current_user), conn=Depends(get_conn)):
    conn.execute("update users set avatar_url = null where id = %s", (user["id"],))
    return {"avatar_url": None}


def _guard(user, school_id):
    if "superadmin" not in user["roles"] and user["school_id"] != school_id:
        raise ApiError(403, "other_school", "you can only manage your own school")


@router.put("/admin/teams/{team_id}/logo")
async def upload_team_logo(team_id: UUID, request: Request, user=Depends(require_admin), conn=Depends(get_conn)):
    team = conn.execute("""select tm.id, tr.school_id from teams tm join tournaments tr on tr.id = tm.tournament_id
                           where tm.id = %s""", (team_id,)).fetchone()
    if team is None:
        raise ApiError(404, "team_not_found", "team not found")
    _guard(user, team["school_id"])
    content_type, body = await _image(request)
    url = _store(conn, user["id"], "team_logo", content_type, body)
    conn.execute("update teams set logo_url = %s where id = %s", (url, team_id))
    audit(conn, user["id"], "team.upload_logo", "team", team_id, url=url)
    return {"logo": url}


@router.put("/admin/matches/{match_id}/photo")
async def upload_match_photo(match_id: UUID, request: Request, user=Depends(require_admin), conn=Depends(get_conn)):
    m = conn.execute("""select m.id, t.school_id from matches m join tournaments t on t.id = m.tournament_id
                        where m.id = %s""", (match_id,)).fetchone()
    if m is None:
        raise ApiError(404, "match_not_found", "match not found")
    _guard(user, m["school_id"])
    content_type, body = await _image(request)
    url = _store(conn, user["id"], "match_photo", content_type, body)
    conn.execute("update matches set photo_url = %s where id = %s", (url, match_id))
    audit(conn, user["id"], "match.upload_photo", "match", match_id, url=url)
    return {"photo_url": url}


@router.delete("/admin/matches/{match_id}/photo")
def clear_match_photo(match_id: UUID, user=Depends(require_admin), conn=Depends(get_conn)):
    m = conn.execute("""select t.school_id from matches m join tournaments t on t.id = m.tournament_id
                        where m.id = %s""", (match_id,)).fetchone()
    if m is None:
        raise ApiError(404, "match_not_found", "match not found")
    _guard(user, m["school_id"])
    conn.execute("update matches set photo_url = null where id = %s", (match_id,))
    return {"photo_url": None}
