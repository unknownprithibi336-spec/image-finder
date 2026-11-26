import os
import base64
import requests
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Any
from serpapi import GoogleSearch

app = FastAPI()

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

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

def upload_temp_image(img_bytes: bytes) -> str:
    res = requests.post(
        "https://litterbox.catbox.moe/resources/internals/api.php",
        data={"reqtype": "fileupload", "time": "1h"},
        files={"fileToUpload": ("product.jpg", img_bytes, "image/jpeg")},
        timeout=20
    )
    url = res.text.strip()
    if url.startswith("http"):
        return url
    raise Exception(f"Upload failed: {url}")

@app.post("/bulk-search")
async def bulk_image_search(data: ImageBatch):
    all_related_image_urls = []
    debug_errors = []
    clean_images = flatten_images(data.images)

    for b64_img in clean_images:
        if "," in b64_img:
            b64_img = b64_img.split(",")[1]

        try:
            img_bytes = base64.b64decode(b64_img)
            public_url = upload_temp_image(img_bytes)
        except Exception as e:
            debug_errors.append({"upload_error": str(e)})
            continue

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
        if not visual_matches:
            debug_errors.append({"empty_matches_keys": list(results.keys()), "url": public_url})

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
