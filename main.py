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
    return {"status": "ok"}


def cleanup_keep_only(target_ext, base_name):
    """
    Remove any files with base_name that do not end with target_ext.
    """
    for path in glob.glob(os.path.join(DOWNLOAD_DIR, base_name + ".*")):
        if not path.lower().endswith(target_ext.lower()):
            try:
                os.remove(path)
            except Exception:
                pass


@app.get("/download")
def download(
    url: str = Query(..., description="Video URL"),
    format_type: str = Query("mp4", regex="^(mp4|mp3)$", description="mp4 or mp3"),
    # quality param is accepted but ignored for mp4 — mp4 will always download highest available quality
    quality: int = Query(None, description="(ignored for mp4) optional hint only")
):
    if not url:
        raise HTTPException(status_code=400, detail="URL required")

    base_name = str(uuid.uuid4())
    outtmpl = os.path.join(DOWNLOAD_DIR, base_name + ".%(ext)s")

    # ensure yt-dlp uses android player for bypassing 403 sometimes
    common_extractor_args = {"youtube": {"player_client": ["android"]}}

    try:
        if format_type == "mp3":
            # audio-only: download best audio, convert to mp3, then delete intermediates
            opts = {
                "format": "bestaudio/best",
                "outtmpl": outtmpl,
                "quiet": True,
                "nocheckcertificate": True,
                "extractor_args": common_extractor_args,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
                # ensure ffmpeg used when possible
                "prefer_ffmpeg": True,
                # keep temporary files so we can explicitly cleanup afterwards
                "keepvideo": False,
            }

            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

            # After conversion, find the mp3 file
            mp3_matches = glob.glob(os.path.join(DOWNLOAD_DIR, base_name + ".mp3"))
            if not mp3_matches:
                # sometimes yt-dlp outputs .m4a then postprocessor failed — report useful debug
                other_matches = glob.glob(os.path.join(DOWNLOAD_DIR, base_name + ".*"))
                raise HTTPException(status_code=500, detail=f"mp3 not produced. files: {other_matches}")

            # remove any other leftover files (e.g., .m4a, .webm)
            cleanup_keep_only(".mp3", base_name)
            filename = os.path.basename(mp3_matches[0])
            return {"download_url": f"/files/{filename}", "filename": filename}

        else:
            # mp4: choose highest available quality (ignore quality param)
            # use "bestvideo+bestaudio/best" which picks highest video and merges with best audio
            opts = {
                "format": "bestvideo+bestaudio/best",
                "outtmpl": outtmpl,
                "merge_output_format": "mp4",
                "quiet": True,
                "nocheckcertificate": True,
                "extractor_args": common_extractor_args,
                "postprocessor_args": ["-movflags", "+faststart"],
                "prefer_ffmpeg": True,
            }

            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

            # find mp4 (or fallback to any created file)
            matches = glob.glob(os.path.join(DOWNLOAD_DIR, base_name + ".*"))
            if not matches:
                raise HTTPException(status_code=500, detail="Downloaded file not found after yt_dlp run")

            # prefer mp4
            chosen = None
            for m in matches:
                if m.lower().endswith(".mp4"):
                    chosen = m
                    break
            if not chosen:
                chosen = matches[0]

            filename = os.path.basename(chosen)
            # remove any other files to keep storage clean (keep mp4)
            cleanup_keep_only(".mp4", base_name)
            return {"download_url": f"/files/{filename}", "filename": filename}

    except yt_dlp.utils.DownloadError as de:
        # provide clearer debug
        raise HTTPException(status_code=500, detail=f"yt-dlp download error: {str(de)}")
    except Exception as e:
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
