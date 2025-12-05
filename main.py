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
            if f.get("ext") == "mp4" and f.get("vcodec") != "none":
                label = f"{f.get('height')}p"
                if "avc1" in (f.get("vcodec") or ""):
                    label += " (Web Safe)"
                formats.append({
                    "format_id": f.get("format_id"),
                    "label": label,
                    "height": f.get("height")
                })

        formats.sort(key=lambda x: x["height"] or 0, reverse=True)
        return {"formats": formats}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/download")
def download(
    url: str = Query(..., description="Video URL"),
    format_id: str = Query(None, description="format id from /formats (for mp4). If omitted for mp3 download, use format_type=mp3"),
    format_type: str = Query("mp4", regex="^(mp4|mp3)$", description="mp4 or mp3")
):
    """
    - format_type = "mp4" (default): requires format_id (e.g. from /formats), will download video+audio and output mp4.
    - format_type = "mp3": will download best audio and convert to mp3.
    """
    if not url:
        raise HTTPException(status_code=400, detail="URL required")

    # unique base name (we'll let yt_dlp choose the final extension)
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
                # pass-through args to ffmpeg when extracting (optional)
                "postprocessor_args": ["-vn"],
            }
        else:
            # mp4 workflow - we expect client to pass a valid format_id (video)
            if not format_id:
                raise HTTPException(status_code=400, detail="format_id required for mp4 downloads")
            
            # format: combine chosen video format with best audio
            opts = {
                "format": f"{format_id}+bestaudio/best",
                "outtmpl": outtmpl,
                "merge_output_format": "mp4",
                "quiet": True,
                "nocheckcertificate": True,
                "extractor_args": {"youtube": {"player_client": ["android"]}},
                # ensure faststart so browser can stream / seek
                "postprocessor_args": ["-movflags", "+faststart"],
            }

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        # find created file (could be .mp4, .m4a, .mp3, etc.)
        matches = glob.glob(os.path.join(DOWNLOAD_DIR, base_name + ".*"))
        if not matches:
            raise HTTPException(status_code=500, detail="Downloaded file not found after yt_dlp run")
        filepath = matches[0]
        filename = os.path.basename(filepath)

        return {"download_url": f"/files/{filename}", "filename": filename}

    except Exception as e:
        # keep a server-side log (optional)
        print(f"Error during download: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/file/{filename}")
def get_file(filename: str):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    # video/mp4 for mp4, audio/mpeg for mp3, fallback to octet-stream for unknown
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
