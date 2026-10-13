from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from .models import ImportBatch
from .security import Actor, authorize_case, current_actor, get_db, utc
from .sync import revision

router = APIRouter(prefix="/api/v1")


@router.get("/sync")
def sync_status(case_id: str | None = Query(None), actor: Actor = Depends(current_actor), db=Depends(get_db)):
    if case_id is not None:
        authorize_case(db, actor.user, case_id)
    progress = (
        db.scalar(
            select(ImportBatch.updated_at)
            .where(ImportBatch.tenant_id == actor.user.tenant_id, ImportBatch.case_id == case_id)
            .order_by(ImportBatch.updated_at.desc())
            .limit(1)
        )
        if case_id
        else None
    )
    return {
        "tenant_revision": revision(db, actor.user.tenant_id),
        "case_id": case_id,
        "case_revision": revision(db, actor.user.tenant_id, case_id) if case_id else None,
        "progress_revision": utc(progress).isoformat() if progress else None,
        "mode": "shared-server",
        "database": db.bind.dialect.name,
        "poll_seconds": 5,
    }
