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

# --- FFmpeg Check ---
print("--- CHECKING SYSTEM ---")
if shutil.which("ffmpeg"):
    print("✅ FFmpeg is installed and ready.")
else:
    print("❌ WARNING: FFmpeg is missing. MP3 conversion will fail.")
print("-----------------------")

@app.get("/")
def root():
    return {"status": "ok", "message": "Kaneki V3.2 (Web Client + Force FFmpeg)"}

@app.get("/formats")
def get_formats(url: str = Query(..., description="Video URL")):
    if not url:
        raise HTTPException(status_code=400, detail="URL required")

    # Use 'web' client to avoid PO Token errors shown in your logs
    opts = {
        "quiet": True,
        "skip_download": True,
        "nocheckcertificate": True,
        "extractor_args": {"youtube": {"player_client": ["web"]}},
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
            
            # Filter Video Formats
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
        formats.insert(0, {
            "format_id": "bestaudio", 
            "label": "🎵 MP3 Music (Best Quality)", 
            "height": 0, 
            "ext": "mp3", 
            "type": "audio"
        })

        return {"formats": formats}

    except Exception as e:
        print(f"Format Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Could not analyze video.")


@app.get("/download")
def download(
    url: str = Query(..., description="Video URL"),
    format_id: str = Query(None, description="Format ID"),
    format_type: str = Query("mp4", description="mp3 or mp4")
):
    base_name = str(uuid.uuid4())
    
    # Base Options
    ydl_opts = {
        "quiet": True,
        "nocheckcertificate": True,
        "outtmpl": os.path.join(DOWNLOAD_DIR, f"{base_name}.%(ext)s"),
        # Switching to 'web' client to stop the crashes
        "extractor_args": {"youtube": {"player_client": ["web"]}},
        "prefer_ffmpeg": True,
        "retries": 5,
    }

    try:
        if format_type == "mp3":
            # --- MP3 MODE ---
            ydl_opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        else:
            # --- VIDEO MODE ---
            if format_id and format_id != "bestaudio":
                 ydl_opts.update({
                    "format": f"{format_id}+bestaudio/best",
                    "merge_output_format": "mp4",
                })
            else:
                ydl_opts.update({
                    "format": "bestvideo+bestaudio/best",
                    "merge_output_format": "mp4",
                })

        # START DOWNLOAD
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # --- MANUAL PROCESSING ---
        files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{base_name}.*"))
        if not files:
            raise Exception("File failed to create.")
        
        final_file = files[0]
        final_filename = os.path.basename(final_file)

        # 1. FORCE MP3 CONVERSION
        if format_type == "mp3":
            if not final_file.endswith(".mp3"):
                print(f"⚠️ Manually converting {final_file} to MP3...")
                new_mp3_path = os.path.join(DOWNLOAD_DIR, f"{base_name}.mp3")
                
                # Check for FFmpeg again before running
                if shutil.which("ffmpeg"):
                    cmd = ["ffmpeg", "-i", final_file, "-vn", "-ab", "192k", "-f", "mp3", new_mp3_path, "-y"]
                    subprocess.run(cmd, check=True)
                    
                    if os.path.exists(new_mp3_path):
                        os.remove(final_file)
                        final_file = new_mp3_path
                        final_filename = f"{base_name}.mp3"
                else:
                    print("❌ Conversion skipped because FFmpeg is missing!")
        
        # 2. FORCE MP4 CONTAINER
        elif format_type == "mp4":
            if not final_file.endswith(".mp4"):
                 print(f"⚠️ Remuxing to MP4...")
                 new_mp4_path = os.path.join(DOWNLOAD_DIR, f"{base_name}.mp4")
                 if shutil.which("ffmpeg"):
                     cmd = ["ffmpeg", "-i", final_file, "-c", "copy", new_mp4_path, "-y"]
                     subprocess.run(cmd, check=True)
                     if os.path.exists(new_mp4_path):
                        os.remove(final_file)
                        final_file = new_mp4_path
                        final_filename = f"{base_name}.mp4"

        return {"download_url": f"/files/{final_filename}", "filename": final_filename}

    except Exception as e:
        print(f"Critical Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
