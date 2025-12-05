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
    return {"status": "ok"}

@app.get("/download")
def download(url: str, type: str = "mp4", quality: int = 720):

    file_id = str(uuid.uuid4())
    output = os.path.join(DOWNLOAD_DIR, file_id + ".%(ext)s")

    if type == "mp3":
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "extractor_args": {"youtube": {"player_client": ["android"]}},
        }

    else:  # mp4
        ydl_opts = {
            "format": f"bestvideo[height<={quality}]+bestaudio/best",
            "merge_output_format": "mp4",
            "outtmpl": output,
            "postprocessor_args": ["-movflags", "+faststart"],
            "extractor_args": {"youtube": {"player_client": ["android"]}},
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.download([url])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # detect generated file
    for ext in ["mp4", "mp3", "m4a", "webm"]:
        path = os.path.join(DOWNLOAD_DIR, file_id + "." + ext)
        if os.path.exists(path):
            return {"download_url": f"/files/{file_id}.{ext}"}

    raise HTTPException(status_code=500, detail="File not generated")

@app.get("/files/{filename}")
def serve_file(filename: str):
    path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Not found")

    mime = "video/mp4"
    if filename.endswith(".mp3"):
        mime = "audio/mpeg"

    return FileResponse(path, media_type=mime, filename=filename)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
