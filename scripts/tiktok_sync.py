"""
مزامنة مقاطع تيك توك لحساب الجمعية.
- يجدد صلاحية الدخول باستخدام refresh token
- يجلب آخر المقاطع من TikTok Display API
- يحفظ الأغلفة داخل المستودع (روابط تيك توك للأغلفة تنتهي بعد 6 ساعات)
- يكتب tiktok/videos.json الذي تقرأه الصفحة

المتغيرات المطلوبة (من أسرار GitHub):
  TT_CLIENT_KEY, TT_CLIENT_SECRET, TT_REFRESH_TOKEN
يكتب رمز التجديد الجديد (إن تغيّر) في الملف المحدد بـ NEW_REFRESH_FILE ليحدّثه سير العمل في الأسرار.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "tiktok"
COVERS = OUT_DIR / "covers"
MAX_VIDEOS = 20
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
LIST_URL = "https://open.tiktokapis.com/v2/video/list/"
USER_URL = "https://open.tiktokapis.com/v2/user/info/"
FIELDS = "id,title,video_description,create_time,cover_image_url,embed_link,share_url,duration"


def http(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def mask(value):
    if value and os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{value}")


def refresh_tokens():
    body = urllib.parse.urlencode({
        "client_key": os.environ["TT_CLIENT_KEY"],
        "client_secret": os.environ["TT_CLIENT_SECRET"],
        "grant_type": "refresh_token",
        "refresh_token": os.environ["TT_REFRESH_TOKEN"],
    }).encode()
    res = json.loads(http(TOKEN_URL, body, {"Content-Type": "application/x-www-form-urlencoded"}))
    if "access_token" not in res:
        sys.exit(f"فشل تجديد الصلاحية: {res.get('error')} – {res.get('error_description')}")
    mask(res["access_token"])
    mask(res.get("refresh_token"))
    new_rt = res.get("refresh_token")
    out = os.environ.get("NEW_REFRESH_FILE")
    if out and new_rt and new_rt != os.environ["TT_REFRESH_TOKEN"]:
        Path(out).write_text(new_rt)
        print("تم استلام رمز تجديد جديد وسيُحفظ في الأسرار.")
    return res["access_token"]


def api_post(url, token, payload):
    raw = http(url, json.dumps(payload).encode(),
               {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, "POST")
    res = json.loads(raw)
    err = res.get("error", {})
    if err.get("code") not in (None, "ok"):
        sys.exit(f"خطأ من تيك توك: {err.get('code')} – {err.get('message')}")
    return res.get("data", {})


def fetch_videos(token):
    videos, cursor = [], None
    while len(videos) < MAX_VIDEOS:
        payload = {"max_count": min(20, MAX_VIDEOS - len(videos))}
        if cursor:
            payload["cursor"] = cursor
        data = api_post(f"{LIST_URL}?fields={FIELDS}", token, payload)
        videos += data.get("videos", [])
        if not data.get("has_more"):
            break
        cursor = data.get("cursor")
    return videos[:MAX_VIDEOS]


def fetch_user(token):
    try:
        raw = http(f"{USER_URL}?fields=display_name,avatar_url,profile_deep_link",
                   headers={"Authorization": f"Bearer {token}"})
        return json.loads(raw).get("data", {}).get("user", {})
    except Exception as e:  # بيانات الحساب اختيارية
        print("تعذّر جلب بيانات الحساب:", e)
        return {}


def save_cover(vid, url):
    dest = COVERS / f"{vid}.jpg"
    if dest.exists():
        return dest
    try:
        dest.write_bytes(http(url, headers={"User-Agent": "Mozilla/5.0"}))
        return dest
    except Exception as e:
        print(f"تعذّر تنزيل غلاف {vid}: {e}")
        return None


def main():
    COVERS.mkdir(parents=True, exist_ok=True)
    token = refresh_tokens()
    videos = fetch_videos(token)
    user = fetch_user(token)

    items = []
    for v in videos:
        vid = str(v.get("id", ""))
        if not vid:
            continue
        cover = save_cover(vid, v["cover_image_url"]) if v.get("cover_image_url") else None
        items.append({
            "id": vid,
            "title": (v.get("title") or v.get("video_description") or "").strip(),
            "date": v.get("create_time"),
            "duration": v.get("duration"),
            "cover": f"tiktok/covers/{vid}.jpg" if cover else "",
            "embed": v.get("embed_link") or f"https://www.tiktok.com/player/v1/{vid}",
            "url": v.get("share_url") or "",
        })

    # حذف الأغلفة القديمة التي لم تعد في القائمة
    keep = {f"{i['id']}.jpg" for i in items}
    for f in COVERS.glob("*.jpg"):
        if f.name not in keep:
            f.unlink()

    out = {
        "updated": int(time.time()),
        "user": {"name": user.get("display_name", "")},
        "videos": items,
    }
    (OUT_DIR / "videos.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"تم حفظ {len(items)} مقطع.")


if __name__ == "__main__":
    main()
