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
# Startup: Clean old downloads
if os.path.exists(DOWNLOAD_DIR):
    try:
        shutil.rmtree(DOWNLOAD_DIR)
    except:
        pass
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app.mount("/files", StaticFiles(directory=DOWNLOAD_DIR), name="files")

# FFmpeg Check
def check_ffmpeg():
    if not shutil.which("ffmpeg"):
        print("WARNING: FFmpeg not found! Merging video/audio might fail.")
    else:
        print("FFmpeg found.")

check_ffmpeg()

@app.get("/")
def root():
    return {"status": "ok", "message": "Kaneki V2.5 (Stable Android)"}

@app.get("/formats")
def get_formats(url: str = Query(..., description="Video URL")):
    if not url:
        raise HTTPException(status_code=400, detail="URL required")

    # Use 'android' client which is more stable than iOS currently
    opts = {
        "quiet": True,
        "skip_download": True,
        "nocheckcertificate": True,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}}, # Fallback allowed
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
                # Deduplicate by height
                if height not in seen_qualities and ext in ['mp4', 'webm']:
                    seen_qualities.add(height)
                    label = f"{height}p"
                    if f.get("fps") and f.get("fps") > 30:
                        label += f" {int(f.get('fps'))}fps"
                    
                    formats.append({
                        "format_id": f.get("format_id"),
                        "label": f"🎬 Video {label} ({ext})",
                        "height": height,
                        "ext": ext,
                        "type": "video"
                    })

        # Sort: High to Low
        formats.sort(key=lambda x: (x["height"] or 0), reverse=True)
        
        # Add Audio Option
        formats.insert(0, {
            "format_id": "bestaudio",
            "label": "🎵 MP3 Music (Best Quality)",
            "height": 0,
            "ext": "mp3",
            "type": "audio"
        })

        if not formats:
             raise Exception("No compatible formats found")

        return {"formats": formats}

    except Exception as e:
        print(f"Format Error: {str(e)}")
        # Return a simplified error to frontend so it doesn't just crash
        raise HTTPException(status_code=500, detail="Could not analyze video. Try another link.")


@app.get("/download")
def download(
    url: str = Query(..., description="Video URL"),
    format_id: str = Query(None, description="Format ID"),
    format_type: str = Query("mp4", description="mp3 or mp4")
):
    if not url:
        raise HTTPException(status_code=400, detail="URL required")

    base_name = str(uuid.uuid4())
    
    # Base Options
    ydl_opts = {
        "quiet": True,
        "nocheckcertificate": True,
        "outtmpl": os.path.join(DOWNLOAD_DIR, f"{base_name}.%(ext)s"),
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        "prefer_ffmpeg": True,
        "socket_timeout": 30,
        # Improve reliability
        "retries": 3,
        "fragment_retries": 3,
    }

    try:
        if format_type == "mp3":
            # --- MP3 DOWNLOAD MODE ---
            ydl_opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        else:
            # --- VIDEO DOWNLOAD MODE ---
            # If user selected a specific quality
            if format_id and format_id != "bestaudio":
                # Check if it's a combined format (contains +) or single
                if "+" in str(format_id):
                    chosen_format = str(format_id)
                else:
                    chosen_format = f"{format_id}+bestaudio/best"
                
                ydl_opts.update({
                    "format": chosen_format,
                    "merge_output_format": "mp4",
                })
            else:
                # Auto fallback - looser restriction to prevent "format not available"
                ydl_opts.update({
                    "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "merge_output_format": "mp4",
                })
            
            ydl_opts.update({"postprocessor_args": ["-movflags", "+faststart"]})

        # --- EXECUTE DOWNLOAD ---
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                ydl.download([url])
            except yt_dlp.utils.DownloadError as de:
                # Fallback mechanism if specific format fails
                print(f"First attempt failed: {de}. Retrying with 'best'...")
                ydl_opts["format"] = "best"
                with yt_dlp.YoutubeDL(ydl_opts) as ydl_fallback:
                    ydl_fallback.download([url])

        # --- FIND THE FILE ---
        possible_files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{base_name}.*"))
        
        if not possible_files:
            raise HTTPException(status_code=500, detail="Download failed (File creation error)")

        final_file = possible_files[0]
        
        # Audio conversion safeguard
        if format_type == "mp3" and not final_file.endswith(".mp3"):
            new_file = os.path.join(DOWNLOAD_DIR, f"{base_name}.mp3")
            if shutil.which("ffmpeg"):
                os.system(f"ffmpeg -i {final_file} -vn -ab 192k {new_file} -y")
                if os.path.exists(new_file):
                    final_file = new_file

        filename = os.path.basename(final_file)
        return {"download_url": f"/files/{filename}", "filename": filename}

    except Exception as e:
        print(f"Download Critical Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
