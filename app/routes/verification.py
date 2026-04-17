from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from app.core.database import get_collection
from bson import ObjectId
from app.utils.cloudinary_utils import upload_image
import logging
from datetime import datetime
import os
import base64
import tempfile
import urllib.request
import uuid

import torch
import numpy as np
import cv2
from facenet_pytorch import MTCNN, InceptionResnetV1
from PIL import Image

# Initialize models
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
mtcnn = MTCNN(image_size=160, margin=20, device=DEVICE)
model = InceptionResnetV1(pretrained='vggface2').eval().to(DEVICE)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/verification", tags=["Agent Verification"])

class VerificationRequest(BaseModel):
    customerId: str
    capturedImage: str # base64 string
    
def download_image_to_temp_from_url(url: str, suffix=".jpg") -> str:
    path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}{suffix}")
    urllib.request.urlretrieve(url, path)
    return path

def save_base64_to_temp(b64_str: str, suffix=".jpg") -> str:
    # Remove prefix if present "data:image/jpeg;base64,"
    if "," in b64_str:
        b64_str = b64_str.split(",")[1]
    
    img_data = base64.b64decode(b64_str)
    path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}{suffix}")
    with open(path, "wb") as f:
        f.write(img_data)
    return path

def get_embedding(image_path):
    img = Image.open(image_path).convert('RGB')
    face = mtcnn(img)
    if face is None:
        return None
    
    face = face.unsqueeze(0).to(DEVICE)
    with torch.no_grad():
        emb = model(face).cpu().numpy().flatten()
    
    # L2 Normalization
    norm = np.linalg.norm(emb)
    if norm > 0:
        emb = emb / norm
    return emb

@router.post("/verify-agent", response_model=dict)
async def verify_agent(req: VerificationRequest):
    if not req.customerId or not ObjectId.is_valid(req.customerId):
        return {"status": 400, "msg": "Missing or invalid customerId"}
    if not req.capturedImage:
        return {"status": 400, "msg": "Missing capturedImage"}

    customer_coll = get_collection("customers")
    agent_coll = get_collection("agents")

    customer = await customer_coll.find_one({"_id": ObjectId(req.customerId)})
    if not customer:
        return {"status": 404, "msg": "Customer not found"}

    agent_id = customer.get("agentId")
    if not agent_id:
        return {"status": 404, "msg": "Customer has no assigned agentId"}

    agent = await agent_coll.find_one({"_id": agent_id})
    if not agent or not agent.get("image"):
        return {"status": 404, "msg": "Agent reference image not found"}

    final_score = 0
    is_verified = False
    similarity = 0
    
    cap_path = None
    ref_path = None

    try:
        # Prepare valid paths for matching
        cap_path = save_base64_to_temp(req.capturedImage)
        ref_image_url = agent["image"]
        ref_path = download_image_to_temp_from_url(ref_image_url)

        # Get embeddings
        cap_emb = get_embedding(cap_path)
        ref_emb = get_embedding(ref_path)

        if cap_emb is not None and ref_emb is not None:
            # Cosine similarity (both are already L2 normalized)
            similarity = np.dot(cap_emb, ref_emb)
            
            # User wants 70 threshold (0 to 100 percentage)
            # Threshold 0.7 mapping: score = similarity * 100
            final_score = max(0, min(100, int(similarity * 100)))
            
            # Threshold logic
            is_verified = final_score >= 70
            
            logger.info(f"[FACE MATCH] Similarity: {similarity:.4f} -> Score: {final_score}% (Threshold: 70%)")
            if is_verified:
                logger.info(f"✅ FACE MATCH VERIFIED")
            else:
                logger.info(f"❌ FACE MISMATCH")
        else:
            logger.warning("Could not detect face in one or both images")
            final_score = 0
            is_verified = False

    except Exception as e:
        logger.error(f"❌ Face processing error: {e}")
        final_score = 0
        is_verified = False
    finally:
        # Cleanup temporary files
        if cap_path and os.path.exists(cap_path): os.remove(cap_path)
        if ref_path and os.path.exists(ref_path): os.remove(ref_path)

    # Upload captured image to cloudinary
    image_url = req.capturedImage
    if req.capturedImage.startswith("data:image"):
        try:
             # cloudinary runs synchronously by default
             image_url = await upload_image(req.capturedImage, folder="agent_verifications")
        except Exception as e:
             logger.error(f"❌ Cloudinary upload failed: {e}")
             
    # Mock metadata
    metadata = {
        "collectedAt": datetime.utcnow().isoformat(),
        "collectedLocation": customer.get("location"),
        "deviceModel": "Android 15 (SM-S918B)",
        "deviceImei": f"820461265/999999 | VI Network",
        "networkOperator": "VI Network"
    }
    
    # Update Customer 
    update_data = {
         "verifiedAgentImage": image_url,
         "verificationScore": final_score,
         "verificationStatus": "verified" if is_verified else "failed"
    }
    update_data.update(metadata)
    
    await customer_coll.update_one(
         {"_id": ObjectId(req.customerId)},
         {"$set": update_data}
    )

    return {
      "status": 200,
      "msg": "Agent verification completed",
      "data": {
        "imageUrl": image_url,
        "score": final_score,
        "isVerified": is_verified,
        "similarity": float(round(similarity, 4))
      }
    }
