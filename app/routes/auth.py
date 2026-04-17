from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from app.core.database import get_collection
from bson import ObjectId
import re
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

class LoginRequest(BaseModel):
    identifier: str

@router.post("/login", response_model=dict)
async def login(req: LoginRequest):
    identifier = req.identifier.strip()
    if not identifier:
        return {"status": 400, "msg": "Identifier is required"}

    logger.info(f"[Login] Attempting login with identifier: {identifier}")

    agent = None
    matched_customer_id = None
    
    agent_coll = get_collection("agents")
    customer_coll = get_collection("customers")

    # 1. Try to find by Agent Name (Case-insensitive)
    agent = await agent_coll.find_one({"name": {"$regex": f"^{identifier}$", "$options": "i"}})

    # 2. Try to find by Agent ID directly if it's a valid ObjectId
    if not agent and ObjectId.is_valid(identifier):
        logger.info(f"[Login] Attempting direct ID search: {identifier}")
        agent = await agent_coll.find_one({"_id": ObjectId(identifier)})

    # 3. Fallback: Search by Customer Loan #
    if not agent:
        logger.info(f"[Login] Agent name/ID match failed. Searching customer loan: {identifier}")
        
        # Try searching customer by loan with a fuzzy regex (ignoring common prefixes like LN-)
        clean_loan = re.sub(r'^LN-?', '', identifier, flags=re.IGNORECASE)
        customer = await customer_coll.find_one({
            "$or": [
                {"loan": identifier},
                {"loan": clean_loan},
                {"loan": {"$regex": f"{clean_loan}$", "$options": "i"}}
            ]
        })

        if customer:
            logger.info(f"[Login] Found customer {customer.get('name')}. Searching for assigned agent...")
            matched_customer_id = str(customer["_id"])
            
            # Search for agent who HAS this customer in their 'customers' array
            agent = await agent_coll.find_one({"customers": customer["_id"]})

            # Secondary fallback if array is not used: check agentId on customer
            if not agent and customer.get("agentId"):
                agent = await agent_coll.find_one({"_id": customer["agentId"]})
            
            if agent:
                logger.info(f"[Login] Found agent {agent.get('name')} assigned to customer.")

    if not agent:
        return {"status": 404, "msg": "Agent not found"}

    # Format output
    agent["_id"] = str(agent["_id"])
    agent["customers"] = [str(c) for c in agent.get("customers", [])]

    return {
        "status": 200,
        "msg": "Authenticated successfully",
        "data": agent,
        "matchedCustomerId": matched_customer_id
    }
