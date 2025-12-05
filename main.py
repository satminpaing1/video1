import os
import uuid
import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

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

# Special format for pure Audio
SPECIAL_AUDIO_FORMAT = "bestaudio[ext=m4a]/bestaudio"

@app.get("/")
def root():
    return {"status": "ok", "message": "Kaneki Downloader V2.2 (High Quality Enabled)"}

# ------------------------------------------------------------
# 1. GET FORMATS (SMART ANALYSIS)
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
        
        # ရှိသမျှ Formats တွေကို စစ်မယ်
        raw_formats = info.get('formats', [])
        available_heights = set()

        for f in raw_formats:
            # Video ဖြစ်ပြီး Height ပါတဲ့အရာတွေကို မှတ်ထားမယ်
            if f.get('vcodec') != 'none' and f.get('height'):
                available_heights.add(f['height'])

        # Frontend ကို ပြန်ပို့ပေးမယ့် စာရင်း (UI မပျက်အောင် ဖန်တီးခြင်း)
        final_formats = []
        
        # Quality အလိုက် Format ID တွေကို Construct လုပ်မယ် (Merge လုပ်ဖို့အတွက်)
        # 1080p, 720p, 480p, 360p စသည်ဖြင့် စစ်မယ်
        target_resolutions = [1080, 720, 480, 360]
        
        for res in target_resolutions:
            if res in available_heights or (res == 360): # 360 ကတော့ အမြဲထည့်ထားမယ်
                # Frontend ရဲ့ JS logic က (f.ext === 'mp4' && f.vcodec !== 'none') ကို စစ်ထားလို့
                # Backend ကနေ Fake Data လေး ထည့်ပေးလိုက်မယ်၊ ဒါပေမယ့် format_id က အစစ်
                final_formats.append({
                    "format_id": f"bestvideo[height<={res}][ext=mp4]+bestaudio[ext=m4a]/best[height<={res}]",
                    "ext": "mp4",       # Frontend check အတွက်
                    "vcodec": "h264",   # Frontend check အတွက်
                    "height": res,
                    "label": f"{res}p"
                })

        return {"formats": final_formats}

    except Exception as e:
        print(f"Error: {e}")
        # Error ဖြစ်ရင် အနည်းဆုံး Auto တစ်ခုပြန်ပေးမယ်
        return {"formats": [{
            "format_id": "best[ext=mp4]", 
            "ext": "mp4", 
            "vcodec": "h264", 
            "height": 720
        }]}

# ------------------------------------------------------------
# 2. DOWNLOAD HANDLER (AUTO MERGE)
# ------------------------------------------------------------
@app.get("/download")
def download(url: str, format_id: str):
    if not url or not format_id:
        raise HTTPException(status_code=400, detail="Missing parameters")

    try:
        # File name setting
        uid = str(uuid.uuid4())[:8]
        out_tmpl = os.path.join(DOWNLOAD_DIR, f"kaneki_{uid}.%(ext)s")

        ydl_opts = {
            "outtmpl": out_tmpl,
            "quiet": True,
            "noplaylist": True,
            "nocheckcertificate": True,
            # FFmpeg location (Nixpacks မှာထည့်ထားပြီးသားမို့လို့ Path မလိုပါ)
            "merge_output_format": "mp4", # Video ဆိုရင် အမြဲတမ်း MP4 ပြောင်းမယ်
        }

        # Audio Only Request
        if "bestaudio" in format_id and "bestvideo" not in format_id:
            ydl_opts["format"] = format_id
        else:
            # Video Request (1080p, 720p etc.)
            ydl_opts["format"] = format_id
            # 1080p ဆိုရင် Audio သက်သက် Video သက်သက်လာမှာမို့လို့ ပေါင်းပေးရမယ်

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # yt-dlp က တစ်ခါတစ်လေ .mkv နဲ့ သိမ်းတတ်လို့ .mp4 ဖြစ်အောင် rename စစ်မယ်
            if "merge_output_format" in ydl_opts and filename.endswith(".mkv"):
                 pre, _ = os.path.splitext(filename)
                 if os.path.exists(pre + ".mp4"):
                     filename = pre + ".mp4"

        # Path အပြည့်အစုံမဟုတ်ဘဲ Filename ပဲ ပြန်ပို့မယ်
        clean_filename = os.path.basename(filename)

        return {
            "download_url": f"/files/{clean_filename}",
            "filename": clean_filename
        }

    except Exception as e:
        print(f"Download Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
