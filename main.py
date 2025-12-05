import os
import uuid
import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# FFmpeg Auto-Setup (Server ပေါ်ရောက်ရင် အလိုအလျောက် install လုပ်ဖို့)
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

# Frontend မှာသုံးထားတဲ့ Audio Only Format String
SPECIAL_AUDIO_FORMAT = "bestaudio[ext=m4a]/bestaudio"

@app.get("/")
def root():
    return {"status": "ok", "message": "Kaneki Downloader (Fixed Categories)"}

# ------------------------------------------------------------
# 1. SMART FORMATS (CLEAN IDs)
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
                # ဒီနေရာမှာ format_id ကို "v-1080" လိုမျိုး ရိုးရိုးလေးပေးလိုက်မယ်
                # ဒါမှ Frontend က "audio" လို့ မထင်တော့ဘဲ Video လို့ သိမှာ
                final_formats.append({
                    "format_id": f"v-{res}", 
                    "ext": "mp4",       
                    "vcodec": "h264",
                    "height": res,
                    "label": f"{res}p"
                })

        # Fallback if empty
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
# 2. DOWNLOAD HANDLER (MAPPING BACK)
# ------------------------------------------------------------
@app.get("/download")
def download(url: str, format_id: str):
    if not url or not format_id:
        raise HTTPException(status_code=400, detail="Missing parameters")

    try:
        real_format_string = ""

        # Frontend ကပို့လိုက်တဲ့ v-1080, v-720 ကို yt-dlp နားလည်တဲ့ကုဒ်ပြန်ပြောင်းမယ်
        if format_id.startswith("v-"):
            # Video Request
            height = format_id.split("-")[1] # 1080, 720, etc.
            real_format_string = f"bestvideo[height={height}]+bestaudio/best[height={height}]"
        
        elif format_id == SPECIAL_AUDIO_FORMAT or "bestaudio" in format_id:
            # Audio Request
            real_format_string = SPECIAL_AUDIO_FORMAT
        
        else:
            # Fallback
            real_format_string = "best[ext=mp4]"

        # Filename Generation
        uid = str(uuid.uuid4())[:8]
        out_tmpl = os.path.join(DOWNLOAD_DIR, f"kaneki_{uid}.%(ext)s")

        ydl_opts = {
            "format": real_format_string,
            "outtmpl": out_tmpl,
            "quiet": True,
            "noplaylist": True,
            "nocheckcertificate": True,
            # Audio သက်သက်မဟုတ်ရင် Merge လုပ်မယ်
            "merge_output_format": "mp4" if "bestvideo" in real_format_string else None,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Extension cleanup (.mkv -> .mp4 if merged)
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
