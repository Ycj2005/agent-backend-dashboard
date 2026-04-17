import cloudinary
import cloudinary.uploader
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# Configure Cloudinary if credentials are provided
if settings.CLOUDINARY_CLOUD_NAME and settings.CLOUDINARY_API_KEY and settings.CLOUDINARY_API_SECRET:
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True
    )
    logger.info("Cloudinary configured.")
else:
    logger.warning("Cloudinary credentials are not fully set in the environment.")

async def upload_image(image_data: str, folder: str = "bargad_agents") -> str:
    """
    Uploads base64 image data or URL to Cloudinary.
    Replicates Cloudinary logic used in POST /api/agent and POST /api/agent-verification
    """
    try:
        # cloudinary uploader works fine synchronously, but in FastAPI we should run in separate thread
        # for simplicity, cloudinary uses synchronous requests by default. We'll wrap in asyncio later if needed.
        # But this works for base64 strings or URLs.
        upload_response = cloudinary.uploader.upload(
            image_data,
            folder=folder
        )
        return upload_response.get("secure_url", "")
    except Exception as e:
        logger.error(f"Cloudinary upload failed: {str(e)}")
        raise e
