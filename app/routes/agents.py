from fastapi import APIRouter, HTTPException, status
from typing import List
from app.core.database import get_collection
from app.models.agent import AgentCreate, AgentUpdate, AgentModel
from app.models.pyobjectid import PyObjectId
from bson import ObjectId
from app.utils.geocoding import reverse_geocode
from app.utils.cloudinary_utils import upload_image

from app.utils.geo import haversine_distance
from datetime import datetime

# OFFICE = {"lat": 19.1133869510231, "lng": 72.91810580467191}
OFFICE = {"lat": 19.221205362778235, "lng":  73.09295477236344}

router = APIRouter(prefix="/agents", tags=["Agents"])


def parse_location_string(loc_str: str):
    if not loc_str:
        return 0, 0
    parts = [p.strip() for p in loc_str.split(",")]
    if len(parts) == 2:
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            pass
    return 0, 0


@router.post("/start-journey/{agentId}")
async def start_journey(agentId: str, payload: dict):
    if not ObjectId.is_valid(agentId):
        raise HTTPException(status_code=400, detail="Invalid Agent ID")

    optimizedRoute = payload.get("optimizedRoute")
    agent_coll = get_collection("agents")

    update_data = {
        "journeyTracking.isActive": True,
        "journeyTracking.startedAt": datetime.utcnow(),
        "journeyTracking.visitedPoints": [],
        "journeyTracking.deviationPoints": [],
    }

    if optimizedRoute is not None:
        update_data["journeyTracking.optimizedRoute"] = optimizedRoute

    await agent_coll.update_one({"_id": ObjectId(agentId)}, {"$set": update_data})

    # Notify Manager
    agent = await agent_coll.find_one({"_id": ObjectId(agentId)})
    notif_coll = get_collection("notifications")
    await notif_coll.insert_one({
        "agentId": ObjectId(agentId),
        "agentName": agent.get("name"),
        "type": "journey_started",
        "message": f"Agent {agent.get('name')} has started their journey.",
        "timestamp": datetime.utcnow(),
        "read": False
    })

    return {"status": 200, "msg": "Journey started"}



@router.post("/track-location/{agentId}")
async def track_location(agentId: str, payload: dict):
    if not ObjectId.is_valid(agentId):
        raise HTTPException(status_code=400, detail="Invalid Agent ID")

    lat = payload.get("lat")
    lng = payload.get("lng")

    if lat is None or lng is None:
        raise HTTPException(status_code=400, detail="Lat and Lng required")

    agent_coll = get_collection("agents")
    agent = await agent_coll.find_one({"_id": ObjectId(agentId)})

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    jt = agent.get("journeyTracking", {})
    last = jt.get("lastLocation")

    # movement detection (20 meters)
    if last:
        movement = haversine_distance(last["lat"], last["lng"], lat, lng)
        if movement < 20:
            return {"status": 200, "msg": "No movement detected"}

    # office reached
    dist_to_office = haversine_distance(lat, lng, OFFICE["lat"], OFFICE["lng"])
    if dist_to_office < 200:
        await agent_coll.update_one(
            {"_id": ObjectId(agentId)}, {"$set": {"journeyTracking.isActive": False}}
        )
        return {"status": 200, "msg": "Office reached"}

    optimized_route = jt.get("optimizedRoute", [])
    is_on_route = False

    for pt in optimized_route:
        if haversine_distance(lat, lng, pt["lat"], pt["lng"]) < 300:
            is_on_route = True
            break

    point = {"lat": lat, "lng": lng, "timestamp": datetime.utcnow()}
    
    # Check for proximity to assigned customers for arrival notification
    customer_coll = get_collection("customers")
    notif_coll = get_collection("notifications")
    
    agent_customers = agent.get("customers", [])
    for cust_id in agent_customers:
        customer = await customer_coll.find_one({"_id": cust_id})
        if customer and customer.get("location"):
            cloc = customer["location"]
            dist = haversine_distance(lat, lng, cloc["lat"], cloc["lng"])
            
            # If within 50m and not already notified recently? 
            # For simplicity, we just notify if they are "at" the house.
            # In a real app, we'd track if they already arrived today.
            if dist < 50:
                 # Check if recently notified
                 existing = await notif_coll.find_one({
                     "agentId": ObjectId(agentId),
                     "customerId": cust_id,
                     "type": "arrival",
                     "timestamp": {"$gt": datetime.utcnow().replace(hour=0, minute=0, second=0)}
                 })
                 if not existing:
                     await notif_coll.insert_one({
                         "agentId": ObjectId(agentId),
                         "agentName": agent.get("name"),
                         "customerId": cust_id,
                         "customerName": customer.get("name"),
                         "type": "arrival",
                         "message": f"{agent.get('name')} arrived at {customer.get('name')}'s house",
                         "timestamp": datetime.utcnow(),
                         "read": False
                     })

    update = {
        "$set": {"journeyTracking.lastLocation": {"lat": lat, "lng": lng}},
        "$push": {"journeyTracking.livedRoute": point},
    }

    if is_on_route:
        update["$push"]["journeyTracking.visitedPoints"] = point
    else:
        update["$push"]["journeyTracking.deviationPoints"] = point
        # Send deviation notification
        await notif_coll.insert_one({
            "agentId": ObjectId(agentId),
            "agentName": agent.get("name"),
            "type": "deviation",
            "message": f"ALERT: Agent {agent.get('name')} has deviated from the optimized route!",
            "timestamp": datetime.utcnow(),
            "read": False
        })

    await agent_coll.update_one({"_id": ObjectId(agentId)}, update)

    return {"status": 200, "onRoute": is_on_route, "movementSaved": True}



