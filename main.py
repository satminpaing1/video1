from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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
if os.path.exists(DOWNLOAD_DIR):
    shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app.mount("/files", StaticFiles(directory=DOWNLOAD_DIR), name="files")

# --- SYSTEM DIAGNOSTIC ---
print("--- BOOT CHECK ---")
if shutil.which("ffmpeg"):
    print("✅ SYSTEM: FFmpeg is installed! MP3 conversion will work.")
else:
    print("❌ SYSTEM: FFmpeg is MISSING! Check Dockerfile.")
print("--------------------")

@app.get("/")
def root():
    return {"status": "ok", "message": "Kaneki V4.0 (Docker + FFmpeg)"}

@app.get("/formats")
def get_formats(url: str = Query(..., description="Video URL")):
    # Use 'web' client to stop the PO Token crashes
    opts = {
        "quiet": True,
        "skip_download": True,
        "extractor_args": {"youtube": {"player_client": ["web"]}},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        formats = []
        seen = set()
        for f in info.get("formats", []):
            if f.get("vcodec") != "none" and f.get("height"):
                h = f["height"]
                ext = f["ext"]
                if h not in seen and ext in ['mp4', 'webm']:
                    seen.add(h)
                    formats.append({
                        "format_id": f["format_id"],
                        "label": f"🎬 Video {h}p ({ext})",
                        "height": h,
                        "type": "video"
                    })
        
        formats.sort(key=lambda x: x["height"], reverse=True)
        formats.insert(0, {"format_id": "bestaudio", "label": "🎵 MP3 Music (Best Quality)", "type": "audio"})
        return {"formats": formats}
    except Exception as e:
        print(f"Format Error: {e}")
        raise HTTPException(status_code=500, detail="Could not analyze video.")

@app.get("/download")
def download(url: str, format_type: str = "mp4", format_id: str = None):
    base_name = str(uuid.uuid4())
    
    # Configuration
    ydl_opts = {
        "quiet": True,
        "outtmpl": os.path.join(DOWNLOAD_DIR, f"{base_name}.%(ext)s"),
        "extractor_args": {"youtube": {"player_client": ["web"]}}, # Fixes the crash
        "prefer_ffmpeg": True,
    }

    try:
        if format_type == "mp3":
            ydl_opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        else:
            # Video Mode
            if format_id and format_id != "bestaudio":
                 ydl_opts["format"] = f"{format_id}+bestaudio/best"
            else:
                 ydl_opts["format"] = "bestvideo+bestaudio/best"
            ydl_opts["merge_output_format"] = "mp4"

        # Download
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Verify File
        files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{base_name}.*"))
        if not files: raise Exception("Download failed.")
        
        final_file = files[0]
        final_filename = os.path.basename(final_file)

        # Force MP3 Check
        if format_type == "mp3" and not final_file.endswith(".mp3"):
            print("⚠️ Force converting to MP3...")
            new_path = os.path.join(DOWNLOAD_DIR, f"{base_name}.mp3")
            subprocess.run(["ffmpeg", "-i", final_file, "-vn", "-ab", "192k", new_path, "-y"], check=True)
            final_file = new_path
            final_filename = f"{base_name}.mp3"

        return {"download_url": f"/files/{final_filename}", "filename": final_filename}

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
