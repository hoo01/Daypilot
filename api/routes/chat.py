from fastapi import APIRouter, Depends
from schemas import CoordinatorInput, CoordinatorOutput
from agents import CoordinatorAgent
from api.dependencies import get_coordinator

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/", response_model=CoordinatorOutput)
async def chat(
    body: CoordinatorInput,
    coordinator: CoordinatorAgent = Depends(get_coordinator),
) -> CoordinatorOutput:
    """Main chat endpoint. All user messages come through here."""
    return await coordinator.run(body)
