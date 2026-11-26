import os
import uuid
import base64
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Any
from serpapi import GoogleSearch

app = FastAPI()

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
TEMP_DIR = "/tmp/uploaded_imgs"
os.makedirs(TEMP_DIR, exist_ok=True)

class ImageBatch(BaseModel):
    images: List[Any]

def flatten_images(items):
    flat = []
    for item in items:
        if isinstance(item, list):
            flat.extend(flatten_images(item))
        elif isinstance(item, str) and item.strip():
            flat.append(item.strip())
    return flat

@app.get("/temp-img/{filename}")
async def serve_temp_image(filename: str):
    file_path = os.path.join(TEMP_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="image/jpeg")
    return {"error": "not found"}

@app.post("/bulk-search")
async def bulk_image_search(data: ImageBatch, request: Request):
    all_related_image_urls = []
    debug_errors = []
    clean_images = flatten_images(data.images)
    base_url = str(request.base_url).rstrip("/").replace("http://", "https://")

    for b64_img in clean_images:
        if "," in b64_img:
            b64_img = b64_img.split(",")[1]

        filename = f"{uuid.uuid4().hex}.jpg"
        file_path = os.path.join(TEMP_DIR, filename)

        try:
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64_img))
        except Exception as e:
            debug_errors.append({"decode_error": str(e)})
            continue

        public_url = f"{base_url}/temp-img/{filename}"

        search = GoogleSearch({
            "engine": "google_lens",
            "url": public_url,
            "api_key": SERPAPI_KEY
        })
        results = search.get_dict()

        if os.path.exists(file_path):
            os.remove(file_path)

        if "error" in results:
            debug_errors.append({"serpapi_error": results["error"]})
            continue

        visual_matches = results.get("visual_matches", [])
        count = 0
        for match in visual_matches:
            source = match.get("source", "").lower()
            img_link = match.get("thumbnail") or match.get("image")
            if img_link and (any(site in source for site in ["aliexpress", "amazon", "alibaba"]) or count < 5):
                all_related_image_urls.append(img_link)
                count += 1
                if count >= 5:
                    break

    return {
        "status": "success",
        "received_count": len(clean_images),
        "total_images": len(all_related_image_urls),
        "download_urls": all_related_image_urls,
        "errors": debug_errors
    }
