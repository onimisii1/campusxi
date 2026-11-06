"""Idempotency keys for money POSTs: a retried tap (flaky signal, double tap) with the same
Idempotency-Key header gets the first response back instead of charging twice."""
import json

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.errors import ApiError


class Idempotent:
    def __init__(self, conn, user_id, request: Request):
        self.conn, self.user_id = conn, user_id
        self.key = request.headers.get("idempotency-key")
        self.route = f"{request.method} {request.url.path}"
        if self.key is not None and not 8 <= len(self.key) <= 80:
            raise ApiError(422, "bad_idempotency_key", "Idempotency-Key must be 8 to 80 characters")
        if self.key:
            # Serialise concurrent retries of the same key.
            conn.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"idem:{user_id}:{self.key}",))

    def replay(self) -> JSONResponse | None:
        if not self.key:
            return None
        row = self.conn.execute("select route, status_code, response from idempotency_keys where user_id = %s "
                                "and key = %s", (self.user_id, self.key)).fetchone()
        if row is None:
            return None
        if row["route"] != self.route:
            raise ApiError(422, "idempotency_key_reused", "that Idempotency-Key was used for a different request")
        return JSONResponse(row["response"], status_code=row["status_code"], headers={"Idempotent-Replay": "true"})

    def save(self, body, status_code: int = 201):
        if self.key:
            self.conn.execute(
                """insert into idempotency_keys (user_id, key, route, status_code, response)
                   values (%s, %s, %s, %s, %s) on conflict do nothing""",
                (self.user_id, self.key, self.route, status_code, json.dumps(jsonable_encoder(body))))
        return body