# @router.post("/track-location/{agentId}")
# async def track_location(agentId: str, payload: dict):
#     if not ObjectId.is_valid(agentId):
#         raise HTTPException(status_code=400, detail="Invalid Agent ID")

#     lat = payload.get("lat")
#     lng = payload.get("lng")
#     if lat is None or lng is None:
#         raise HTTPException(status_code=400, detail="Lat and Lng required")

#     agent_coll = get_collection("agents")
#     agent = await agent_coll.find_one({"_id": ObjectId(agentId)})
#     if not agent:
#         raise HTTPException(status_code=404, detail="Agent not found")

#     # Check if near office
#     dist_to_office = haversine_distance(lat, lng, OFFICE["lat"], OFFICE["lng"])
#     if dist_to_office < 200: # 200 meters
#         await agent_coll.update_one(
#             {"_id": ObjectId(agentId)},
#             {"$set": {"journeyTracking.isActive": False}}
#         )
#         return {"status": 200, "msg": "Office reached, journey stopped automatically"}

#     # Route deviation check
#     jt = agent.get("journeyTracking", {})
#     optimized_route = jt.get("optimizedRoute", [])
#     is_on_route = False

#     # Check if near any point in optimized route polyline
#     # This is a simple point-to-point check for now.
#     # For better accuracy we would check distance to line segments.
#     for pt in optimized_route:
#         if haversine_distance(lat, lng, pt["lat"], pt["lng"]) < 300: # 300 meters
#             is_on_route = True
#             break

#     point_data = {
#         "lat": lat,
#         "lng": lng,
#         "timestamp": datetime.utcnow()
#     }

#     update_op = {
#         "$set": {
#             "location": f"{lat},{lng}",
#             "journeyTracking.lastLocation": {"lat": lat, "lng": lng}
#         },
#         "$push": {}
#     }

#     if is_on_route:
#         update_op["$push"]["journeyTracking.visitedPoints"] = point_data
#     else:
#         update_op["$push"]["journeyTracking.deviationPoints"] = point_data

#     await agent_coll.update_one({"_id": ObjectId(agentId)}, update_op)
#     return {"status": 200, "msg": "Location tracked", "onRoute": is_on_route}


@router.post("/stop-journey/{agentId}")
async def stop_journey(agentId: str):
    if not ObjectId.is_valid(agentId):
        raise HTTPException(status_code=400, detail="Invalid Agent ID")

    agent_coll = get_collection("agents")
    await agent_coll.update_one(
        {"_id": ObjectId(agentId)}, {"$set": {"journeyTracking.isActive": False}}
    )
    return {"status": 200, "msg": "Journey stopped"}


@router.post("/update-route/{agentId}")
async def update_route(agentId: str, payload: dict):
    if not ObjectId.is_valid(agentId):
        raise HTTPException(status_code=400, detail="Invalid Agent ID")

    optimizedRoute = payload.get("optimizedRoute", [])
    agent_coll = get_collection("agents")

    await agent_coll.update_one(
        {"_id": ObjectId(agentId)},
        {"$set": {"journeyTracking.optimizedRoute": optimizedRoute}},
    )
    return {"status": 200, "msg": "Route updated successfully"}


