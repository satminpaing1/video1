from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import yt_dlp
import os
import uuid
import uvicorn

app = FastAPI()

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
    return {"status": "ok", "message": "Kaneki Downloader (Restored + MP3 Fix)"}

# ------------------------------------------------------------
#  FORMATS (ဒီအပိုင်းက မင်းအဆင်ပြေခဲ့တဲ့ Code အတိုင်းပါပဲ)
# ------------------------------------------------------------
@app.get("/formats")
def get_formats(url: str):
    if not url: raise HTTPException(status_code=400, detail="URL required")
    
    # မူလ အဆင်ပြေခဲ့တဲ့ Android Setting
    opts = {
        "quiet": True,
        "skip_download": True,
        "nocheckcertificate": True,
        "extractor_args": {"youtube": {"player_client": ["android"]}}, 
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        for f in info.get("formats", []):
            if f.get("ext") == "mp4" and f.get("vcodec") != "none":
                label = f"{f.get('height')}p"
                if "avc1" in (f.get("vcodec") or ""):
                    label += " (Web Safe)"
                formats.append({
                    "format_id": f.get("format_id"),
                    "label": label,
                    "height": f.get("height")
                })

        formats.sort(key=lambda x: x["height"] or 0, reverse=True)
        return {"formats": formats}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ------------------------------------------------------------
#  DOWNLOAD (Logic ခွဲထုတ်လိုက်သော နေရာ)
# ------------------------------------------------------------
@app.get("/download")
def download(url: str, format_id: str):
    try:
        unique_id = str(uuid.uuid4())
        
        # Audio ဟုတ်မဟုတ် စစ်မယ်
        is_audio = "audio" in format_id or "bestaudio" in format_id

        # Common Options (အခြေခံ setting)
        opts = {
            "quiet": True,
            "nocheckcertificate": True,
            "extractor_args": {"youtube": {"player_client": ["android"]}},
        }

        if is_audio:
            # === MP3 အတွက် သီးသန့် (File Size သေးသွားအောင်) ===
            filename = f"{unique_id}.mp3"
            # Extension မပါတဲ့ Path ကိုပေးရမယ် (FFmpeg က .mp3 ကို သူ့ဘာသာထည့်မယ်)
            out_path_base = os.path.join(DOWNLOAD_DIR, unique_id)
            
            opts.update({
                "format": "bestaudio/best",
                "outtmpl": out_path_base, 
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128", # 128k quality (Standard)
                }],
            })
            
        else:
            # === Video အတွက် သီးသန့် (Web Playback ရအောင်) ===
            filename = f"{unique_id}.mp4"
            out_path = os.path.join(DOWNLOAD_DIR, filename)
            
            opts.update({
                "format": f"{format_id}+bestaudio/best",
                "outtmpl": out_path,
                "merge_output_format": "mp4",
                # Web မှာ Play လို့ရတဲ့ FastStart ကုဒ် (ဒါက အရင်က အလုပ်လုပ်ခဲ့တဲ့ကောင်)
                "postprocessor_args": {"ffmpeg": ["-movflags", "faststart"]},
            })

        # Download စဆွဲမယ်
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        return {
            "download_url": f"/files/{filename}",
            "filename": filename
        }

    except Exception as e:
        print(f"Download Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/file/{filename}")
def get_file(filename: str):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    
    # Browser သိအောင် Type ခွဲပေးမယ်
    media_type = "audio/mpeg" if filename.endswith(".mp3") else "video/mp4"
    return FileResponse(filepath, media_type=media_type, filename=filename)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
