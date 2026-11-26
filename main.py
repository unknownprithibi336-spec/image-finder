import os
import base64
import requests
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
from serpapi import GoogleSearch

app = FastAPI()

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY", "")

class ImageBatch(BaseModel):
    images: List[str]

def upload_base64_to_imgbb(b64_string: str) -> str:
    url = "https://api.imgbb.com/1/upload"
    if "," in b64_string:
        b64_string = b64_string.split(",")[1]
    payload = {
        "key": IMGBB_API_KEY,
        "image": b64_string,
        "expiration": 600
    }
    res = requests.post(url, data=payload).json()
    return res["data"]["url"]

@app.post("/bulk-search")
async def bulk_image_search(data: ImageBatch):
    all_related_image_urls = []
    for b64_img in data.images:
        try:
            public_url = upload_base64_to_imgbb(b64_img)
        except Exception:
            continue
        params = {
            "engine": "google_lens",
            "url": public_url,
            "api_key": SERPAPI_KEY
        }
        search = GoogleSearch(params)
        results = search.get_dict()
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
        "total_images": len(all_related_image_urls),
        "download_urls": all_related_image_urls
    }