@router.post("/update-lived-route/{agent_id}")
async def update_lived_route(agent_id: str, payload: dict):
    lived_route = payload.get("livedRoute", [])
    agent_coll = get_collection("agents")
    result = await agent_coll.update_one(
        {"_id": ObjectId(agent_id)},
        {"$set": {"journeyTracking.livedRoute": lived_route}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "success", "message": "Lived route updated"}


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_agent(agent: AgentCreate):
    try:
        image_url = ""
        if agent.image:
            image_url = await upload_image(agent.image)

        lat, lng = parse_location_string(agent.location)
        auto_address = await reverse_geocode(lat, lng)

        agent_dict = {
            "name": agent.name,
            "image": image_url,
            "location": agent.location,
            "address": auto_address,
            "customers": [],
        }

        agent_coll = get_collection("agents")
        result = await agent_coll.insert_one(agent_dict)
        agent_dict["_id"] = str(result.inserted_id)

        return {"status": 200, "msg": "Agent created successfully!", "data": agent_dict}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=dict)
async def get_agents():
    try:
        agent_coll = get_collection("agents")
        agents = await agent_coll.find().to_list(None)
        for a in agents:
            a["_id"] = str(a["_id"])
            a["customers"] = [str(c) for c in a.get("customers", [])]
        return {"status": 200, "msg": "Agents fetched successfully!", "data": agents}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/with-customers", response_model=dict)
