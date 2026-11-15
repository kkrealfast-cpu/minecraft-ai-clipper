import os, re, uuid, json, time, shutil, subprocess, threading
from pathlib import Path
from typing import Dict, Any
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from pydantic import BaseModel, HttpUrl

ROOT = Path(__file__).parent.resolve()
WORK = ROOT / "jobs"
WORK.mkdir(exist_ok=True)
app = FastAPI(title="Minecraft AI Clipper")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
JOBS: Dict[str, Dict[str, Any]] = {}
LOCK = threading.Lock()

MAX_DURATION = int(os.getenv("MAX_VIDEO_SECONDS", "7200"))
CLIP_SECONDS = int(os.getenv("CLIP_SECONDS", "32"))
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "tiny")

class ClipRequest(BaseModel):
    url: HttpUrl

def run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout)[-3500:])
    return p.stdout

def set_job(job_id, **kwargs):
    with LOCK:
        JOBS.setdefault(job_id, {}).update(kwargs)

def seconds_to_srt(t):
    t = max(0, t)
    h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def choose_moments(segments, duration, clip_len=CLIP_SECONDS):
    cues = ["no way", "oh my", "let's go", "lets go", "what", "insane", "crazy", "bro", "help", "run", "dead", "kill", "clutch", "finally", "wait", "holy", "wow", " omg", "actually", "look", "elytra", "diamond", "netherite", "fight", "won", "lost", "bruh", "get out"]
    candidates = []
    for seg in segments:
        start = max(0, float(seg.start) - 8)
        end = min(float(duration), start + clip_len)
        if end - start < min(12, clip_len * .6):
            continue
        text = (seg.text or "").lower()
        words = re.findall(r"[a-z']+", text)
        cue_score = sum(2.8 for cue in cues if cue in text)
        excitement = sum(1.2 for w in words if w in {"insane","crazy","amazing","no","way","wait","bro","wow","finally","run","help"})
        punctuation = min(3, text.count("!") * .7 + text.count("?") * .35)
        density = min(3, len(words) / 18)
        candidates.append((cue_score + excitement + punctuation + density, start, end, text))
    if not candidates:
        starts = [max(0, min(duration - clip_len, duration * f)) for f in (.12, .36, .60, .82)]
        return [(s, min(duration, s + clip_len), "Highlight") for s in starts]
    candidates.sort(reverse=True, key=lambda x: x[0])
    chosen = []
    for score, start, end, text in candidates:
        if all(end <= old_s - 4 or start >= old_e + 4 for old_s, old_e, _ in chosen):
            chosen.append((start, end, text))
        if len(chosen) == 4: break
    if len(chosen) < 4:
        for frac in (.12, .36, .60, .82):
            s = max(0, min(duration - clip_len, duration * frac)); e = min(duration, s + clip_len)
            if all(e <= os_ - 4 or s >= oe + 4 for os_, oe, _ in chosen): chosen.append((s, e, "Highlight"))
            if len(chosen) == 4: break
    return sorted(chosen[:4], key=lambda x: x[0])

def make_srt(segments, start, end, path):
    rows = []; idx = 1
    for seg in segments:
        a, b = max(float(seg.start), start), min(float(seg.end), end)
        txt = re.sub(r"\s+", " ", (seg.text or "").strip())
        if b <= a or not txt: continue
        rows.append(f"{idx}\n{seconds_to_srt(a-start)} --> {seconds_to_srt(b-start)}\n{txt}\n"); idx += 1
    path.write_text("\n".join(rows), encoding="utf-8")

def process_job(job_id, url):
    folder = WORK / job_id; folder.mkdir(parents=True, exist_ok=True)
    try:
        set_job(job_id, status="processing", progress=5, message="Checking video…")
        info_json = run(["yt-dlp", "--no-warnings", "--dump-single-json", "--no-playlist", str(url)])
        info = json.loads(info_json); duration = float(info.get("duration") or 0)
        if duration <= 0 or duration > MAX_DURATION: raise RuntimeError(f"Video duration must be between 1 second and {MAX_DURATION//60} minutes.")
        set_job(job_id, progress=12, message="Getting video…", title=info.get("title", "Your video"))
        video = folder / "source.mp4"
        run(["yt-dlp", "--no-warnings", "--no-playlist", "-f", "bv*[height<=1080]+ba/b[height<=1080]", "--merge-output-format", "mp4", "-o", str(video), str(url)])
        if not video.exists():
            found = list(folder.glob("source.*"))
            if not found: raise RuntimeError("Could not download the video.")
            video = found[0]
        set_job(job_id, progress=48, message="Listening for the best moments…")
        from faster_whisper import WhisperModel
        model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        segments_iter, meta = model.transcribe(str(video), vad_filter=True); segments = list(segments_iter)
        if not segments: raise RuntimeError("I couldn't hear clear speech in this video. Try a video with spoken audio.")
        set_job(job_id, progress=68, message="Picking four highlight moments…")
        moments = choose_moments(segments, duration); output_clips = []
        for i, (start, end, label) in enumerate(moments, 1):
            set_job(job_id, progress=68 + i*7, message=f"Making clip {i} of 4…")
            srt = folder / f"captions_{i}.srt"; make_srt(segments, start, end, srt)
            out = folder / f"clip_{i}.mp4"; subpath = str(srt).replace("\\", "/").replace(":", r"\:")
            vf = f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,subtitles='{subpath}':force_style='FontName=Arial,FontSize=17,Outline=2,Shadow=1,Alignment=2,MarginV=115'"
            run(["ffmpeg", "-y", "-ss", str(start), "-i", str(video), "-t", str(end-start), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)])
            output_clips.append({"number": i, "filename": out.name, "start": round(start), "end": round(end)})
        set_job(job_id, status="done", progress=100, message="Your four clips are ready!", clips=output_clips)
    except Exception as e:
        set_job(job_id, status="error", progress=100, message=str(e)[:1000])
    finally:
        src = folder / "source.mp4"
        if src.exists():
            try: src.unlink()
            except OSError: pass

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/clip")
def create_clip(req: ClipRequest, background: BackgroundTasks):
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Queued…", "clips": []}
    background.add_task(process_job, job_id, str(req.url))
    return {"job_id": job_id}

@app.get("/api/status/{job_id}")
def status(job_id: str):
    if job_id not in JOBS: raise HTTPException(404, "Job not found")
    return JOBS[job_id]

@app.get("/download/{job_id}/{filename}")
def download(job_id: str, filename: str):
    if not re.fullmatch(r"clip_[1-4]\.mp4", filename): raise HTTPException(400, "Invalid filename")
    path = WORK / job_id / filename
    if not path.exists(): raise HTTPException(404, "Clip not ready")
    return FileResponse(path, media_type="video/mp4", filename=filename)
