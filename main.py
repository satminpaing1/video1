import os
import uuid
import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# --- အသစ်ဖြည့်ရမည့်အပိုင်း (Start) ---
import static_ffmpeg
static_ffmpeg.add_paths()  # ဒါက FFmpeg ကို Auto Download လုပ်ပြီး System Path ထဲထည့်ပေးပါလိမ့်မယ်
# --- အသစ်ဖြည့်ရမည့်အပိုင်း (End) ---

app = FastAPI()

# ကျန်တဲ့ ကုဒ်များအားလုံး အတူတူပါပဲ...
# CORS Setup
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
    return {"status": "ok", "message": "Kaneki Downloader (Static FFmpeg Enabled)"}

# ------------------------------------------------------------
# 1. VIDEO FORMATS CHECKER
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
                    "format_id": f"bestvideo[height={res}]+bestaudio/best[height={res}]",
                    "ext": "mp4",       
                    "vcodec": "h264",
                    "height": res,
                    "label": f"{res}p"
                })

        if not final_formats:
             final_formats.append({
                "format_id": "best[ext=mp4]",
                "ext": "mp4",
                "vcodec": "h264",
                "height": 360
            })

        return {"formats": final_formats}

    except Exception as e:
        print(f"Error analyzing: {e}")
        return {"formats": []}

# ------------------------------------------------------------
# 2. DOWNLOAD HANDLER
# ------------------------------------------------------------
@app.get("/download")
def download(url: str, format_id: str):
    if not url or not format_id:
        raise HTTPException(status_code=400, detail="Missing parameters")

    try:
        if "bestaudio" in format_id and "bestvideo" not in format_id:
             pass 
        
        uid = str(uuid.uuid4())[:8]
        out_tmpl = os.path.join(DOWNLOAD_DIR, f"kaneki_{uid}.%(ext)s")

        ydl_opts = {
            "format": format_id,
            "outtmpl": out_tmpl,
            "quiet": True,
            "noplaylist": True,
            "nocheckcertificate": True,
            "merge_output_format": "mp4",
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if filename.endswith(".mkv"):
                 pre, _ = os.path.splitext(filename)
                 if os.path.exists(pre + ".mp4"):
                     filename = pre + ".mp4"

        clean_filename = os.path.basename(filename)

        return {
            "download_url": f"/files/{clean_filename}",
            "filename": clean_filename
        }

    except Exception as e:
        print(f"DL Error: {e}")
        raise HTTPException(status_code=500, detail="Download Failed")
