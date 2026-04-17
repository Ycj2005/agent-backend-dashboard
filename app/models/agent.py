from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from app.models.pyobjectid import PyObjectId
from datetime import datetime


class AgentRoutePoint(BaseModel):
    lat: float
    lng: float
    timestamp: datetime

class JourneyPoint(BaseModel):
    lat: float
    lng: float
    timestamp: Optional[datetime] = None

class JourneyTracking(BaseModel):
    isActive: bool = False
    startedAt: Optional[datetime] = None
    optimizedRoute: List[Dict[str, float]] = Field(default_factory=list)
    visitedPoints: List[JourneyPoint] = Field(default_factory=list)
    deviationPoints: List[JourneyPoint] = Field(default_factory=list)
    lastLocation: Optional[Dict[str, float]] = None

class AgentBase(BaseModel):
    name: str
    image: str
    address: str
    location: str
    customers: List[PyObjectId] = Field(default_factory=list)

    # NEW FIELDS
    isTracking: Optional[bool] = False
    journeyTracking: Optional[JourneyTracking] = Field(default_factory=JourneyTracking)
    routeDeviation: Optional[List[AgentRoutePoint]] = Field(default_factory=list)
    lastLocation: Optional[Dict] = None
    startedAt: Optional[datetime] = None


class AgentCreate(BaseModel):
    name: str
    image: Optional[str] = None
    location: str


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    image: Optional[str] = None
    location: Optional[str] = None
    customerIds: Optional[List[PyObjectId]] = None


class AgentModel(AgentBase):
    id: PyObjectId = Field(alias="_id")

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {PyObjectId: str}


# from pydantic import BaseModel, Field
# from typing import Optional, List, Union, Dict
# from app.models.pyobjectid import PyObjectId

# class AgentBase(BaseModel):
#     name: str
#     image: str
#     address: str
#     location: str # In NextJS it was a string format "lat,lng" for Agents initially or an object. Let's keep it string usually, or dict if we want to support both. Let's use string here since agent creation passes a string.
#     customers: List[PyObjectId] = Field(default_factory=list)

# class AgentCreate(BaseModel):
#     name: str
#     image: Optional[str] = None
#     location: str

# class AgentUpdate(BaseModel):
#     name: Optional[str] = None
#     image: Optional[str] = None
#     location: Optional[str] = None
#     customerIds: Optional[List[PyObjectId]] = None

# class AgentModel(AgentBase):
#     id: PyObjectId = Field(alias="_id")

#     class Config:
#         populate_by_name = True
#         arbitrary_types_allowed = True
#         json_encoders = {PyObjectId: str}
