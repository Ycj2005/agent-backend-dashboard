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
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor

import torch
import numpy as np
import cv2
from facenet_pytorch import MTCNN, InceptionResnetV1
from PIL import Image

# Lazy model initialization - loaded on first request to avoid flooding
# Railway logs with download progress bars ("99.9%...") at container start.
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
_mtcnn = None
_model = None

# Cache for reference embeddings: { agent_id_str: (embedding_array, image_url) }
_ref_embedding_cache = {}

# Thread pool for background Cloudinary uploads
_upload_executor = ThreadPoolExecutor(max_workers=2)

logger = logging.getLogger(__name__)


def _get_models():
    """Lazy-load face recognition models on first use."""
    global _mtcnn, _model
    if _mtcnn is None or _model is None:
        logger.info("Loading face recognition models (first request)...")
        _mtcnn = MTCNN(image_size=160, margin=20, device=DEVICE)
        _model = InceptionResnetV1(pretrained='vggface2').eval().to(DEVICE)
        logger.info("Face recognition models loaded.")
    return _mtcnn, _model

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

def _resize_for_detection(img, max_size=640):
    """Resize image to max_size on longest side for faster MTCNN detection."""
    w, h = img.size
    if max(w, h) <= max_size:
        return img
    scale = max_size / max(w, h)
    new_w, new_h = int(w * scale), int(h * scale)
    return img.resize((new_w, new_h), Image.BILINEAR)

def get_embedding(image_path):
    mtcnn, model = _get_models()
    img = Image.open(image_path).convert('RGB')
    img = _resize_for_detection(img, max_size=640)
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

def _get_ref_embedding(agent_id_str: str, image_url: str):
    """Get cached reference embedding or compute and cache it."""
    global _ref_embedding_cache
    cached = _ref_embedding_cache.get(agent_id_str)
    if cached and cached[1] == image_url:
        logger.info(f"[CACHE HIT] Using cached embedding for agent {agent_id_str}")
        return cached[0]

    logger.info(f"[CACHE MISS] Computing embedding for agent {agent_id_str}")
    ref_path = None
    try:
        ref_path = download_image_to_temp_from_url(image_url)
        emb = get_embedding(ref_path)
        if emb is not None:
            _ref_embedding_cache[agent_id_str] = (emb, image_url)
        return emb
    finally:
        if ref_path and os.path.exists(ref_path):
            os.remove(ref_path)

def _background_upload(b64_image: str, customer_id: str, folder: str):
    """Synchronous upload for use in thread pool."""
    try:
        import cloudinary.uploader
        result = cloudinary.uploader.upload(b64_image, folder=folder)
        image_url = result.get("secure_url", b64_image)
        # Fire-and-forget DB update with the cloudinary URL
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        coll = loop.run_until_complete(_get_coll_async())
        loop.run_until_complete(
            coll.update_one(
                {"_id": ObjectId(customer_id)},
                {"$set": {"verifiedAgentImage": image_url}}
            )
        )
        loop.close()
        logger.info(f"✅ Background upload complete for {customer_id}")
    except Exception as e:
        logger.error(f"❌ Background upload failed: {e}")

async def _get_coll_async():
    return get_collection("customers")

@router.post("/verify-agent")
async def verify_agent(req: VerificationRequest):
    try:
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
        agent_id_str = str(agent["_id"])
        ref_image_url = agent["image"]

        t_start = time.time()

        try:
            # Prepare captured image
            cap_path = save_base64_to_temp(req.capturedImage)

            # Get captured face embedding
            t1 = time.time()
            cap_emb = get_embedding(cap_path)
            logger.info(f"[TIMING] Captured embedding: {time.time()-t1:.2f}s")

            # Get reference embedding (cached)
            t2 = time.time()
            ref_emb = _get_ref_embedding(agent_id_str, ref_image_url)
            logger.info(f"[TIMING] Reference embedding: {time.time()-t2:.2f}s")

            if cap_emb is not None and ref_emb is not None:
                # Cosine similarity (both are already L2 normalized)
                similarity = float(np.dot(cap_emb, ref_emb))
                
                # Score = similarity * 100 (0-100 range)
                final_score = max(0, min(100, int(similarity * 100)))
                
                # Threshold: >= 65 is verified (user requirement)
                is_verified = final_score >= 65
                
                logger.info(f"[FACE MATCH] Similarity: {similarity:.4f} -> Score: {final_score}% (Threshold: 65%)")
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
            # Cleanup captured temp file only (ref is handled by cache)
            if cap_path and os.path.exists(cap_path): os.remove(cap_path)
        
        logger.info(f"[TIMING] Total face processing: {time.time()-t_start:.2f}s")

        # Mock metadata
        metadata = {
            "collectedAt": datetime.utcnow().isoformat(),
            "collectedLocation": customer.get("location"),
            "deviceModel": "Android 15 (SM-S918B)",
            "deviceImei": f"820461265/999999 | VI Network",
            "networkOperator": "VI Network"
        }
        
        # Update Customer immediately with base64 placeholder (Cloudinary URL will be updated in background)
        update_data = {
             "verifiedAgentImage": "uploading...",
             "verificationScore": final_score,
             "verificationStatus": "verified" if is_verified else "failed"
        }
        update_data.update(metadata)
        
        await customer_coll.update_one(
             {"_id": ObjectId(req.customerId)},
             {"$set": update_data}
        )

        # Fire Cloudinary upload in background thread (non-blocking)
        if req.capturedImage.startswith("data:image"):
            _upload_executor.submit(
                _background_upload,
                req.capturedImage,
                req.customerId,
                "agent_verifications"
            )
            logger.info("📤 Cloudinary upload dispatched to background")

        total_time = time.time() - t_start
        logger.info(f"[TIMING] Total verification response time: {total_time:.2f}s")

        return {
          "status": 200,
          "msg": "Agent verification completed",
          "data": {
            "imageUrl": "uploading",
            "score": final_score,
            "isVerified": is_verified,
            "similarity": round(float(similarity), 4),
            "processingTime": round(total_time, 2)
          }
        }
    except Exception as e:
        logger.error(f"❌ Unhandled verification error: {e}", exc_info=True)
        return {"status": 500, "msg": f"Server error: {str(e)}", "data": {"score": 0, "isVerified": False, "similarity": 0}}

