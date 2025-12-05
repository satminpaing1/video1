import os
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import yt_dlp

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app.mount("/files", StaticFiles(directory=DOWNLOAD_DIR), name="files")

# frontend မှာသုံးထားတဲ့ audio-only format id နဲ့ကိုက်စေဖို
SPECIAL_AUDIO_FORMAT = "bestaudio[ext=m4a]/bestaudio"


@app.get("/")
def root():
    return {"status": "ok", "message": "ThuYaAungZaw Downloader (YouTube H264 720p/360p)"} 


# ------------------------------------------------------------
# FORMATS – frontend resolution dropdown ပဲ
# ------------------------------------------------------------
@app.get("/formats")
def get_formats(url: str):
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    # UI အတွက် 720p / 480p / 360p ပြမယ် – backend မှာ quality ကို handle လုပ်မယ်
    formats = [
        {"format_id": "q720", "label": "720p"},
        {"format_id": "q480", "label": "480p"},
        {"format_id": "q360", "label": "360p"},
    ]
    return {"formats": formats}


# ------------------------------------------------------------
# INTERNAL HELPERS
# ------------------------------------------------------------
def download_audio_only(url: str) -> str:
    """Audio only – MP3 / M4A (Frontend က MP3 / Audio only)."""
    uid = str(uuid.uuid4())
    out_tmpl = os.path.join(DOWNLOAD_DIR, uid + ".%(ext)s")

    ydl_opts = {
        "format": SPECIAL_AUDIO_FORMAT,
        "outtmpl": out_tmpl,
        "quiet": True,
        "noplaylist": True,
        "nocheckcertificate": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)

    return os.path.basename(path)


def _choose_best_format(info, quality_tag: str):
    """
    info = yt-dlp extract_info(..., download=False)
    quality_tag = 'q720' / 'q480' / 'q360'
    YouTube ကိုအရင် handle လုပ်ပြီး, မဟုတ်ရင် generic progressive mp4 H.264 ကိုရွေးမယ်။
    """
    extractor = (info.get("extractor") or "").lower()
    formats = info.get("formats", []) or []

    def find_by_id(fid):
        return next((f for f in formats if f.get("format_id") == fid), None)

    # --------- YouTube သီးသန့်: format 22 (720p), 18 (360p) ---------
    if "youtube" in extractor:
        # 22 = 720p H.264 + audio
        # 18 = 360p H.264 + audio
        if quality_tag == "q720":
            for fid in ["22", "18"]:
                f = find_by_id(fid)
                if f:
                    return f
        elif quality_tag == "q480":
            # YouTube မှာ 480p progressive မကြီးသလောက် → 18/22 ထဲက သင့်တော်ဆုံးကို
            for fid in ["22", "18"]:
                f = find_by_id(fid)
                if f:
                    return f
        else:  # q360
            for fid in ["18", "22"]:
                f = find_by_id(fid)
                if f:
                    return f
        # အပြီးသတ်ပြီးလည်း မတွေ့ရင် generic ထဲကို ပြန်ကျမယ်

    # --------- Generic progressive mp4 (H.264ကိုအရင်ရွေး) ---------
    preferred_max = 720 if quality_tag == "q720" else 480 if quality_tag == "q480" else 360

    prog = [
        f for f in formats
        if (f.get("vcodec") or "").lower() != "none"
        and (f.get("acodec") or "").lower() != "none"
        and (f.get("ext") or "").lower() == "mp4"
    ]

    h264 = [
        f for f in prog
        if (f.get("vcodec") or "").lower().startswith("avc1")
        or "h264" in (f.get("vcodec") or "").lower()
    ]

    def best_under(cands, max_h):
        ok = [f for f in cands if (f.get("height") or 0) <= max_h]
        if ok:
            return sorted(ok, key=lambda x: x.get("height") or 0, reverse=True)[0]
        if cands:
            return sorted(cands, key=lambda x: x.
                          get("height") or 0, reverse=True)[0]
        return None

    f = best_under(h264, preferred_max)
    if f:
        return f

    f = best_under(prog, preferred_max)
    return f


def download_video_stable(url: str, quality_tag: str) -> str:
    """
    URL + quality_tag(q720/q480/q360) ထဲကနေ
    iPhone/Safari playable ဖြစ်မယ့် progressive mp4 format ကိုရွေးပြီး download လုပ်မယ်။
    """

    base_opts = {
        "quiet": True,
        "noplaylist": True,
        "nocheckcertificate": True,
    }

    # 1) Info only – format table ရယူမယ်
    with yt_dlp.YoutubeDL({**base_opts, "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False)

    chosen = _choose_best_format(info, quality_tag)
    if not chosen:
        raise RuntimeError("No suitable progressive MP4 format found")

    fmt_id = chosen.get("format_id")
    out_tmpl = os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s")

    # 2) actual download
    ydl_opts = {
        **base_opts,
        "format": fmt_id,
        "outtmpl": out_tmpl,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info2 = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info2)

    return os.path.basename(path)


# ------------------------------------------------------------
# DOWNLOAD ENDPOINT
# ------------------------------------------------------------
@app.get("/download")
def download(url: str, format_id: str):
    if not url or not format_id:
        raise HTTPException(status_code=400, detail="Missing url or format_id")

    try:
        if format_id == SPECIAL_AUDIO_FORMAT:
            filename = download_audio_only(url)
        else:
            # format_id = q720 / q480 / q360
            filename = download_video_stable(url, format_id)

        return {
            "download_url": f"/file/{filename}",
            "filename": filename,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download error: {e}")


# ------------------------------------------------------------
# SERVE FILE
# ------------------------------------------------------------
@app.get("/file/{filename}")
def get_file(filename: str):
    path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")

    lower = filename.lower()
    if lower.endswith(".mp3") or lower.endswith(".m4a") or lower.endswith(".aac"):
        media_type = "audio/mpeg"
    else:
        media_type = "video/mp4"

    return FileResponse(path, media_type=media_type, filename=filename)
