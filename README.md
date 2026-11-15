# Minecraft AI Clipper

A browser-based starter app that accepts a YouTube URL, transcribes the video, selects four likely highlight moments, crops each to 9:16, burns in captions, and provides MP4 downloads.

## Important
- Only use videos you own or have permission to download, edit, and repost.
- YouTube's terms and creator permissions may restrict downloading or reusing videos. Credit alone is not permission.
- This app has no watermark and no paid AI API key, but it is **not free to host at unlimited scale**. Video download, transcription, storage, and FFmpeg use server resources.
- The highlight picker is a basic transcript-based heuristic, not a human editor. It may miss funny visual-only moments or choose a dull section.
- YouTube may block some videos due to age, region, login, or anti-bot restrictions.

## Run locally (Windows)
1. Install Python 3.11+.
2. Install FFmpeg and make sure `ffmpeg` is on PATH.
3. Open a terminal in this folder.
4. Run:
   ```bash
   py -m venv .venv
   .venv\\Scripts\\activate
   pip install -r requirements.txt
   uvicorn app:app --reload
   ```
5. Open http://127.0.0.1:8000

The first run downloads the Whisper `tiny` speech model. Processing is CPU-heavy and may take several minutes.

## Run with Docker
Install Docker Desktop, then:
```bash
docker build -t minecraft-clipper .
docker run --rm -p 8000:8000 -v "%cd%/jobs:/app/jobs" minecraft-clipper
```
Open http://localhost:8000

## Hosting online
Deploy the folder as a Docker web service on a host that supports long-running background processes, FFmpeg, and enough RAM/disk. Set a persistent disk for `/app/jobs`. A free web-hosting tier may sleep, time out, or lack enough CPU/RAM for transcription. Do not assume unlimited free hosting.

## Settings
- `WHISPER_MODEL=tiny` (default; fastest/least accurate). `base` or `small` can improve transcription but need more resources.
- `CLIP_SECONDS=32`
- `MAX_VIDEO_SECONDS=7200`

This is a starter project, not a production multi-user service. Before public deployment, add authentication, per-user quotas, job cleanup, rate limiting, storage limits, and a proper job queue.
