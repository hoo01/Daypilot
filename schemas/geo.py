from pydantic import BaseModel, Field


class GeoInput(BaseModel):
    user_id: str
    origin: str                      # current location or address
    destination: str
    must_arrive_by: str              # e.g. "14:00"
    departure_buffer_min: int = 10


class GeoOutput(BaseModel):
    departure_time: str              # e.g. "11:20"
    arrival_time: str                # e.g. "11:50"
    route: str                       # e.g. "subway Line 2"
    commute_duration_min: int
    available_window_min: int        # usable work time before departure
    recommended_tasks_before_departure: list[str] = Field(default_factory=list)
