"""The only module allowed to write `daily_schedules`.

- Reads map legacy documents (tasks / strategy_name / all_strategies / confirmed) onto DayPlan.
- Writes use optimistic locking on `version` and always drop the legacy fields.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from db import get_db
from db.collections import Collections
from schemas.day_plan import ActivePlan, ConcurrentModification, DayPlan, Proposal

LEGACY_FIELDS = ("tasks", "strategy_name", "all_strategies", "confirmed", "generated_at")
_NEW_FORMAT_KEYS = ("active", "proposal", "version")


def _legacy_proposal_id(user_id: str, date: str, generated_at: str) -> str:
    # Deterministic so the same legacy document yields the same proposal_id on every read.
    return "legacy-" + uuid.uuid5(uuid.NAMESPACE_URL, f"daypilot:{user_id}:{date}:{generated_at}").hex


def document_to_day_plan(doc: dict | None, *, user_id: str | None = None, date: str | None = None) -> DayPlan:
    if not doc:
        return DayPlan(user_id=user_id or "", date=date or "")
    doc = {k: v for k, v in doc.items() if k not in ("_id", "status")}
    uid, day = doc.get("user_id", user_id or ""), doc.get("date", date or "")

    if any(k in doc for k in _NEW_FORMAT_KEYS):
        return DayPlan.model_validate({
            "user_id": uid, "date": day,
            "active": doc.get("active"), "proposal": doc.get("proposal"),
            "version": doc.get("version", 0),
        })

    # Legacy document (written before the DayPlan refactor)
    generated_at = doc.get("generated_at") or ""
    active = proposal = None
    if doc.get("confirmed") is True:
        active = ActivePlan(
            strategy_name=doc.get("strategy_name") or "",
            tasks=doc.get("tasks") or [],
            confirmed_at=doc.get("confirmed_at") or generated_at,
        )
    elif doc.get("all_strategies"):
        proposal = Proposal(
            proposal_id=_legacy_proposal_id(uid, day, generated_at),
            kind="plan",
            strategies=doc["all_strategies"],
            top_recommendation=doc.get("strategy_name") or "",
            created_at=generated_at,
        )
    return DayPlan(user_id=uid, date=day, active=active, proposal=proposal, version=0)


class DayPlanRepository:
    def __init__(self, db: AsyncIOMotorDatabase | None = None):
        self._db = db

    @property
    def _coll(self):
        return (self._db if self._db is not None else get_db())[Collections.DAILY_SCHEDULES]

    async def get(self, user_id: str, date: str) -> DayPlan:
        doc = await self._coll.find_one({"user_id": user_id, "date": date})
        return document_to_day_plan(doc, user_id=user_id, date=date)

    async def save(self, plan: DayPlan, expected_version: int) -> DayPlan:
        """Persist `plan` iff the stored version is still `expected_version`.

        Raises ConcurrentModification otherwise. Returns the plan as stored (version + 1).
        """
        flt: dict = {"user_id": plan.user_id, "date": plan.date}
        if expected_version == 0:
            # A fresh key, or a legacy document that has no version field yet.
            flt["$or"] = [{"version": 0}, {"version": {"$exists": False}}]
        else:
            flt["version"] = expected_version

        update = {
            "$set": {
                "user_id": plan.user_id,
                "date": plan.date,
                "active": plan.active.model_dump(mode="json") if plan.active else None,
                "proposal": plan.proposal.model_dump(mode="json") if plan.proposal else None,
                "version": expected_version + 1,
                "updated_at": datetime.utcnow().isoformat(),
            },
            "$unset": {f: "" for f in LEGACY_FIELDS},
        }
        try:
            doc = await self._coll.find_one_and_update(
                flt, update, upsert=(expected_version == 0), return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            # upsert tried to insert because the filter missed: a document with a newer
            # version already exists for (user_id, date).
            doc = None
        if doc is None:
            raise ConcurrentModification(
                "version_mismatch",
                f"DayPlan {plan.user_id}/{plan.date} changed (expected version {expected_version}).",
            )
        return document_to_day_plan(doc)
