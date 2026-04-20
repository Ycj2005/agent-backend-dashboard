from fastapi import APIRouter, HTTPException, status, Query
from app.core.database import get_collection
from app.models.customer import CustomerCreate, CustomerUpdate
from app.utils.geocoding import reverse_geocode
from bson import ObjectId
from pydantic import BaseModel

router = APIRouter(prefix="/customers", tags=["Customers"])

@router.post("", response_model=dict)
async def create_customer(customer: CustomerCreate):
    try:
        # Parse location string "lat, lng"
        lat, lng = 0.0, 0.0
        parts = [p.strip() for p in customer.location.split(",")]
        if len(parts) == 2:
            try:
                lat, lng = float(parts[0]), float(parts[1])
            except ValueError:
                return {"status": 400, "msg": "Location must be 'lat, lng' e.g. 19.076, 72.877"}
        else:
             return {"status": 400, "msg": "Location must be 'lat, lng' e.g. 19.076, 72.877"}
             
        parsed_location = {"lat": lat, "lng": lng}
        auto_address = await reverse_geocode(lat, lng)
        
        cust_dict = {
            "name": customer.name,
            "loan": customer.loan or "",
            "location": parsed_location,
            "address": auto_address,
            "cashCollected": customer.cashCollected or "",
            "verificationScore": 0,
            "verificationStatus": "pending"
        }
        
        if customer.agentId and ObjectId.is_valid(customer.agentId):
             cust_dict["agentId"] = ObjectId(customer.agentId)
             
        customer_coll = get_collection("customers")
        result = await customer_coll.insert_one(cust_dict)
        cust_dict["_id"] = str(result.inserted_id)
        if "agentId" in cust_dict:
             cust_dict["agentId"] = str(cust_dict["agentId"])
             
        # Link to agent
        if customer.agentId and ObjectId.is_valid(customer.agentId):
             agent_coll = get_collection("agents")
             await agent_coll.update_one(
                 {"_id": ObjectId(customer.agentId)},
                 {"$addToSet": {"customers": result.inserted_id}}
             )

        return {"status": 200, "msg": "Customer created and linked to agent successfully!", "data": cust_dict}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("", response_model=dict)
