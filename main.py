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


def _url_of(value):
    # কিছু API-তে ছবি সরাসরি লিংক, কিছুতে {"link": ...}
    if isinstance(value, dict):
        value = value.get("link")
    if isinstance(value, str) and value.startswith("http"):
        return value
    return None


def pick_matches(matches):
    # আগে AliExpress/Amazon/Alibaba, তারপর বাকিগুলো
    preferred, others = [], []
    for match in matches:
        source = str(match.get("source") or "").lower()
        link = str(match.get("link") or "").lower()
        if any(site in source or site in link for site in PREFERRED_SITES):
            preferred.append(match)
        else:
            others.append(match)

    urls = []
    for match in preferred + others:
        # বড় ছবি আগে, না পেলে thumbnail
        img_link = None
        for key in ["original", "original_image", "image", "thumbnail"]:
            img_link = _url_of(match.get(key))
            if img_link:
                break
        if img_link and img_link not in urls:
            urls.append(img_link)
        if len(urls) >= MAX_PER_IMAGE:
            break
    return urls


def search_google_lens(public_url):
    results = GoogleSearch({
        "engine": "google_lens",
        "type": "visual_matches",
        "url": public_url,
        "api_key": SERPAPI_KEY,
    }).get_dict()
    if "error" in results:
        raise Exception(results["error"])
    return results.get("visual_matches", []) + results.get("exact_matches", [])


def search_yandex(public_url):
    matches = []
    # "similar" ট্যাবে একই রকম দেখতে ছবি
    results = GoogleSearch({
        "engine": "yandex_images",
        "url": public_url,
        "tab": "similar",
        "api_key": SERPAPI_KEY,
    }).get_dict()
    if "error" in results:
        raise Exception(results["error"])
    matches += results.get("images_results", [])
    matches += results.get("similar_images", [])
    shopping = results.get("shopping_results")
    if isinstance(shopping, dict):
        matches += shopping.get("products", [])
    elif isinstance(shopping, list):
        for block in shopping:
            if isinstance(block, dict):
                matches += block.get("products", [block])
    return matches


SEARCH_ENGINES = [
    ("google_lens", search_google_lens),
    ("yandex", search_yandex),
]


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

        # প্রথমে Google Lens, কিছু না পেলে Yandex
        picked = []
        tried = []
        for engine_name, search_fn in SEARCH_ENGINES:
            try:
                matches = search_fn(public_url)
            except Exception as e:
                tried.append({"engine": engine_name, "error": str(e)})
                continue
            picked = pick_matches(matches)
            tried.append({"engine": engine_name, "matches": len(matches)})
            if picked:
                break

        all_related_image_urls.extend(picked)

        if not picked:
            debug_errors.append({
                "image": index,
                "no_results": True,
                "uploaded_url": public_url,
                "tried": tried,
            })

    return {
        "status": "success",
        "received_count": len(clean_images),
        "total_images": len(all_related_image_urls),
        "download_urls": all_related_image_urls,
        "errors": debug_errors,
    }