async def get_agents_with_customers():
    try:
        agent_coll = get_collection("agents")

        pipeline = [
            {
                "$lookup": {
                    "from": "customers",
                    "localField": "customers",
                    "foreignField": "_id",
                    "as": "customer_docs",
                }
            }
        ]

        raw_agents = await agent_coll.aggregate(pipeline).to_list(None)

        agents_out = []
        for agent in raw_agents:
            # Parse location
            loc = None
            raw_loc = agent.get("location")
            if isinstance(raw_loc, dict) and "lat" in raw_loc and "lng" in raw_loc:
                loc = {"lat": float(raw_loc["lat"]), "lng": float(raw_loc["lng"])}
            elif isinstance(raw_loc, str):
                parts = [s.strip() for s in raw_loc.split(",")]
                if len(parts) == 2:
                    try:
                        loc = {"lat": float(parts[0]), "lng": float(parts[1])}
                    except ValueError:
                        pass

            if not loc:
                continue  # Skip agents without valid location

            customers_out = []
            for c in agent.get("customer_docs", []):
                cloc = None
                raw_cloc = c.get("location")
                if (
                    isinstance(raw_cloc, dict)
                    and "lat" in raw_cloc
                    and "lng" in raw_cloc
                ):
                    cloc = {
                        "lat": float(raw_cloc["lat"]),
                        "lng": float(raw_cloc["lng"]),
                    }
                elif isinstance(raw_cloc, str):
                    parts = [s.strip() for s in raw_cloc.split(",")]
                    if len(parts) == 2:
                        try:
                            cloc = {"lat": float(parts[0]), "lng": float(parts[1])}
                        except ValueError:
                            pass

                if not cloc:
                    continue

                customers_out.append(
                    {
                        "_id": str(c["_id"]),
                        "name": c.get("name", "Unknown Customer"),
                        "loan": c.get("loan", ""),
                        "location": cloc,
                        "address": c.get("address", ""),
                        "agentId": (
                            str(c.get("agentId"))
                            if c.get("agentId")
                            else str(agent["_id"])
                        ),
                        "verifiedAgentImage": c.get("verifiedAgentImage", ""),
                        "verificationScore": c.get("verificationScore", 0),
                        "verificationStatus": c.get("verificationStatus", "pending"),
                        "cashCollected": c.get("cashCollected", ""),
                        "deviceModel": c.get("deviceModel", ""),
                        "deviceImei": c.get("deviceImei", ""),
                        "networkOperator": c.get("networkOperator", ""),
                        "collectedAt": c.get("collectedAt"),
                    }
                )

            agents_out.append(
                {
                    "_id": str(agent["_id"]),
                    "name": agent.get("name", "Unknown Agent"),
                    "image": agent.get("image", ""),
                    "location": loc,
                    "address": agent.get("address", ""),
                    "customers": customers_out,
                }
            )

        return {
            "status": 200,
            "msg": "Agents with customers fetched successfully!",
            "data": agents_out,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{id}", response_model=dict)
async def get_agent(id: str):
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid Agent ID format")
    try:
        agent_coll = get_collection("agents")
        pipeline = [
            {"$match": {"_id": ObjectId(id)}},
            {
                "$lookup": {
                    "from": "customers",
                    "localField": "customers",
                    "foreignField": "_id",
                    "as": "customers_populated",
                }
            },
        ]

        result = await agent_coll.aggregate(pipeline).to_list(1)
        if not result:
            return {"status": 404, "msg": "Agent not found."}

        agent = result[0]
        agent["_id"] = str(agent["_id"])

        # Convert _ids to strings in customers array
        for c in agent["customers_populated"]:
            c["_id"] = str(c["_id"])
            if "agentId" in c and c["agentId"]:
                c["agentId"] = str(c["agentId"])

        agent["customers"] = agent["customers_populated"]
        del agent["customers_populated"]

        return {"status": 200, "msg": "Agent fetched!", "data": agent}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{id}", response_model=dict)
async def update_agent(id: str, payload: AgentUpdate):
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid Agent ID format")

    try:
        agent_coll = get_collection("agents")

        update_op = {}
        set_fields = {}

        if payload.name is not None:
            set_fields["name"] = payload.name
        if payload.image is not None:
            set_fields["image"] = payload.image
        if payload.location is not None:
            set_fields["location"] = payload.location

        if set_fields:
            update_op["$set"] = set_fields

        if payload.customerIds:
            # We assume payload.customerIds is a list of ObjectIds (strings that can be parsed)
            oids = [ObjectId(c) for c in payload.customerIds if ObjectId.is_valid(c)]
            if oids:
                update_op["$addToSet"] = {"customers": {"$each": oids}}

        if not update_op:
            return {"status": 400, "msg": "No fields to update."}

        result = await agent_coll.find_one_and_update(
            {"_id": ObjectId(id)}, update_op, return_document=True
        )

        if not result:
            return {"status": 404, "msg": "Agent not found."}

        result["_id"] = str(result["_id"])
        result["customers"] = [str(c) for c in result.get("customers", [])]

        # We simulate populate by fetching the agent through GET method or aggregation if needed,
        # but to keep it simple, returning the updated doc might be enough, or do a quick lookup
        pipeline = [
            {"$match": {"_id": ObjectId(id)}},
            {
                "$lookup": {
                    "from": "customers",
                    "localField": "customers",
                    "foreignField": "_id",
                    "as": "customers_populated",
                }
            },
        ]

        populated = await agent_coll.aggregate(pipeline).to_list(1)
        if populated:
            agent = populated[0]
            agent["_id"] = str(agent["_id"])
            for c in agent["customers_populated"]:
                c["_id"] = str(c["_id"])
                if "agentId" in c and c["agentId"]:
                    c["agentId"] = str(c["agentId"])
            agent["customers"] = agent["customers_populated"]
            del agent["customers_populated"]
            return {"status": 200, "msg": "Agent updated successfully!", "data": agent}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/start-tracking/{id}")
async def start_tracking(id: str):
    agent_coll = get_collection("agents")

    await agent_coll.update_one(
        {"_id": ObjectId(id)},
        {
            "$set": {
                "isTracking": True,
                "startedAt": datetime.utcnow(),
                "routeDeviation": [],
            }
        },
    )

    return {"status": 200, "msg": "Tracking started"}


@router.post("/update-location/{id}")
async def update_location(id: str, payload: dict):

    lat = payload.get("lat")
    lng = payload.get("lng")

    agent_coll = get_collection("agents")

    await agent_coll.update_one(
        {"_id": ObjectId(id)},
        {
            "$set": {
                "lastLocation": {"lat": lat, "lng": lng, "timestamp": datetime.utcnow()}
            },
            "$push": {
                "routeDeviation": {
                    "lat": lat,
                    "lng": lng,
                    "timestamp": datetime.utcnow(),
                }
            },
        },
    )

    return {"status": 200, "msg": "Location Updated"}


@router.post("/stop-tracking/{id}")
async def stop_tracking(id: str):

    agent_coll = get_collection("agents")

    await agent_coll.update_one({"_id": ObjectId(id)}, {"$set": {"isTracking": False}})

    return {"status": 200, "msg": "Tracking stopped"}
