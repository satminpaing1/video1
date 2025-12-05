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
            # collect useful formats: video mp4 variants (with video), and audio-only too
            ext = f.get("ext")
            vcodec = f.get("vcodec")
            acodec = f.get("acodec")
            height = f.get("height")
            # Video formats (mp4 with video)
            if ext == "mp4" and vcodec != "none":
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
            # audio-only (m4a, webm, etc.)
            elif vcodec == "none" and acodec and (ext in ("m4a", "mp3", "webm", "m4a")):
                formats.append({
                    "format_id": f.get("format_id"),
                    "label": f"audio - {ext}",
                    "height": None,
                    "ext": ext,
                    "type": "audio"
                })

        # sort videos by height desc
        formats.sort(key=lambda x: (x["height"] or 0), reverse=True)
        return {"formats": formats}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/download")
def download(
    url: str = Query(..., description="Video URL"),
    # for mp4: either provide format_id OR quality (e.g. 1080, 720)
    format_id: str = Query(None, description="format id from /formats (for mp4)"),
    format_type: str = Query("mp4", regex="^(mp4|mp3)$", description="mp4 or mp3"),
    quality: int = Query(None, description="quality in px (e.g. 1080 or 720). used only when format_id omitted for mp4")
):
    if not url:
        raise HTTPException(status_code=400, detail="URL required")

    # unique base name (let yt_dlp pick the extension via %(ext)s)
    base_name = str(uuid.uuid4())
    outtmpl = os.path.join(DOWNLOAD_DIR, base_name + ".%(ext)s")

    try:
        if format_type == "mp3":
            # audio-only workflow -> produce .mp3 via FFmpegExtractAudio
            opts = {
                "format": "bestaudio/best",
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
                # ensure ffmpeg doesn't include video (safe)
                "postprocessor_args": ["-vn"],
            }

        else:
            # mp4 workflow
            if format_id:
                fmt = f"{format_id}+bestaudio/best"
            else:
                # if quality provided, try to choose bestvideo <= quality
                if quality:
                    # construct selector; yt_dlp supports bestvideo[height<=X]
                    fmt = f"bestvideo[height<={quality}]+bestaudio/best"
                else:
                    # fallback to best combined
                    fmt = "bestvideo+bestaudio/best"

            opts = {
                "format": fmt,
                "outtmpl": outtmpl,
                "merge_output_format": "mp4",
                "quiet": True,
                "nocheckcertificate": True,
                "extractor_args": {"youtube": {"player_client": ["android"]}},
                # ensure faststart for web playback/seek
                "postprocessor_args": ["-movflags", "+faststart"],
            }

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        # find created file(s)
        matches = glob.glob(os.path.join(DOWNLOAD_DIR, base_name + ".*"))
        if not matches:
            raise HTTPException(status_code=500, detail="Downloaded file not found after yt_dlp run")

        # prefer mp3 if requested, otherwise prefer mp4, then any
        chosen = None
        if format_type == "mp3":
            for m in matches:
                if m.lower().endswith(".mp3"):
                    chosen = m
                    break
        if not chosen:
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
        print(f"Error during download: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/file/{filename}")
def get_file(filename: str):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    # media types
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
