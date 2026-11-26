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
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
    }
    errors = []

    # অপশন ১: tmpfiles.org
    try:
        res = requests.post(
            "https://tmpfiles.org/api/v1/upload",
            files={"file": ("product.jpg", img_bytes, "image/jpeg")},
            headers=headers,
            timeout=15
        )
        data = res.json()
        if data.get("status") == "success":
            raw_url = data["data"]["url"]
            return raw_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
    except Exception as e:
        errors.append(f"tmpfiles: {e}")

    # অপশন ২: uguu.se
    try:
        res = requests.post(
            "https://uguu.se/upload",
            files={"files[]": ("product.jpg", img_bytes, "image/jpeg")},
            headers=headers,
            timeout=15
        )
        data = res.json()
        if data.get("success") and data.get("files"):
            return data["files"][0]["url"]
    except Exception as e:
        errors.append(f"uguu: {e}")

    # অপশন ৩: litterbox (User-Agent সহ)
    try:
        res = requests.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "1h"},
            files={"fileToUpload": ("product.jpg", img_bytes, "image/jpeg")},
            headers=headers,
            timeout=15
        )
        if res.text.strip().startswith("http"):
            return res.text.strip()
    except Exception as e:
        errors.append(f"litterbox: {e}")

    raise Exception(" | ".join(errors))

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
