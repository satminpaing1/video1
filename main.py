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
import subprocess

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DOWNLOAD_DIR = "downloads"
# Startup: Clean old downloads
if os.path.exists(DOWNLOAD_DIR):
    shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app.mount("/files", StaticFiles(directory=DOWNLOAD_DIR), name="files")

# --- FFmpeg Diagnostic ---
print("--- SYSTEM CHECK ---")
ffmpeg_path = shutil.which("ffmpeg")
if ffmpeg_path:
    print(f"✅ FFmpeg found at: {ffmpeg_path}")
else:
    print("❌ CRITICAL: FFmpeg NOT FOUND. Installing via image config is required.")
print("--------------------")

@app.get("/")
def root():
    return {"status": "ok", "message": "Kaneki V3.0 (FFmpeg Forced)"}

@app.get("/formats")
def get_formats(url: str = Query(..., description="Video URL")):
    if not url:
        raise HTTPException(status_code=400, detail="URL required")

    opts = {
        "quiet": True,
        "skip_download": True,
        "nocheckcertificate": True,
        # Use android_creator to potentially see better formats on server IPs
        "extractor_args": {"youtube": {"player_client": ["android_creator", "android"]}},
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        seen_qualities = set()

        for f in info.get("formats", []):
            ext = f.get("ext")
            vcodec = f.get("vcodec")
            height = f.get("height")
            
            if vcodec and vcodec != "none" and height:
                if height not in seen_qualities and ext in ['mp4', 'webm']:
                    seen_qualities.add(height)
                    label = f"{height}p"
                    formats.append({
                        "format_id": f.get("format_id"),
                        "label": f"🎬 Video {label} ({ext})",
                        "height": height,
                        "ext": ext,
                        "type": "video"
                    })

        formats.sort(key=lambda x: (x["height"] or 0), reverse=True)
        formats.insert(0, {"format_id": "bestaudio", "label": "🎵 MP3 Music (Best Quality)", "height": 0, "ext": "mp3", "type": "audio"})

        return {"formats": formats}

    except Exception as e:
        print(f"Format Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Could not analyze link.")

@app.get("/download")
def download(
    url: str = Query(..., description="Video URL"),
    format_id: str = Query(None, description="Format ID"),
    format_type: str = Query("mp4", description="mp3 or mp4")
):
    base_name = str(uuid.uuid4())
    
    # Configure options
    ydl_opts = {
        "quiet": True,
        "nocheckcertificate": True,
        "outtmpl": os.path.join(DOWNLOAD_DIR, f"{base_name}.%(ext)s"),
        "extractor_args": {"youtube": {"player_client": ["android_creator", "android"]}},
        "prefer_ffmpeg": True,
        "retries": 3,
    }

    try:
        # --- MP3 LOGIC ---
        if format_type == "mp3":
            ydl_opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        
        # --- VIDEO LOGIC ---
        else:
            # Explicitly request merge if format_id is provided
            if format_id and format_id != "bestaudio":
                 # If user picked 1080p (e.g., 137), we need to merge with audio
                 # If ffmpeg is missing, this usually fails or falls back
                 ydl_opts.update({
                    "format": f"{format_id}+bestaudio/best" if "+" not in format_id else format_id,
                    "merge_output_format": "mp4",
                })
            else:
                ydl_opts.update({
                    "format": "bestvideo+bestaudio/best",
                    "merge_output_format": "mp4",
                })
            ydl_opts.update({"postprocessor_args": ["-movflags", "+faststart"]})

        # --- DOWNLOAD ---
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # --- FILE POST-PROCESSING (CRITICAL FIX) ---
        # Find what file was actually created
        files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{base_name}.*"))
        if not files:
            raise Exception("File not created.")
        
        final_file = files[0]
        final_filename = os.path.basename(final_file)
        
        # 1. FIX MP3 EXTENSION
        if format_type == "mp3":
            # If yt-dlp produced .m4a or .webm instead of .mp3, convert it manually
            if not final_file.endswith(".mp3"):
                new_path = os.path.join(DOWNLOAD_DIR, f"{base_name}.mp3")
                print(f"Converting {final_file} to {new_path}...")
                subprocess.run(["ffmpeg", "-i", final_file, "-vn", "-ab", "192k", new_path, "-y"], check=True)
                final_file = new_path
                final_filename = f"{base_name}.mp3"

        # 2. FIX VIDEO EXTENSION (Ensure .mp4)
        elif format_type == "mp4" and not final_file.endswith(".mp4"):
             # If it's .mkv or .webm, just rename it to .mp4 for browser compatibility (simple container swap attempt)
             # Or better, let backend serve it but tell frontend it's mp4
             new_path = os.path.join(DOWNLOAD_DIR, f"{base_name}.mp4")
             shutil.move(final_file, new_path)
             final_file = new_path
             final_filename = f"{base_name}.mp4"

        return {"download_url": f"/files/{final_filename}", "filename": final_filename}

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
