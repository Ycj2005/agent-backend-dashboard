from fastapi import APIRouter, HTTPException
from typing import List
from app.core.database import get_collection
from app.models.notification import NotificationModel
from bson import ObjectId

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=dict)
async def get_notifications():
    try:
        notif_coll = get_collection("notifications")
        notifications = (
            await notif_coll.find().sort("timestamp", -1).limit(50).to_list(None)
        )
        for n in notifications:
            n["_id"] = str(n["_id"])
            n["agentId"] = str(n["agentId"])
            if n.get("customerId"):
                n["customerId"] = str(n["customerId"])
        return {"status": 200, "data": notifications}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/read/{notif_id}")
async def mark_as_read(notif_id: str):
    if not ObjectId.is_valid(notif_id):
        raise HTTPException(status_code=400, detail="Invalid ID")
    notif_coll = get_collection("notifications")
    await notif_coll.update_one({"_id": ObjectId(notif_id)}, {"$set": {"read": True}})
    return {"status": 200, "msg": "Marked as read"}


@router.delete("/clear")
async def clear_notifications():
    notif_coll = get_collection("notifications")
    await notif_coll.delete_many({})
    return {"status": 200, "msg": "Notifications cleared"}
