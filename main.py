import os
import base64
import requests
from fastapi import FastAPI, UploadFile, File
from typing import List
from serpapi import GoogleSearch

app = FastAPI()

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY", "")

def upload_to_imgbb(image_bytes: bytes) -> str:
    url = "https://api.imgbb.com/1/upload"
    encoded_image = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "key": IMGBB_API_KEY,
        "image": encoded_image,
        "expiration": 600
    }
    res = requests.post(url, data=payload).json()
    return res["data"]["url"]

@app.post("/bulk-search")
async def bulk_image_search(files: List[UploadFile] = File(...)):
    all_related_image_urls = []
    for file in files:
        image_bytes = await file.read()
        try:
            public_url = upload_to_imgbb(image_bytes)
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
