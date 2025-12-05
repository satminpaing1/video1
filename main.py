import os
import uuid
import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# FFmpeg Auto-Setup
import static_ffmpeg
static_ffmpeg.add_paths()

app = FastAPI()

# CORS
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

# Audio Only Format String
SPECIAL_AUDIO_FORMAT = "bestaudio[ext=m4a]/bestaudio"

@app.get("/")
def root():
    return {"status": "ok", "message": "Kaneki Downloader (Turbo Mode)"}

# ------------------------------------------------------------
# 1. SMART FORMATS
# ------------------------------------------------------------
@app.get("/formats")
def get_formats(url: str):
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    ydl_opts = {
        "quiet": True,
        "noplaylist": True,
        "skip_download": True,
        "nocheckcertificate": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        raw_formats = info.get('formats', [])
        available_heights = set()

        for f in raw_formats:
            if f.get('vcodec') != 'none' and f.get('height'):
                available_heights.add(f['height'])

        final_formats = []
        target_resolutions = [2160, 1440, 1080, 720, 480, 360]
        
        for res in target_resolutions:
            if res in available_heights:
                final_formats.append({
                    "format_id": f"v-{res}", 
                    "ext": "mp4",       
                    "vcodec": "h264",
                    "height": res,
                    "label": f"{res}p"
                })

        if not final_formats:
             final_formats.append({
                "format_id": "v-360",
                "ext": "mp4",
                "vcodec": "h264",
                "height": 360
            })

        return {"formats": final_formats}

    except Exception as e:
        print(f"Error analyzing: {e}")
        return {"formats": []}


# ------------------------------------------------------------
# 2. DOWNLOAD HANDLER (TURBO SPEED)
# ------------------------------------------------------------
@app.get("/download")
def download(url: str, format_id: str):
    if not url or not format_id:
        raise HTTPException(status_code=400, detail="Missing parameters")

    try:
        uid = str(uuid.uuid4())[:8]
        out_tmpl = os.path.join(DOWNLOAD_DIR, f"kaneki_{uid}.%(ext)s")
        
        # --- SPEED OPTIMIZATION SETTINGS ---
        ydl_opts = {
            "outtmpl": out_tmpl,
            "quiet": True,
            "noplaylist": True,
            "nocheckcertificate": True,
            
            # --- ဒီအပိုင်းက အမြန်နှုန်းကို တင်ပေးမယ့်အရာများ ---
            "concurrent_fragment_downloads": 5,  # တစ်ပြိုင်နက် ၅ ပိုင်းခွဲဆွဲမယ်
            "http_chunk_size": 10485760,         # Chunk size 10MB ထားမယ်
            "retries": 10,                       # လိုင်းကျရင် ၁၀ ခါပြန်စမ်းမယ်
            "fragment_retries": 10,
            "buffersize": 1024,
            # ----------------------------------------------
        }

        # --- VIDEO REQUEST ---
        if format_id.startswith("v-"):
            height = format_id.split("-")[1]
            ydl_opts["format"] = f"bestvideo[height={height}]+bestaudio/best[height={height}]"
            ydl_opts["merge_output_format"] = "mp4"

        # --- AUDIO REQUEST ---
        elif format_id == SPECIAL_AUDIO_FORMAT or "bestaudio" in format_id:
            ydl_opts["format"] = "bestaudio/best"
            ydl_opts["postprocessors"] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128', 
            }]
            # Audio Convert လုပ်တာမြန်အောင် Quality နည်းနည်းလျှော့ပြီး Speed တင်မယ်
            ydl_opts["postprocessor_args"] = [
                '-speed', '0' # Fastest encoding speed
            ]
        
        else:
            ydl_opts["format"] = "best[ext=mp4]"


        # Execute Download
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Extension Fix
            if format_id.startswith("v-") and filename.endswith(".mkv"):
                 pre, _ = os.path.splitext(filename)
                 if os.path.exists(pre + ".mp4"):
                     filename = pre + ".mp4"
            
            if "bestaudio" in format_id or format_id == SPECIAL_AUDIO_FORMAT:
                pre, _ = os.path.splitext(filename)
                if os.path.exists(pre + ".mp3"):
                    filename = pre + ".mp3"

        clean_filename = os.path.basename(filename)

        return {
            "download_url": f"/files/{clean_filename}",
            "filename": clean_filename
        }

    except Exception as e:
        print(f"DL Error: {e}")
        raise HTTPException(status_code=500, detail="Download Failed")