async def get_customers():
    try:
        customer_coll = get_collection("customers")
        customers = await customer_coll.find().to_list(None)
        for c in customers:
            c["_id"] = str(c["_id"])
            if "agentId" in c and c["agentId"]:
                c["agentId"] = str(c["agentId"])
        return {"status": 200, "msg": "Customers fetched successfully!", "data": customers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/search", response_model=dict)
async def search_customer(loan: str = Query(...)):
    if not loan:
        return {"status": 400, "msg": "Loan number required"}
        
    try:
        customer_coll = get_collection("customers")
        pipeline = [
            {"$match": {"loan": loan}},
            {
                "$lookup": {
                    "from": "agents",
                    "localField": "agentId",
                    "foreignField": "_id",
                    "as": "agentId"
                }
            },
            {"$unwind": {"path": "$agentId", "preserveNullAndEmptyArrays": True}}
        ]
        results = await customer_coll.aggregate(pipeline).to_list(1)
        if not results:
             return {"status": 404, "msg": "Customer not found"}
             
        c = results[0]
        c["_id"] = str(c["_id"])
        if "agentId" in c and c["agentId"]:
             c["agentId"]["_id"] = str(c["agentId"]["_id"])
             c["agentId"]["customers"] = [str(cust_id) for cust_id in c["agentId"].get("customers", [])]
             
        return {"status": 200, "msg": "Customer found", "data": c}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Legacy/Alias route for singular 'customer'
@router.get("/customer/search", response_model=dict, include_in_schema=False)
async def search_customer_alias(loan: str = Query(...)):
    return await search_customer(loan)

class ResetVerificationReq(BaseModel):
    customerId: str

@router.post("/reset-verification", response_model=dict)
async def reset_verification(req: ResetVerificationReq):
    try:
        if not req.customerId or not ObjectId.is_valid(req.customerId):
             return {"error": "Customer ID is required and must be valid", "status": 400}
             
        customer_coll = get_collection("customers")
        result = await customer_coll.find_one_and_update(
            {"_id": ObjectId(req.customerId)},
            {"$set": {"verifiedAgentImage": None}},
            return_document=True
        )
        
        if not result:
             return {"error": "Customer not found", "status": 404}
             
        result["_id"] = str(result["_id"])
        if "agentId" in result and result["agentId"]:
             result["agentId"] = str(result["agentId"])
             
        return {"success": True, "message": "Verification reset successfully", "customer": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{id}", response_model=dict)
async def get_customer(id: str):
    if not ObjectId.is_valid(id):
         raise HTTPException(status_code=400, detail="Invalid Customer ID format")
    try:
        customer_coll = get_collection("customers")
        pipeline = [
            {"$match": {"_id": ObjectId(id)}},
            {
                "$lookup": {
                    "from": "agents",
                    "localField": "agentId",
                    "foreignField": "_id",
                    "as": "agentId"
                }
            },
            {"$unwind": {"path": "$agentId", "preserveNullAndEmptyArrays": True}}
        ]
        results = await customer_coll.aggregate(pipeline).to_list(1)
        if not results:
             return {"status": 404, "msg": "Customer not found."}
             
        customer = results[0]
        customer["_id"] = str(customer["_id"])
        if "agentId" in customer and customer["agentId"]:
             customer["agentId"]["_id"] = str(customer["agentId"]["_id"])
             if "customers" in customer["agentId"]:
                  customer["agentId"]["customers"] = [str(c_id) for c_id in customer["agentId"]["customers"]]
             
        return {"status": 200, "msg": "Data fetched successfully.", "data": customer}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/{id}", response_model=dict)
async def update_customer(id: str, payload: CustomerUpdate):
    if not ObjectId.is_valid(id):
         raise HTTPException(status_code=400, detail="Invalid Customer ID format")
         
    try:
        customer_coll = get_collection("customers")
        
        updates = payload.model_dump(exclude_unset=True)
        if "agentId" in updates and updates["agentId"]:
             updates["agentId"] = ObjectId(updates["agentId"])
             
        if not updates:
             return {"status": 400, "msg": "No fields to update."}
             
        result = await customer_coll.find_one_and_update(
            {"_id": ObjectId(id)},
            {"$set": updates},
            return_document=True
        )
        
        if not result:
             return {"status": 404, "msg": "Customer not found."}
             
        result["_id"] = str(result["_id"])
        if "agentId" in result and result["agentId"]:
             result["agentId"] = str(result["agentId"])

        return {"status": 200, "msg": "Customer updated successfully.", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/collect-cash/{customerId}")
async def collect_cash(customerId: str, payload: dict):
    if not ObjectId.is_valid(customerId):
        raise HTTPException(status_code=400, detail="Invalid Customer ID")

    amount = payload.get("amount", 0)
    agentId = payload.get("agentId")
    agentName = payload.get("agentName", "Agent")

    if not agentId or not ObjectId.is_valid(agentId):
        raise HTTPException(status_code=400, detail="Invalid Agent ID")

    from datetime import datetime
    customer_coll = get_collection("customers")
    notif_coll = get_collection("notifications")

    # Update Customer
    customer = await customer_coll.find_one_and_update(
        {"_id": ObjectId(customerId)},
        {
            "$set": {
                "cashCollected": amount,
                "verificationStatus": "verified",
                "collectedAt": datetime.utcnow(),
            }
        },
        return_document=True,
    )

    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Create Notification
    notification = {
        "agentId": ObjectId(agentId),
        "agentName": agentName,
        "customerId": ObjectId(customerId),
        "customerName": customer.get("name"),
        "type": "cash_collected",
        "message": f"{agentName} collected Rs.{amount} from {customer.get('name')}",
        "timestamp": datetime.utcnow(),
        "read": False,
    }
    await notif_coll.insert_one(notification)

    return {"status": 200, "msg": "Cash collected and notified manager", "data": amount}

