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
    return {"status": "ok", "message": "Kaneki Downloader (Playback Fixed)"}

@app.get("/formats")
def get_formats(url: str):
    if not url: raise HTTPException(status_code=400, detail="URL required")
    
    # 403 Error မတက်အောင် Android Client လေးတော့ ဟန်ဆောင်ထားလိုက်မယ်
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
            # Web မှာဖွင့်ဖို့ MP4 ဖြစ်မှရမယ်
            if f.get("ext") == "mp4" and f.get("vcodec") != "none":
                label = f"{f.get('height')}p"
                # H.264 (avc1) codec ဆိုရင် Web မှာ ပိုကောင်းကောင်းပွင့်တယ်
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

@app.get("/download")
def download(url: str, format_id: str):
    try:
        filename = f"{uuid.uuid4()}.mp4"
        out_path = os.path.join(DOWNLOAD_DIR, filename)
        
        opts = {
            "format": f"{format_id}+bestaudio/best",
            "outtmpl": out_path,
            "merge_output_format": "mp4",
            "quiet": True,
            "nocheckcertificate": True,
            "extractor_args": {"youtube": {"player_client": ["android"]}},
            
            # --- ဒီအပိုင်းက မင်းပြဿနာကို ဖြေရှင်းမယ့်ကောင် ---
            # Video Index ကို ရှေ့ဆုံးရွှေ့ပြီး Web မှာ Play လို့ရအောင်လုပ်ခြင်း
            "postprocessor_args": {
                "ffmpeg": ["-movflags", "faststart"]
            }
            # ---------------------------------------------
        }

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        return {
            "download_url": f"/files/{filename}",
            "filename": filename
        }

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/file/{filename}")
def get_file(filename: str):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    
    # Browser ကို Video ပါလို့ ပြောပြီး ပို့ပေးခြင်း
    return FileResponse(filepath, media_type="video/mp4", filename=filename)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
