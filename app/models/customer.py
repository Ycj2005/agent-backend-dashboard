from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from app.models.pyobjectid import PyObjectId

class CustomerLocation(BaseModel):
    lat: float
    lng: float

class CustomerBase(BaseModel):
    loan: str
    name: str
    address: str
    location: CustomerLocation
    agentId: Optional[PyObjectId] = None
    verifiedAgentImage: Optional[str] = None
    cashCollected: Optional[Any] = 0
    verificationScore: Optional[int] = 0
    verificationStatus: Optional[str] = "pending"
    collectedAt: Optional[Any] = None
    deviceModel: Optional[str] = None
    deviceImei: Optional[str] = None
    networkOperator: Optional[str] = None

class CustomerCreate(BaseModel):
    name: str
    location: str # Usually incoming as "lat, lng" string
    loan: Optional[str] = ""
    agentId: Optional[PyObjectId] = None
    cashCollected: Optional[Any] = 0

class CustomerUpdate(BaseModel):
    verifiedAgentImage: Optional[str] = None
    agentId: Optional[PyObjectId] = None
    loan: Optional[str] = None
    cashCollected: Optional[Any] = None
    verificationScore: Optional[int] = None
    verificationStatus: Optional[str] = None
    collectedAt: Optional[Any] = None
    deviceModel: Optional[str] = None
    deviceImei: Optional[str] = None
    networkOperator: Optional[str] = None

class CustomerModel(CustomerBase):
    id: PyObjectId = Field(alias="_id")

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {PyObjectId: str}
