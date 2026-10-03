import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

from auth import get_current_user
from planner_service import create_plan
from recommendations import generate_recommendations

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "frontend" / "templates"))

class HomeRequest(BaseModel):
  budget: float = Field(ge=1, le=50000000)
  rooms: str = Field(min_length=1, max_length=30)
  style: str = Field(default="Modern", min_length=1, max_length=60)
  room_types: list[str] = Field(default_factory=list, max_length=6)
  num_lights: int = Field(default=0, ge=0, le=500)
  num_fans: int = Field(default=0, ge=0, le=500)
  num_furniture: int = Field(default=0, ge=0, le=500)
  num_dining_tables: int = Field(default=0, ge=0, le=100)
  platforms: list[str] = Field(default_factory=lambda: ["Amazon", "Flipkart", "IKEA"], max_length=8)
  preferences: str = Field(default="", max_length=1000)

  @field_validator("rooms", "style", mode="before")
  @classmethod
  def trim_required_text(cls, value):
    return value.strip() if isinstance(value, str) else value


def get_home_recommendations(budget, rooms, style, room_types, platforms, preferences,
                             num_lights=0, num_fans=0, num_furniture=0, num_dining_tables=0):
  result, _ = generate_recommendations("home", {
    "budget": budget,
    "rooms": rooms,
    "style": style,
    "room_types": room_types or [],
    "platforms": platforms or [],
    "preferences": preferences or "",
    "num_lights": num_lights,
    "num_fans": num_fans,
    "num_furniture": num_furniture,
    "num_dining_tables": num_dining_tables,
  })
  return json.dumps(result, ensure_ascii=False)

@router.get("/home-planner")
async def home_planner_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request=request, name="home_planner.html")

@router.post("/generate-home")
async def generate_home(data: HomeRequest, user: dict = Depends(get_current_user)):
  payload = data.model_dump()
  preferences = {key: payload[key] for key in (
    "rooms", "style", "room_types", "platforms", "preferences",
    "num_lights", "num_fans", "num_furniture", "num_dining_tables")}
  return create_plan(user, "home", payload, preferences)
