from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.core.database import connect_to_mongo, close_mongo_connection
from app.routes import agents, customers, auth, verification, route, notifications

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Suppress noisy third-party library logs to avoid Railway's 500 logs/sec rate limit
for _noisy_lib in ["torch", "torchvision", "facenet_pytorch", "PIL", "httpx", "urllib3", "asyncio"]:
    logging.getLogger(_noisy_lib).setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup Events
    await connect_to_mongo()
    yield
    # Shutdown Events
    await close_mongo_connection()


app = FastAPI(
    title="Routing Machine Backend API",
    description="Consolidated backend for OpenStreet Manager and OpenStreet Agent apps.",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow CORS for NextJS frontends
origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "https://agent-dashboard-six-indol.vercel.app",
    "https://agent-side-application.vercel.app",
    "https://agent-backend-dashboard-production.up.railway.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
# Note: NextJS old routes were like /api/agent -> FastAPI equivalent /api/agents (handled by router prefix)
app.include_router(agents.router, prefix="/api")
app.include_router(customers.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(verification.router, prefix="/api")
app.include_router(route.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")


# Legacy/Alias for singular 'customer' search
@app.get("/api/customer/search", include_in_schema=False)
async def customer_search_alias(loan: str):
    from app.routes.customers import search_customer

    return await search_customer(loan)


@app.get("/api/customer/{id}", include_in_schema=False)
async def customer_get_alias(id: str):
    from app.routes.customers import get_customer

    return await get_customer(id)


@app.post("/api/agent-verification", include_in_schema=False)
async def agent_verification_alias(req: dict):
    from app.routes.verification import verify_agent, VerificationRequest

    # Map raw dict to VerificationRequest if possible
    try:
        vr = VerificationRequest(**req)
        return await verify_agent(vr)
    except Exception as e:
        return {"status": 400, "msg": f"Invalid verification request: {str(e)}"}


@app.get("/")
async def root():
    return {"message": "Welcome to Routing Machine API Backend"}


# trigger reload
