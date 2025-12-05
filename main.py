# main.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import yt_dlp
import os
import uuid
import uvicorn
import glob

app = FastAPI()
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


@app.get("/")
def root():
    return {"status": "ok", "message": "Kaneki Downloader (Playback Fixed)"}


def choose_best_video_format(info, max_height=None):
    """
    From info['formats'], choose the best video-only or video-with-audio format id.
    Prefer mp4 (or formats with video track) and prefer those with highest height <= max_height.
    If none <= max_height, pick highest available.
    Returns format_id (string).
    """
    fmts = info.get("formats", []) or []
    video_candidates = []
    for f in fmts:
        # must have video
        if f.get("vcodec") and f.get("vcodec") != "none":
            # prefer container mp4 (safer for web) but still keep others
            video_candidates.append({
                "format_id": f.get("format_id"),
                "height": f.get("height") or 0,
                "ext": f.get("ext"),
                "vcodec": f.get("vcodec"),
                "acodec": f.get("acodec")  # may include audio or none
            })
    if not video_candidates:
        return None

    # filter by max_height if provided
    if max_height:
        under = [v for v in video_candidates if (v["height"] or 0) <= max_height]
        if under:
            # pick highest height among under
            best = sorted(under, key=lambda x: x["height"] or 0, reverse=True)[0]
            return best["format_id"]

    # fallback: pick highest available
    best = sorted(video_candidates, key=lambda x: x["height"] or 0, reverse=True)[0]
    return best["format_id"]


def choose_best_audio_format(info):
    """
    Choose the best audio-only format id (prefer m4a/webm with high abr).
    Returns format_id or None.
    """
    fmts = info.get("formats", []) or []
    audio_candidates = []
    for f in fmts:
        if (f.get("vcodec") is None) or (f.get("vcodec") == "none"):
            # audio-only
            audio_candidates.append({
                "format_id": f.get("format_id"),
                "ext": f.get("ext"),
                "abr": f.get("abr") or 0,
                "filesize": f.get("filesize") or 0
            })
    if not audio_candidates:
        return None
    # sort by abr then filesize
    audio_candidates.sort(key=lambda x: (x["abr"] or 0, x["filesize"] or 0), reverse=True)
    return audio_candidates[0]["format_id"]


@app.get("/formats")
def get_formats(url: str = Query(..., description="Video URL")):
    if not url:
        raise HTTPException(status_code=400, detail="URL required")

    opts = {
        "quiet": True,
        "skip_download": True,
        "nocheckcertificate": True,
        "extractor_args": {"youtube": {"player_client": ["android"]}},
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        for f in info.get("formats", []):
            ext = f.get("ext")
            vcodec = f.get("vcodec")
            acodec = f.get("acodec")
            height = f.get("height")
            # Video formats (has video track)
            if vcodec and vcodec != "none":
                label = f"{height or '?'}p"
                if "avc1" in (vcodec or ""):
                    label += " (Web Safe)"
                formats.append({
                    "format_id": f.get("format_id"),
                    "label": label,
                    "height": height,
                    "ext": ext,
                    "type": "video"
                })
            # audio-only
            else:
                formats.append({
                    "format_id": f.get("format_id"),
                    "label": f"audio - {ext} - {f.get('abr') or ''}kbps",
                    "height": None,
                    "ext": ext,
                    "type": "audio"
                })

        # sort videos by height desc (audio will have height None)
        formats.sort(key=lambda x: (x["height"] or 0), reverse=True)
        return {"formats": formats}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/download")
def download(
    url: str = Query(..., description="Video URL"),
    format_id: str = Query(None, description="format id from /formats (for mp4)"),
    format_type: str = Query("mp4", regex="^(mp4|mp3)$", description="mp4 or mp3"),
    quality: int = Query(None, description="quality in px (e.g. 1080 or 720). used only when format_id omitted for mp4")
):
    if not url:
        raise HTTPException(status_code=400, detail="URL required")

    base_name = str(uuid.uuid4())
    outtmpl = os.path.join(DOWNLOAD_DIR, base_name + ".%(ext)s")

    try:
        # first extract info to make robust format decisions
        ydl_info_opts = {
            "quiet": True,
            "skip_download": True,
            "nocheckcertificate": True,
            "extractor_args": {"youtube": {"player_client": ["android"]}},
        }
        with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if format_type == "mp3":
            # choose the best audio format id (optional)
            audio_fmt_id = choose_best_audio_format(info)
            # If audio_fmt_id found, request that + postprocess to mp3; otherwise use bestaudio
            if audio_fmt_id:
                fmt_selector = f"{audio_fmt_id}"
            else:
                fmt_selector = "bestaudio/best"

            opts = {
                "format": fmt_selector,
                "outtmpl": outtmpl,
                "quiet": True,
                "nocheckcertificate": True,
                "extractor_args": {"youtube": {"player_client": ["android"]}},
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
                # don't force merge_output_format here (audio only)
                "prefer_ffmpeg": True,
            }

        else:
            # mp4 workflow: determine which video format id to use
            chosen_video_fmt = None
            if format_id:
                # user-specified format_id - use it directly (combine with bestaudio)
                chosen_video_fmt = format_id
            else:
                chosen_video_fmt = choose_best_video_format(info, max_height=quality)

            if chosen_video_fmt:
                fmt_selector = f"{chosen_video_fmt}+bestaudio/best"
            else:
                # fallback to bestvideo+bestaudio/best (yt_dlp will pick highest available)
                fmt_selector = "bestvideo+bestaudio/best"

            opts = {
                "format": fmt_selector,
                "outtmpl": outtmpl,
                "merge_output_format": "mp4",
                "quiet": True,
                "nocheckcertificate": True,
                "extractor_args": {"youtube": {"player_client": ["android"]}},
                "postprocessor_args": ["-movflags", "+faststart"],
                "prefer_ffmpeg": True,
            }

        # Download
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        # find created file(s)
        matches = glob.glob(os.path.join(DOWNLOAD_DIR, base_name + ".*"))
        if not matches:
            raise HTTPException(status_code=500, detail="Downloaded file not found after yt_dlp run")

        # pick the correct file (mp3 preferred if requested)
        chosen = None
        if format_type == "mp3":
            for m in matches:
                if m.lower().endswith(".mp3"):
                    chosen = m
                    break
        if not chosen:
            # prefer mp4, then m4a, then mp3
            for ext_pref in (".mp4", ".m4a", ".mp3"):
                for m in matches:
                    if m.lower().endswith(ext_pref):
                        chosen = m
                        break
                if chosen:
                    break
        if not chosen:
            chosen = matches[0]

        filepath = chosen
        filename = os.path.basename(filepath)
        return {"download_url": f"/files/{filename}", "filename": filename}

    except Exception as e:
        # helpful server log
        print("Download error:", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/file/{filename}")
def get_file(filename: str):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    ext = filename.split(".")[-1].lower()
    if ext == "mp4":
        media_type = "video/mp4"
    elif ext == "mp3":
        media_type = "audio/mpeg"
    elif ext in ("m4a", "mp4a", "aac"):
        media_type = "audio/mp4"
    else:
        media_type = "application/octet-stream"
    return FileResponse(filepath, media_type=media_type, filename=filename)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
