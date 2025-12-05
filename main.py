import os
import uuid
import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI()
# main.py ထဲမှာ ထည့်ရန်
import shutil

# FFmpeg ရှိမရှိ စစ်ဆေးခြင်း
if not shutil.which("ffmpeg"):
    print("CRITICAL ERROR: FFmpeg not found in path!")

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
    return {"status": "ok", "message": "Kaneki Downloader (Selector Enabled)"}

# ------------------------------------------------------------
# 1. VIDEO FORMATS CHECKER (SMART SELECTOR)
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
        
        # ဗီဒီယိုမှာ တကယ်ရှိတဲ့ Resolution တွေကို ရှာမယ်
        raw_formats = info.get('formats', [])
        available_heights = set()

        for f in raw_formats:
            # Video ဖြစ်ပြီး Height ပါတဲ့အရာတွေကို မှတ်ထားမယ်
            if f.get('vcodec') != 'none' and f.get('height'):
                available_heights.add(f['height'])

        final_formats = []
        
        # User လိုချင်တဲ့ Resolution တွေကို အစဉ်လိုက် စစ်မယ် (1080p ကနေ အငယ်ဆုံးထိ)
        # 2160(4K), 1440(2K), 1080, 720, 480, 360
        target_resolutions = [2160, 1440, 1080, 720, 480, 360]
        
        for res in target_resolutions:
            if res in available_heights:
                # တွေ့ရင် Frontend ကို ပို့မယ်
                # format_id မှာ 'height={res}' လို့ သုံးထားတာကြောင့် အတိအကျပဲ ဒေါင်းပါလိမ့်မယ်
                final_formats.append({
                    # Backend က နားလည်မယ့် Code (အတိအကျယူရန်)
                    "format_id": f"bestvideo[height={res}]+bestaudio/best[height={res}]",
                    
                    # Frontend UI က နားလည်ဖို့အတွက် Fake Data (UI မပျက်အောင်)
                    "ext": "mp4",       
                    "vcodec": "h264",
                    "height": res,
                    "label": f"{res}p"
                })

        # အကယ်၍ ဘာမှမတွေ့ခဲ့ရင် (ဥပမာ - Audio only or strange format)
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
        # Audio Only (MP3/M4A) Frontend ကပို့တဲ့ကုဒ်
        if "bestaudio" in format_id and "bestvideo" not in format_id:
             # Audio သီးသန့်
             pass 
        
        # Video ဆိုရင် MP4 ပြောင်းပေးဖို့ Setting ချမယ်
        uid = str(uuid.uuid4())[:8]
        out_tmpl = os.path.join(DOWNLOAD_DIR, f"kaneki_{uid}.%(ext)s")

        ydl_opts = {
            "format": format_id, # Frontend ကရွေးလိုက်တဲ့ အတိအကျ format (e.g. height=1080)
            "outtmpl": out_tmpl,
            "quiet": True,
            "noplaylist": True,
            "nocheckcertificate": True,
            "merge_output_format": "mp4", # အသံနဲ့ရုပ် ပေါင်းပြီး MP4 ထုတ်ပေးမယ်
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # .mkv နဲ့ထွက်လာရင် .mp4 လို့ နာမည်ပြန်ချိန်းပေးမယ် (User အဆင်ပြေအောင်)
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
