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
    return {"status": "ok", "message": "Kaneki Downloader V2.3 (Fixed)"}


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
            height = f.get("height")
            
            # Video formats
            if vcodec and vcodec != "none" and height:
                label = f"{height}p"
                if f.get("fps"):
                    label += f"{f.get('fps')}fps"
                formats.append({
                    "format_id": f.get("format_id"),
                    "label": f"🎬 Video {label} ({ext})",
                    "height": height,
                    "ext": ext,
                    "type": "video"
                })

        # Sort videos by height (Quality)
        formats.sort(key=lambda x: (x["height"] or 0), reverse=True)
        
        # Add Audio Option manually at the top
        formats.insert(0, {
            "format_id": "bestaudio/best",
            "label": "🎵 MP3 Audio (Best Quality)",
            "height": 0,
            "ext": "mp3",
            "type": "audio"
        })

        return {"formats": formats}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/download")
def download(
    url: str = Query(..., description="Video URL"),
    format_id: str = Query(None, description="format id"),
    format_type: str = Query("mp4", regex="^(mp4|mp3)$", description="mp4 or mp3")
):
    if not url:
        raise HTTPException(status_code=400, detail="URL required")

    base_name = str(uuid.uuid4())
    
    # Options setup
    ydl_opts = {
        "quiet": True,
        "nocheckcertificate": True,
        "extractor_args": {"youtube": {"player_client": ["android"]}},
        "outtmpl": os.path.join(DOWNLOAD_DIR, f"{base_name}.%(ext)s"),
        "prefer_ffmpeg": True,
    }

    try:
        if format_type == "mp3":
            # MP3 Logic - Best Audio Quality
            ydl_opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "0",  # 0 is best quality in ffmpeg
                }],
            })
        else:
            # MP4 Logic - Selected Video + Best Audio
            # If format_id is provided (e.g. 137), use it. Else fallback to best.
            video_fmt = format_id if format_id and format_id != "bestaudio/best" else "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
            
            # Ensure we merge video+audio into mp4
            if "+" in video_fmt or "best" in video_fmt:
                 ydl_opts.update({
                    "format": f"{video_fmt}",
                    "merge_output_format": "mp4",
                    "postprocessor_args": ["-movflags", "+faststart"],
                })
            else:
                 ydl_opts.update({
                    "format": f"{video_fmt}+bestaudio/best",
                    "merge_output_format": "mp4",
                    "postprocessor_args": ["-movflags", "+faststart"],
                })

        # Download
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Find the file
        matches = glob.glob(os.path.join(DOWNLOAD_DIR, base_name + ".*"))
        if not matches:
            raise HTTPException(status_code=500, detail="File creation failed")

        final_file = matches[0]
        filename = os.path.basename(final_file)
        
        return {"download_url": f"/files/{filename}", "filename": filename}

    except Exception as e:
        print("Error:", e)
        raise HTTPException(status_code=500, detail=str(e))
