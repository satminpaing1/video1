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
# Clear downloads folder on start to save space
if os.path.exists(DOWNLOAD_DIR):
    shutil.rmtree(DOWNLOAD_DIR)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app.mount("/files", StaticFiles(directory=DOWNLOAD_DIR), name="files")

# FFmpeg Check
def check_ffmpeg():
    if not shutil.which("ffmpeg"):
        print("CRITICAL WARNING: FFmpeg not found! 1080p and MP3 will fail.")
    else:
        print("FFmpeg found system-wide.")

check_ffmpeg()

@app.get("/")
def root():
    return {"status": "ok", "message": "Kaneki V2.4 (FFmpeg Fixed)"}

@app.get("/formats")
def get_formats(url: str = Query(..., description="Video URL")):
    if not url:
        raise HTTPException(status_code=400, detail="URL required")

    # Use 'ios' client to see high quality formats on server IPs
    opts = {
        "quiet": True,
        "skip_download": True,
        "nocheckcertificate": True,
        "extractor_args": {"youtube": {"player_client": ["ios"]}},
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
            
            # Filter Video Formats (mp4 only for better compatibility)
            if vcodec and vcodec != "none" and height:
                # Deduplicate by height (show only the best option per resolution)
                if height not in seen_qualities and ext == 'mp4':
                    seen_qualities.add(height)
                    label = f"{height}p"
                    if f.get("fps") and f.get("fps") > 30:
                        label += f" {int(f.get('fps'))}fps"
                    
                    formats.append({
                        "format_id": f.get("format_id"),
                        "label": f"🎬 Video {label} (MP4)",
                        "height": height,
                        "ext": ext,
                        "type": "video"
                    })

        # Sort: High to Low
        formats.sort(key=lambda x: (x["height"] or 0), reverse=True)
        
        # Audio Option
        formats.insert(0, {
            "format_id": "bestaudio",
            "label": "🎵 MP3 Music (Best Quality)",
            "height": 0,
            "ext": "mp3",
            "type": "audio"
        })

        return {"formats": formats}

    except Exception as e:
        print(f"Format Error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get formats")


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
        # IMPORTANT: mimic iOS to avoid 360p throttle on servers
        "extractor_args": {"youtube": {"player_client": ["ios"]}}, 
        "prefer_ffmpeg": True,
        "socket_timeout": 30,
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
            # If user selected a specific quality (e.g. 137 for 1080p), 
            # we MUST merge it with bestaudio.
            if format_id and format_id != "bestaudio":
                ydl_opts.update({
                    "format": f"{format_id}+bestaudio/best", # Merge Video+Audio
                    "merge_output_format": "mp4",
                })
            else:
                # Auto best quality
                ydl_opts.update({
                    "format": "bestvideo+bestaudio/best",
                    "merge_output_format": "mp4",
                })
            
            # Ensure faststart for web streaming
            ydl_opts.update({"postprocessor_args": ["-movflags", "+faststart"]})

        # --- EXECUTE DOWNLOAD ---
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # --- FIND THE FILE ---
        # yt-dlp might output .mp3, .mp4, .mkv, or .webm depending on merge
        possible_files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{base_name}.*"))
        
        if not possible_files:
            raise HTTPException(status_code=500, detail="Download failed (File creation error)")

        final_file = possible_files[0]
        
        # Double check: if MP3 requested but got m4a/webm, force convert (fallback)
        if format_type == "mp3" and not final_file.endswith(".mp3"):
            new_file = os.path.join(DOWNLOAD_DIR, f"{base_name}.mp3")
            os.system(f"ffmpeg -i {final_file} -vn -ab 192k {new_file} -y")
            if os.path.exists(new_file):
                final_file = new_file

        filename = os.path.basename(final_file)
        return {"download_url": f"/files/{filename}", "filename": filename}

    except Exception as e:
        print(f"Download Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
