from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"ok": True}


@router.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}
