from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
import httpx
import os
import hashlib
import json
import time
import logging
from app.core.config import settings

router = APIRouter(prefix="/route", tags=["Routing"])
logger = logging.getLogger(__name__)

# Request Models
class Point(BaseModel):
    lat: float
    lng: float
    name: Optional[str] = None
    isOffice: Optional[bool] = False

class RouteRequest(BaseModel):
    points: List[Point]

# Cache Setup (Trivial In-Memory)
cache = {}

def generate_payload_hash(points: List[Point]):
    simplified = "|".join([f"{p.lat:.6f},{p.lng:.6f}" for p in points])
    return hashlib.sha256(simplified.encode()).hexdigest()

def haversine_distance(p1, p2):
    import math
    R = 6371  # Earth radius in km
    dLat = math.radians(p2.lat - p1.lat)
    dLng = math.radians(p2.lng - p1.lng)
    a = math.sin(dLat / 2) ** 2 + \
        math.cos(math.radians(p1.lat)) * math.cos(math.radians(p2.lat)) * \
        math.sin(dLng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

async def get_actual_route_distance(ordered_points: List[Point], api_key: str):
    coords = ";".join([f"{p.lng},{p.lat}" for p in ordered_points])
    url = f"https://apis.mappls.com/advancedmaps/v1/{api_key}/route_adv/driving/{coords}?geometries=geojson&overview=full"
    
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url, timeout=10.0)
            if res.status_code != 200:
                return None
            data = res.json()
            if not data.get("routes") or not data["routes"][0].get("distance"):
                return None
            return data["routes"][0]["distance"] / 1000 # to km
        except Exception as e:
            logger.warning(f"[ROUTE] API Error: {e}")
            return None

def get_permutations(lst):
    import itertools
    return list(itertools.permutations(lst))

async def optimize_route(points: List[Point], api_key: str):
    if len(points) <= 3:
        return list(range(len(points)))

    # Greedy approach: Start from office, go to nearest neighbor, etc., end at office
    start_idx = 0
    end_idx = len(points) - 1
    unvisited = list(range(1, len(points) - 1))
    
    current_order = [start_idx]
    
    while unvisited:
        current_pt = points[current_order[-1]]
        # Find nearest unvisited based on haversine (cheap)
        nearest_idx = unvisited[0]
        min_dist = haversine_distance(current_pt, points[nearest_idx])
        
        for idx in unvisited[1:]:
            d = haversine_distance(current_pt, points[idx])
            if d < min_dist:
                min_dist = d
                nearest_idx = idx
        
        current_order.append(nearest_idx)
        unvisited.remove(nearest_idx)
    
    current_order.append(end_idx)
    return current_order

@router.post("")
@router.post("/")
async def get_route(req: RouteRequest):
    logger.info(f"[ROUTE] Received request for {len(req.points)} points")
    if len(req.points) < 2:
        throw_400("At least 2 points required")

    payload_hash = generate_payload_hash(req.points)
    
    # Simple TTL cache check
    if payload_hash in cache:
        cached_data, timestamp = cache[payload_hash]
        if time.time() - timestamp < 300: # 5 mins
            logger.info("[ROUTE] Returning cached result")
            return cached_data

    api_key = settings.MAPPLS_API_KEY
    if not api_key:
        logger.error("[ROUTE] MAPPLS_API_KEY is missing in settings")
        raise HTTPException(status_code=500, detail="Mappls API key missing")

    try:
        # 1. Optimize order (Greedy algorithm)
        optimized_order = await optimize_route(req.points, api_key)
        optimized_points = [req.points[i] for i in optimized_order]
        
        # 2. Get real route from Mappls
        coords = ";".join([f"{p.lng},{p.lat}" for p in optimized_points])
        final_url = f"https://apis.mappls.com/advancedmaps/v1/{api_key}/route_adv/driving/{coords}?geometries=geojson&overview=full&steps=true"
        
        logger.info(f"[ROUTE] Calling Mappls API: {final_url[:100]}...")
        
        async with httpx.AsyncClient() as client:
            res = await client.get(final_url, timeout=15.0)
            if res.status_code != 200:
                logger.error(f"[ROUTE] Mappls API Error: {res.status_code} - {res.text}")
                raise HTTPException(status_code=res.status_code, detail=f"Mappls API error: {res.text}")
            
            data = res.json()
            if not data.get("routes"):
                 logger.warning("[ROUTE] No routes found in Mappls response")
                 raise HTTPException(status_code=404, detail="No route found")
                 
            route = data["routes"][0]
            
            # Aggregate path coordinates
            path = []
            if route.get("geometry", {}).get("coordinates"):
                # Mappls returns [lng, lat], we need [lat, lng] for frontend
                path = [[c[1], c[0]] for c in route["geometry"]["coordinates"]]
            elif route.get("legs"):
                for leg in route["legs"]:
                    if leg.get("steps"):
                        for step in leg["steps"]:
                            if step.get("geometry", {}).get("coordinates"):
                                for c in step["geometry"]["coordinates"]:
                                    path.append([c[1], c[0]]) 
            
            if not path:
                logger.warning("[ROUTE] Path construction failed")
                raise HTTPException(status_code=404, detail="Could not build path from Mappls response")

            result = {
                "path": path,
                "distance": route.get("distance", 0) / 1000,
                "time": route.get("duration", 0),
                "legs": [
                    {
                        "distance": leg.get("distance", 0) / 1000,
                        "duration": leg.get("duration", 0)
                    } for leg in route.get("legs", [])
                ],
                "optimizedOrder": optimized_order,
                "status": "SUCCESS"
            }
            
            cache[payload_hash] = (result, time.time())
            logger.info(f"[ROUTE] Success: {result['distance']:.2f} km")
            return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ROUTE] Unhandled error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

def throw_400(msg):
    raise HTTPException(status_code=400, detail=msg)
