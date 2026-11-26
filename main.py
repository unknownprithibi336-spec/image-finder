import os
import base64
import requests
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Any
from serpapi import GoogleSearch

app = FastAPI()

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
PREFERRED_SITES = ["aliexpress", "amazon", "alibaba"]
MAX_PER_IMAGE = 5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
}


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


def decode_image(b64_img: str) -> bytes:
    # "data:image/jpeg;base64,..." থাকলে সামনের অংশ বাদ
    if "," in b64_img:
        b64_img = b64_img.split(",", 1)[1]
    # লাইন ব্রেক/স্পেস বাদ, padding ঠিক করা
    b64_img = "".join(b64_img.split())
    b64_img += "=" * (-len(b64_img) % 4)
    return base64.b64decode(b64_img)


def upload_temp_image(img_bytes: bytes) -> str:
    errors = []

    # অপশন ১: tmpfiles.org
    try:
        res = requests.post(
            "https://tmpfiles.org/api/v1/upload",
            files={"file": ("product.jpg", img_bytes, "image/jpeg")},
            headers=HEADERS,
            timeout=20,
        )
        data = res.json()
        if data.get("status") == "success":
            raw_url = data["data"]["url"]
            url = raw_url.replace("tmpfiles.org/", "tmpfiles.org/dl/", 1)
            return url.replace("http://", "https://", 1)
        errors.append(f"tmpfiles: {res.status_code} {res.text[:100]}")
    except Exception as e:
        errors.append(f"tmpfiles: {e}")

    # অপশন ২: uguu.se
    try:
        res = requests.post(
            "https://uguu.se/upload",
            files={"files[]": ("product.jpg", img_bytes, "image/jpeg")},
            headers=HEADERS,
            timeout=20,
        )
        data = res.json()
        if data.get("success") and data.get("files"):
            return data["files"][0]["url"]
        errors.append(f"uguu: {res.status_code} {res.text[:100]}")
    except Exception as e:
        errors.append(f"uguu: {e}")

    # অপশন ৩: litterbox
    try:
        res = requests.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "1h"},
            files={"fileToUpload": ("product.jpg", img_bytes, "image/jpeg")},
            headers=HEADERS,
            timeout=20,
        )
        if res.text.strip().startswith("http"):
            return res.text.strip()
        errors.append(f"litterbox: {res.status_code} {res.text[:100]}")
    except Exception as e:
        errors.append(f"litterbox: {e}")

    raise Exception(" | ".join(errors) or "সব upload সার্ভিস ব্যর্থ")


def pick_matches(visual_matches):
    # আগে AliExpress/Amazon/Alibaba, তারপর বাকিগুলো
    preferred, others = [], []
    for match in visual_matches:
        source = (match.get("source") or "").lower()
        link = (match.get("link") or "").lower()
        if any(site in source or site in link for site in PREFERRED_SITES):
            preferred.append(match)
        else:
            others.append(match)

    urls = []
    for match in preferred + others:
        # বড় ছবি আগে, না পেলে thumbnail
        img_link = match.get("image") or match.get("thumbnail")
        if img_link and img_link not in urls:
            urls.append(img_link)
        if len(urls) >= MAX_PER_IMAGE:
            break
    return urls


@app.get("/")
def health():
    return {"status": "ok", "serpapi_key_set": bool(SERPAPI_KEY)}


@app.post("/bulk-search")
def bulk_image_search(data: ImageBatch):
    all_related_image_urls = []
    debug_errors = []
    clean_images = flatten_images(data.images)

    if not SERPAPI_KEY:
        return {
            "status": "error",
            "received_count": len(clean_images),
            "total_images": 0,
            "download_urls": [],
            "errors": [{"config_error": "SERPAPI_KEY সেট করা নেই"}],
        }

    for index, b64_img in enumerate(clean_images, start=1):
        try:
            img_bytes = decode_image(b64_img)
            public_url = upload_temp_image(img_bytes)
        except Exception as e:
            debug_errors.append({"image": index, "upload_error": str(e)})
            continue

        try:
            results = GoogleSearch({
                "engine": "google_lens",
                "url": public_url,
                "api_key": SERPAPI_KEY,
            }).get_dict()
        except Exception as e:
            debug_errors.append({"image": index, "serpapi_error": str(e)})
            continue

        if "error" in results:
            debug_errors.append({"image": index, "serpapi_error": results["error"]})
            continue

        matches = results.get("visual_matches", [])
        picked = pick_matches(matches)
        all_related_image_urls.extend(picked)

        if not picked:
            debug_errors.append({
                "image": index,
                "no_results": True,
                "uploaded_url": public_url,
                "result_keys": [k for k in results.keys() if k != "search_parameters"],
                "visual_matches_count": len(matches),
                "serpapi_link": results.get("search_metadata", {}).get("google_lens_url", ""),
            })

    return {
        "status": "success",
        "received_count": len(clean_images),
        "total_images": len(all_related_image_urls),
        "download_urls": all_related_image_urls,
        "errors": debug_errors,
    }
