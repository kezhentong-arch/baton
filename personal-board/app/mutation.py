"""Idempotent writes: the change and its receipt are committed in one SQLite transaction, so a retry with the
same request_id and the same parameters returns the first result instead of writing twice."""
from __future__ import annotations

import hashlib
import json
import re

from app.actions import ActionError, apply_action
from app.i18n import t
from app.model import utc_now


def act(conn, action: str, params: dict, request_id: str | None = None) -> dict:
    if not isinstance(action, str) or not isinstance(params, dict):
        raise ActionError(t("err.act_shape"))
    if request_id is not None and (not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", request_id)):
        raise ActionError(t("err.request_id"))
    payload = json.dumps([action, params], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode()).hexdigest()
    conn.execute("BEGIN IMMEDIATE")
    with conn:
        if request_id:
            old = conn.execute("SELECT digest, result FROM action_receipts WHERE request_id=?", (request_id,)).fetchone()
            if old:
                if old["digest"] != digest:
                    raise ActionError(t("err.request_reused"))
                return json.loads(old["result"])
        result = apply_action(conn, action, params, utc_now(), commit=False).as_dict()
        if request_id:
            conn.execute("INSERT INTO action_receipts(request_id,digest,result) VALUES(?,?,?)",
                         (request_id, digest, json.dumps(result, ensure_ascii=False)))
        return result
