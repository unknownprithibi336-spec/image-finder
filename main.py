import os
import requests
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Any
from serpapi import GoogleSearch

app = FastAPI()

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY", "")

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

@app.post("/bulk-search")
async def bulk_image_search(data: ImageBatch):
    all_related_image_urls = []
    debug_errors = []
    clean_images = flatten_images(data.images)

    for b64_img in clean_images:
        if "," in b64_img:
            b64_img = b64_img.split(",")[1]
        res = requests.post(
            "https://api.imgbb.com/1/upload",
            data={"key": IMGBB_API_KEY, "image": b64_img, "expiration": 600}
        ).json()

        if "data" not in res:
            debug_errors.append({"imgbb_error": res})
            continue

        public_url = res["data"]["url"]
        search = GoogleSearch({
            "engine": "google_lens",
            "url": public_url,
            "api_key": SERPAPI_KEY
        })
        results = search.get_dict()
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
