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
import shutil
import sys
import time

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


def find_generated_file(base_name):
    matches = glob.glob(os.path.join(DOWNLOAD_DIR, base_name + ".*"))
    return matches


def cleanup_except(base_name, keep_exts):
    for path in glob.glob(os.path.join(DOWNLOAD_DIR, base_name + ".*")):
        if not any(path.lower().endswith(ext) for ext in keep_exts):
            try:
                os.remove(path)
            except Exception:
                pass


@app.get("/download")
def download(
    url: str = Query(..., description="Video URL"),
    format_type: str = Query("mp4", regex="^(mp4|mp3)$", description="mp4 or mp3")
):
    """
    - format_type=mp3 -> download best audio and convert to mp3 (single .mp3 output)
    - format_type=mp4 -> always download highest available video quality (bestvideo+bestaudio) and output .mp4
    """
    if not url:
        raise HTTPException(status_code=400, detail="URL required")

    base_name = str(uuid.uuid4())
    outtmpl = os.path.join(DOWNLOAD_DIR, base_name + ".%(ext)s")

    common = {
        "outtmpl": outtmpl,
        "quiet": False,               # show console logs to diagnose if needed
        "no_warnings": True,
        "nocheckcertificate": True,
        "extractor_args": {"youtube": {"player_client": ["android"]}},
        "prefer_ffmpeg": True,
    }

    try:
        if format_type == "mp3":
            # audio-only workflow -> produce single .mp3
            opts = {
                **common,
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
                # ensure ffmpeg invoked
                "keepvideo": False,
            }

            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

            # try to find mp3
            matches = find_generated_file(base_name)
            mp3 = next((m for m in matches if m.lower().endswith(".mp3")), None)
            if not mp3:
                # sometimes yt-dlp might output .m4a then postprocessor failed; list files for debug
                raise HTTPException(status_code=500, detail=f"mp3 not produced; generated: {matches}")

            # remove any other leftover files, keep only mp3
            cleanup_except(base_name, [".mp3"])
            filename = os.path.basename(mp3)
            return {"download_url": f"/files/{filename}", "filename": filename}

        else:
            # mp4 workflow: always pick highest available video quality
            # 'bestvideo+bestaudio/best' asks yt-dlp to choose best video and merge
            opts = {
                **common,
                "format": "bestvideo+bestaudio/best",
                "merge_output_format": "mp4",
                "postprocessor_args": ["-movflags", "+faststart"],
            }

            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

            # find mp4
            matches = find_generated_file(base_name)
            if not matches:
                raise HTTPException(status_code=500, detail="No file generated after download")

            # prefer mp4
            chosen = next((m for m in matches if m.lower().endswith(".mp4")), matches[0])
            # cleanup others, keep mp4
            cleanup_except(base_name, [os.path.splitext(chosen)[1]])
            filename = os.path.basename(chosen)
            return {"download_url": f"/files/{filename}", "filename": filename}

    except yt_dlp.utils.DownloadError as de:
        # yt-dlp-specific download problems
        print("yt-dlp DownloadError:", de, file=sys.stderr)
        raise HTTPException(status_code=500, detail=f"yt-dlp download error: {str(de)}")
    except Exception as e:
        # general exception; include repr for debugging
        print("Download exception:", repr(e), file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/file/{filename}")
def serve_file(filename: str):
    path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Not found")
    ext = filename.split(".")[-1].lower()
    if ext == "mp4":
        mime = "video/mp4"
    elif ext == "mp3":
        mime = "audio/mpeg"
    elif ext in ("m4a", "mp4a", "aac"):
        mime = "audio/mp4"
    else:
        mime = "application/octet-stream"
    return FileResponse(path, media_type=mime, filename=filename)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
