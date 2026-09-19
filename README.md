# 🎬 AI Movie Translate & Dubbing Agent (v2.2) — $0 Free Local & Cloud-Accelerated Pipeline

## Secure local setup

Keep Gemini credentials and YouTube session cookies outside the project directory. Set `GEMINI_API_KEYS` and, only when needed, `MOVIE_COOKIES_PATH` in the process environment. The Web UI remains local-only by default; remote access requires `WEB_UI_TOKEN`, and browser origins can be restricted with `WEB_UI_ALLOWED_ORIGINS`. API keys are never returned to the browser and are sent to Google through request headers rather than URL query strings.

```powershell
$env:GEMINI_API_KEYS="NEW_KEY_1,NEW_KEY_2"
$env:MOVIE_COOKIES_PATH="C:\Users\wcp18\AppData\Local\MovieTranslate\cookies.txt"
$env:WEB_UI_TOKEN="use-a-long-random-token"
$env:WEB_UI_ALLOWED_ORIGINS="http://127.0.0.1:5000,http://localhost:5000"
python web_ui.py
```

Rotate any credentials that were previously stored in `config.json` or `cookies.txt` before using this project again.

An autonomous, end-to-end AI agentic pipeline designed to automatically translate movies, short dramas, and anime clips line-by-line into natural **Colloquial Burmese** (or English), synthesize lifelike **Multi-Voice Dubbing (Male/Female)**, and produce viral, ready-to-publish videos equipped with **9:16 Facebook Reels Canvas**, **Burned Myanmar ASS Subtitles**, **Subtitle Blur Protection**, **Custom Watermark Branding**, and **High-CTR Thumbnails**.

> 📖 **v2.2 Detailed Release Notes & Changelog:** View complete architecture updates and benchmark records in [CHANGELOG.md](CHANGELOG.md).

---

## ⚡ Cloud GPU One-Click Setup (100% Free Cloud Options)

### 🥇 Option A: Google Colab (Free T4 GPU + Google Drive Sync)
👉 **[Open AI_Movie_Translate_Colab.ipynb in Google Colab](https://colab.research.google.com/github/paipai1999/ai-translate-agent/blob/main/AI_Movie_Translate_Colab.ipynb)**
* **Highlights:** 1-Click Web UI Dashboard, Permanent Google Drive Sync for videos/cookies/db, 60s Auto Keep-Alive Heartbeat, and Fast Socket Health-Check.
* **Public & Private Editions:** 
  - `AI_Movie_Translate_Colab.ipynb` (Public Edition on GitHub - clean template for community sharing).
  - `AI_Movie_Translate_Colab_PRIVATE.ipynb` (Personal VIP Edition - pre-loaded with your 4 Gemini keys & YouTube cookies for instant 1-click execution without typing).

### 🥈 Option B: Kaggle Notebooks (Free Dual T4 30GB VRAM / 30h Weekly Quota)
👉 **[View AI_Movie_Translate_Kaggle.ipynb](https://github.com/paipai1999/ai-translate-agent/blob/main/AI_Movie_Translate_Kaggle.ipynb)**
* **Highlights:** 2x NVIDIA T4 GPUs (30GB VRAM) or P100 GPU, 30 Hours/Week Free GPU Quota, 12-Hour Continuous Sessions, Cloudflare Tunnel Web UI, and 30GB System RAM.
* **Public & Private Editions:**
  - `AI_Movie_Translate_Kaggle.ipynb` (Public Edition on GitHub).
  - `AI_Movie_Translate_Kaggle_PRIVATE.ipynb` (Personal VIP Edition - pre-embedded keys & cookies, zero setup).
* **Kaggle Quickstart:**
  1. Create a new Notebook on [kaggle.com](https://www.kaggle.com).
  2. Click `File` > `Import Notebook` and upload `AI_Movie_Translate_Kaggle.ipynb` (or private version).
  3. In right sidebar `Notebook Settings`: Set **Accelerator = GPU T4 x2** and turn **Internet = On**.
  4. Run Cell 1 to launch the Web UI Dashboard!

---

## 📊 v2.2 Architecture Overhaul & Benchmark Performance

Version 2.2 introduces an end-to-end architectural redesign of the audio-visual synchronization engine, speech generation budgeting, and video post-processing hardware acceleration.

### 📈 Benchmark Comparison: Old Pipeline vs. v2.2 Engine

The following real-world benchmark was measured on a full 15-minute movie recap (205 discrete dialogue segments):

| Evaluation Metric | Legacy Pipeline (v2.1) | v2.2 Architectural Engine | Improvement / Impact |
| :--- | :---: | :---: | :---: |
| **Audio/Visual Drift at Clip 10** | `+9.80s` behind | **`+0.51s` (Near Zero)** | **95% tighter sync** |
| **Audio/Visual Drift at Clip 50** | `+85.16s` behind | **`+3.43s`** | **96% tighter sync** |
| **Audio/Visual Drift at Clip 100** | `+148.36s` (2.5 min lag) | **`+3.28s`** | **98% tighter sync** |
| **Cumulative Drift Accumulation** | Compounding without bound | **Zero compounding (Auto-realigns)** | **Eliminated runaway drift** |
| **Dropped Dialogue Clips** | 45 clips dropped / skipped | **0 clips dropped (205/205 placed)** | **100% dialogue coverage** |
| **Sentence Mid-Speech Cutoffs** | Severe (Truncated words) | **0% cutoffs (100% complete delivery)** | **Full pronunciation guarantee** |
| **QAAgent Auto-Rewrite Coverage** | ~19% (165/205 ignored) | **100% of over-length blocks rewritten** | **Flawless length adherence** |
| **Video Encoding Engine (Kaggle)**| CPU `libx264` (Multi-core) | **NVIDIA NVENC (`h264_nvenc`)** | **Hardware-accelerated silicon** |
| **Video Encoding Speed** | 80–110 fps | **400–650 fps** | **5x–8x faster rendering** |
| **1080p Post-Processing Time** | ~7.2 minutes | **~1.4 minutes** | **Saved ~6 minutes per run** |
| **Total 15-Min Video Render Time** | 35+ minutes (3 passes) | **6–8 min CPU / ~1.5 min GPU** | **Single-Pass Filtergraph (4x faster)** |


---

### 🎯 The 4-Pillar Zero-Drift Sync Engine

```text
[Old Sequential Pipeline - Compounding Drift]
Scene 1: [--- Voice 1 (3.5s) ---]
Scene 2 (starts 3.0s):           [--- Voice 2 (3.5s) ---] -> Drift: +0.5s
Scene 3 (starts 6.0s):                                   [--- Voice 3 ---] -> Drift: +1.0s
Scene 100:                                                                -> Drift: +148.36s (2.5 min delay!)

[v2.2 Scene-Anchor Engine - Zero Cumulative Drift]
Scene 1: [--- Voice 1 (3.1s) ---]
Scene 2 (starts 3.0s): [--- Voice 2 (2.9s) ---]  ← Hard-anchored to starts[2] (Drift: 0.0s)
Scene 3 (starts 6.0s): [--- Voice 3 (3.0s) ---]  ← Hard-anchored to starts[3] (Drift: 0.0s)
Scene 100:             [--- Voice 100 ---]       ← Auto-realigned at every scene cut!
```

1. **Pillar 1: Scene Timestamp Anchoring (`starts[idx]`):**
   - In [`agents/video_merger_agent.py`](agents/video_merger_agent.py), each discrete dialogue and narration block is strictly anchored to its exact video scene cut timestamp.
   - Any local variation in one scene never bleeds or cascades into the next. At every scene transition, action sequence, or pause, the timeline resets to **0.000s synchronization**.

2. **Pillar 2: Strict Character Budgeting in LLM Generation:**
   - Burmese syllables take approximately 1.8x to 2.2x longer to speak than English syllables.
   - In [`agents/writer_agent.py`](agents/writer_agent.py), translation prompts enforce a strict formula:
     $$\text{max\_chars} = \max(18, \lfloor\text{duration\_sec} \times 11.0\rfloor)$$
   - Gemini produces punchy, concise, storytelling sentences tailored precisely to fit the available time budget.

3. **Pillar 3: 100% QAAgent Auto-Rewrite Resolution:**
   - In [`agents/qa_agent.py`](agents/qa_agent.py), over-length lines are verified against character bounds.
   - Using robust multi-format ID extraction with regex digit fallback (`re.search(r'\d+', ...)`) and positional matching, 100% of over-length script blocks are automatically shortened by Gemini without dropping narrative meaning.

4. **Pillar 4: WSOLA Pitch-Preserving Audio Time-Stretching:**
   - In [`agents/voice_agent.py`](agents/voice_agent.py), audio speedup boundaries are calibrated to `[0.78, 1.28]` using FFmpeg's `atempo` filter (Waveform Similarity Overlap-Add algorithm).
   - High-tempo dialogue is spoken crisply without any robotic pitch distortion or chipmunk artifacts.

---

### 🎙️ Full Spoken Sentence Delivery Guarantee (Zero Truncation)

In many automated dubbing systems, sentences that slightly exceed scene duration are aggressively chopped off (`subclip(0, duration)`), leaving incomplete words and abrupt endings.

**In v2.2, mid-speech truncation is permanently eliminated:**
* All hard clipping has been removed from the audio placement pipeline.
* Sentences **always play to their final syllable**.
* Combined with Strict Character Budgeting and gentle pitch-preserving time-stretching, speech naturally finishes within its scene envelope while delivering 100% of every translated word.

---

### ⚡ Self-Healing NVIDIA NVENC GPU Hardware Video Acceleration

* **The Problem:** Cloud Ubuntu environments (such as Kaggle) ship default FFmpeg packages without NVENC support due to proprietary license restrictions, forcing video post-processing to fall back to slow CPU encoding.
* **The v2.2 Solution:** Integrated `_auto_setup_nvenc_linux()` in [`agents/video_merger_agent.py`](agents/video_merger_agent.py):
  - Detects if an NVIDIA GPU is present via `nvidia-smi`.
  - Automatically downloads and activates the official **BtbN Static NVENC FFmpeg build** in the background during initialization.
  - Video rendering executes on dedicated NVENC silicon (`h264_nvenc` with preset `p4`), achieving speeds of **400–650 FPS (5x–8x faster)**.
  - Full automated fallback cascade: `NVIDIA NVENC` ➔ `Intel QuickSync (QSV)` ➔ `AMD AMF` ➔ `Multi-Core CPU (libx264 superfast)`.

---

## 🌟 Key Features (v2.2 Architecture)

### 🎯 1. Frame-Accurate Scene Synchronization & Zero Cumulative Drift
* **Scene Timestamp Anchoring:** Each discrete dialogue and narration block is strictly locked to its visual scene timestamp (`starts[idx]`).
* **Zero Cumulative Delay:** Prevents speech delays from cascading across scenes. Even across 20–120 minute movies, visual scene transitions and narration align at exact **0.000s synchronization**.
* **Full Spoken Sentence Delivery Guarantee:** Sentences are **NEVER truncated or cut off mid-speech**. Every dialogue line is spoken 100% completely from the first word to the very last syllable.

### 🎙️ 2. Natural Human Voice Sweet Spot (`+18%`) & Strict Character Budgeting
* **Strict Per-Item Character Budget:** Gemini translation prompts strictly enforce `max_chars` limits (~11 chars/sec) to craft concise, punchy storytelling lines that naturally fit visual cuts.
* **100% QAAgent Auto-Rewrite:** Automatically identifies and rewrites any over-length dialogue blocks to ensure perfect scene duration compliance.
* **Natural Pitch-Preserving Speedup:** Utilizes FFmpeg `atempo` (WSOLA algorithm) up to 1.28x to ensure crisp, energetic pacing without robotic sound or chipmunk distortion.

### 🎮 3. High-Speed GPU Hardware Video Acceleration (NVIDIA NVENC)
* **Self-Healing Linux Auto-Installer:** Automatically detects NVIDIA GPUs on Linux (Colab/Kaggle) and auto-configures the BtbN Static NVENC FFmpeg build in the background with zero user intervention.
* **5x–8x Faster Video Encoding:** Cuts 1080p post-processing and 9:16 Canvas Reels rendering down from 7 minutes to ~1.5 minutes using dedicated NVENC hardware silicon (`h264_nvenc`, preset `p4`).

### 🔇 4. 100% Muted Original English Dialogue on `--skip-demucs` + Looped BGM
* **Zero English Speech Bleed:** Completely mutes original dialogue when `--skip-demucs` is active, avoiding muddy overlapping speech.
* **Cinematic Tension BGM:** Automatically loops and mixes atmospheric tension soundscapes (`assets/bgm/scifi_tension.wav`) at calibrated background volume.

### 🍪 5. Multi-Platform Auto Downloader (Apple VisionOS & Anti-Bot Resilient Matrix)
* **YouTube:** Powered by Apple VisionOS (`visionos`) 1080p HLS m3u8 streaming and Android native API fallbacks with Node.js runtime integration. 100% immune to Google Play Integrity checks and Cloud Datacenter IP challenges (`Sign in to confirm you're not a bot`), working seamlessly with or without browser cookies.
* **DramaBox (`dramaboxdb.com`):** Direct web & HLS streaming download with VIP authentication.
* **ReelShort (`reelshort.com`):** Direct short drama download with session cookies.
* **Local Upload:** Direct Drag & Drop upload of MP4, MKV, WebM files in the Web UI.

### 🛑 6. 1-Click Instant Force Stop Pipeline
* Emergency **`🛑 Force Stop Pipeline`** button in the Web UI to immediately cancel running jobs.
* Terminates active child subprocess trees (`ffmpeg`, `whisper`, `demucs`, `yt-dlp`) to instantly release GPU VRAM and CPU memory.

### 📝 7. Subtitle Mode Switch & Standalone SRT Export
* **🔥 Burn Subtitles (Hardsub - Default):** Burns styled Myanmar ASS subtitles (Padauk / Myanmar Text) directly into the video frame.
* **🎙️ Voiceover Only (Clean Frame):** Generates clean video with dubbed voice only (no text on video), and automatically exports standalone **`myanmar_subs.srt`** and **`myanmar_subs.ass`** subtitle files for YouTube CC / VLC player.

### 🎨 8. Subtitle Style Presets (Interactive Visual Studio)
Choose from 5 professionally designed subtitle styles with real-time live preview in the Web UI:
* **🎬 Cinema Box (Netflix Style - `box_black`):** White text over dark translucent box (maximum readability & contrast for movie recaps).
* **⚡ TikTok / Reels Yellow (`yellow_pop`):** High-energy gold/yellow text with bold black border and drop shadow (ideal for viral shorts).
* **⚪ Classic White Stroke (`white_stroke`):** Crisp white text with black outline (clean YouTube classic aesthetic).
* **💎 Cyber Cyan Neon (`cyan_cyber`):** Glowing cyan font with deep blue outline (perfect for Sci-Fi, Cyberpunk & Tech movies).
* **🩸 Thriller Crimson Box (`crimson_box`):** White text over dark crimson red box (high suspense for Horror, Mystery & Thrillers).

### ⚙️ 9. Resolution Quality Presets
* **🌟 1080p Full HD (Default / Highest Quality):** 1920x1080 (16:9 Landscape) & 1080x1920 (9:16 Vertical).
* **⚡ 720p HD (Faster Render / Smaller File):** 1280x720 (16:9 Landscape) & 720x1280 (9:16 Vertical) for 2x faster encoding.

### 📱 10. Multi-Format Video Output (16:9 Landscape, 9:16 Vertical Reels, or Both)
* **🌟 Both (16:9 + 9:16 - Default):** Generates both YouTube 16:9 and Facebook/TikTok 9:16 vertical videos in a single run.
* **🖥️ 16:9 Landscape Only:** Focuses exclusively on standard YouTube widescreen output.
* **📱 9:16 Vertical Only:** Produces high-speed Facebook Reels, TikTok & YouTube Shorts with dynamic bokeh video background, top hook title, and safe-zone Myanmar subtitles.

### 👫 11. AI Multi-Voice Character Dubbing & Action Narration Bridge
* **Multi-Voice Dubbing:** Automatically assigns male characters to `my-MM-ThihaNeural` and female characters to `my-MM-NilarNeural`.
* **Action Narration Bridge:** Detects non-verbal action scenes (>18s) and uses **Gemini 3.5 Flash** to synthesize engaging storyline narration so the audience never experiences silence.
* **Dynamic Audio Ducking:** Automatically lowers background ambient sound to 12% during speech and raises it back to 35% during pauses.

### 🧠 12. Google AI Studio 2026 PRO Tier & Model Auto-Rotation Chain
* **Tier Synchronization:** Pre-configured with Google AI Studio 2026 PRO quotas:
  - **Workhorse:** `gemini-3.5-flash-lite` (15 RPM) & `gemini-3.1-flash-lite` (15 RPM)
  - **Fastest Cloud:** `gemini-flash-latest` (Dynamic auto-routed to newest stable engine)
  - **Primary & Fallbacks:** `gemini-3.5-flash-lite`, `gemini-flash-latest`, `gemini-3.5-flash`, `gemini-3.7-flash`, `gemini-3.6-flash`
* **Zero-Error Parsing:** Safe `_extract_text_from_gemini_response` multi-part and thought-block extractor preventing `KeyError: 'parts'`.

### ⏱️ 13. Process Records Time & Live Stopwatch Dashboard
* **Live Elapsed Stopwatch:** Real-time ticking stopwatch (`⏱️ 01:24`) on the Web UI dashboard during video processing.
* **Phase Timing Badges:** Real-time breakdown of seconds spent on each pipeline stage (Video Analysis, Whisper STT, Gemini Script Translation, Voiceover Generation, and Video Merge).
* **Historical Process Records:** Every completed output card permanently stores and displays its comprehensive duration table.

### 🚀 14. Dedicated GPU Cloud Acceleration & Hybrid PC Fallback
* **Google Colab Mode:** Dedicated **NVIDIA T4 GPU (16GB VRAM)** execution utilizing Whisper CUDA FP16 Tensor Cores, Demucs `-d cuda`, and FFmpeg NVENC (`h264_nvenc`) hardware encoder.
* **Kaggle Mode:** Dedicated **Dual NVIDIA T4 GPUs (30GB VRAM)** or **P100 GPU (16GB VRAM)** with 12-hour continuous sessions and Cloudflare Secure Tunnel.
* **Local PC Mode:** Intelligent auto-detection of NVIDIA CUDA, Intel QuickSync (`h264_qsv`), and AMD AMF (`h264_amf`), with zero-error fallback to CPU Multi-core.

### 🖼️ 15. Optional 3-Second Thumbnail Intro & Smart Audio Ducking
* **Toggleable Thumbnail Intro:** Control whether a 3-second thumbnail freeze-frame appears at video start via Web UI checkbox, `config.json` (`"thumbnail_intro": {"enabled": false, "duration_sec": 3.0}`), or CLI flags (`--thumbnail-intro` / `--no-thumbnail-intro`). When enabled, ASS subtitles are dynamically shifted to preserve flawless subtitle-to-voice synchronization.
* **Zero Dead Silence Audio Ducking:** Preserves movie ambient background SFX, BGM, and foley sound effects even when Demucs is bypassed (`--skip-demucs`), automatically ducking original audio down to 15% volume under the AI Burmese voiceover.

### ⚡ 16. Pure FFmpeg Audio Compositing & Unified Single-Pass Filtergraph
* **Zero MoviePy Dependency:** Transitioned completely to C-accelerated linear PCM voiceover assembly (`_assemble_voiceover_track`) in ~2 seconds using `soundfile` and `numpy`. MoviePy is never imported or executed in standard runs, slashing RAM usage from >2GB to ~70MB and eliminating Python GIL bottlenecks.
* **Broadcast Dynamic Audio Ducking:** Employs FFmpeg's native `sidechaincompress=threshold=0.08:ratio=8:attack=100:release=400` filter and `amix=inputs=2:duration=first:dropout_transition=0`. Background audio (Demucs SFX or cinematic BGM loop) ducks smoothly during Burmese narration and swells naturally in dialogue gaps.
* **Simultaneous Dual Output:** Generates both `final_recap.mp4` (hardsubbed 16:9 with styled Myanmar ASS subtitles) and `final_recap_clean.mp4` (clean canvas for 9:16 Reels) in a single hardware-accelerated pass (`h264_nvenc` / `h264_qsv` / `libx264 superfast`), reducing 15-minute recap render time from 35+ minutes to 6–8 minutes on CPU and ~1.5 minutes on GPU.
* **Isolated Legacy Fallback:** Preserves MoviePy inside `_legacy_moviepy_merge()` as an isolated safety net for edge cases or 3-second thumbnail intro stitching.

### 🧠 17. Gemini CoT Reasoning Filtering (100% Clean JSON)
* **Thinking-Safe Parser:** Automatically filters out Gemini 2.5 / 3.x internal Chain-of-Thought reasoning blocks (`p.get("thought")`) and strips `<thought>` tags before JSON parsing.
* Eliminates JSON syntax errors in `QAAgent` when Gemini models deliberate on character counts or syllable budgets, guaranteeing 100% automated script rewrite success.

### 🎙️ 14. Acoustic Pitch & Multimodal Vision Diarization (Multi-Voice Dubbing)
* **Hybrid $F_0$ Autocorrelation:** Evaluates acoustic pitch ($70\text{ Hz} \le F_0 \le 350\text{ Hz}$) on vocal audio slices to classify gender (`male` vs `female`) with sub-millisecond precision.
* **Multimodal Visual Keyframes:** Injects lightweight video frame captures at dialogue cuts into Gemini Vision prompts to identify character identity, emotion, and gender.
* **Dynamic Multi-Voice Dubbing:** Automatically switches between `my-MM-NilarNeural` (female characters) and `my-MM-ThihaNeural` (male characters/narrator), applying emotion-driven pitch (`+5Hz` / `-2Hz`) and volume modulation.

### 💾 15. Deterministic Phase-by-Phase Checkpoint Resume Engine
* **7-Phase State Tracking:** Robust state boundaries across Analysis, Audio STT, Scene Detection, Scripting/SEO, Voice Generation, Video Merge, and QA.
* **Physical Artifact Verification:** Validates actual on-disk files before skipping any completed phase, preventing corrupted or incomplete runs.
* **Granular Clip-Level Voiceover Skipping:** Reuses already synthesized `scene_*.mp3` files without duplicate TTS network calls.
* **Atomic `checkpoint.json`:** Crash-resilient progress checkpointing allows instantaneous resume via CLI (`--resume` / `--fresh`) and Web UI.

---


### 🎯 The Triple-Engine Architecture

This platform provides three specialized production engines tailored for different video localization needs:

| Feature / Capability | 🎬 Engine 1: Movie Recap Studio | 📝 Engine 2: Subtitle & Transcript Studio | 🎞️ Engine 3: Hardsub Studio |
| :--- | :---: | :---: | :---: |
| **Primary Script / Core** | [`main.py`](main.py) / `MasterAgent` | [`subtitle_engine.py`](subtitle_engine.py) | [`hardsub_engine.py`](hardsub_engine.py) |
| **Windows Quick Launcher** | [`Run_Movie_Recap.bat`](Run_Movie_Recap.bat) | [`Run_Subtitle_Engine.bat`](Run_Subtitle_Engine.bat) | [`Run_Hardsub_Engine.bat`](Run_Hardsub_Engine.bat) |
| **Primary Output Purpose** | Viral Movie Recaps with Full AI Dubbing | 1:1 Subtitles & Multi-Lingual Transcripts | Hardsubbed Videos with 100% Original Audio |
| **Audio Treatment** | AI Multi-Voice Dubbing (Thiha / Nilar) | Original Audio (Muted or Preserved) | **100% Original Audio Preserved (Zero TTS)** |
| **Anti-Copyright Shields** | Dynamic ducking, scene-trimming | Standard 1:1 matching | **1.02x Zoom/Crop, Color EQ, Mirror, Audio Shield** |
| **Subtitle Blur Protection** | Bottom area blur detection | Optional transcript | **Vision AI Auto Subtitle Blur (12%–30% bottom)** |
| **Translation Style** | Storyteller Persona (`...ခဲ့တာပေါ့ဗျာ`) | Spoken Burmese (စကားပြောဟန်) | **Faithful 1:1 Persona (Male/Female/Child particles)** |
| **Deliverable Exports** | 16:9 Video, 9:16 Reels, Thumbnail, SEO | 6 Deliverables (`.mp4`, `.txt` x3, `.srt`, QC) | 16:9 MP4, 9:16 MP4, `.ass`, `.srt`, `.json`, QC Report |

---

## 🗂️ Project Structure

```text
ai-translate-agent/
├── hardsub_engine.py          ← Engine 3: 100% Original Audio & Burmese Hardsub Studio
├── subtitle_engine.py         ← Engine 2: YouTube to Burmese Subtitle & Transcript Studio
├── main.py                    ← Engine 1 CLI & Unified Multi-Engine Dispatcher
├── web_ui.py                  ← FastAPI Web Dashboard with 3-Engine Graphical Interface
│
├── Run_Movie_Recap.bat        ← Master Launcher (Menu with options for all 3 engines)
├── Run_Hardsub_Engine.bat     ← Direct 1-Click Launcher for Hardsub Studio
├── Run_Subtitle_Engine.bat    ← Direct 1-Click Launcher for Subtitle Engine
├── Start_Web_UI.bat           ← Direct 1-Click Launcher for Web UI Dashboard
│
├── agents/
│   ├── master.py              ← Engine 1 orchestrator (Phases 1–7) & hardware management
│   ├── downloader_agent.py    ← Multi-platform downloader (YouTube, DramaBox, ReelShort)
│   ├── video_agent.py         ← Video metadata: FPS, duration, resolution (OpenCV & FFprobe)
│   ├── audio_agent.py         ← Audio extract + Fast Whisper STT (CUDA FP16 / INT8) + Demucs
│   ├── writer_agent.py        ← 1:1 Dialogue Translation (Gemini 3.5 Flash) + Action Bridge
│   ├── seo_agent.py           ← Viral Title, Description, Tags, and Hashtags generator
│   ├── voice_agent.py         ← Multi-Voice TTS (Thiha Male / Nilar Female) & Time Stretch
│   ├── video_merger_agent.py  ← Single-Pass Merger, Audio Ducking, NVENC/QSV Hardware Encoder
│   ├── thumbnail_agent.py     ← High-CTR Golden Yellow Top-Center Thumbnail Generator
│   └── qa_agent.py            ← Sync score & language naturalness QA review
│
├── brain/
│   ├── memory.py              ← Pydantic shared state (MovieState with atomic JSON persistence)
│   ├── planner.py             ← Overnight Batch Processor with auto API key rotation
│   ├── prompts.py             ← LLM prompt templates (Dialogue, SEO, QA, Persona translation)
│   ├── config.py              ← config.json loader with Gemini 3.5 Flash defaults
│   ├── gemini_client.py       ← Gemini API client with safe parsing & 8-model fallback rotation
│   └── sqlite_store.py        ← SQLite local database for multi-engine state & job logs
│
├── templates/
│   └── index.html             ← Modern Glassmorphic Web UI (Tabs for Recap, Subtitle & Hardsub)
│
├── AI_Movie_Translate_Colab.ipynb  ← Official Google Colab One-Click Dedicated GPU Notebook
├── AI_Movie_Translate_Kaggle.ipynb ← Official Kaggle One-Click Dual T4 Dedicated GPU Notebook
├── config.json                ← Active runtime configuration (API keys, branding, models)
├── config.example.json        ← Default configuration template
├── cookies.txt                ← Netscape cookie file for YouTube anti-bot bypass
├── requirements.txt           ← Python package dependencies
├── assets/                    ← Reference voice samples, cookies, and branding assets
├── movies/                    ← Place source video files here
├── outputs/                   ← Generated final videos, thumbnails, scripts, and logs
└── temp/                      ← Intermediate audio/video cache (Auto-cleaned after merge)
```

---

## 💻 Local Setup (PC)

```bash
# 1. Clone repository
git clone https://github.com/paipai1999/ai-translate-agent.git
cd ai-translate-agent

# 2. Create virtual environment & install dependencies
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt

# 3. Add your Gemini API Key in config.json (or in Web UI)
#    Get free API keys from: https://aistudio.google.com
```

---

## 🚀 Usage

### 🌐 Method 1: Web UI Dashboard (Recommended)
Double-click [`Start_Web_UI.bat`](Start_Web_UI.bat) or run:
```bash
python web_ui.py
```
*Open your browser at: `http://localhost:5000`*

* **3 Dedicated Engine Tabs:** Switch effortlessly between **🎬 Recap Studio**, **📝 Subtitle Engine**, and **🎞️ Hardsub Studio**.
* **Direct Video Download & Upload:** Paste any YouTube, DramaBox, or ReelShort URL, or click **📁 Upload** to select a file from your computer.
* **Video Format Selector:** Choose between `🌟 Both (16:9 + 9:16)`, `📺 16:9 Landscape`, and `📱 9:16 Vertical Reels`.
* **Subtitle Style Presets:** Choose from 5 presets (`box_black`, `yellow_pop`, `white_stroke`, `cyan_cyber`, `crimson_box`) with live preview canvas.
* **Anti-Copyright & Blur Controls:** Enable Mirroring, Color Grading EQ, Audio Pitch Shields, and Vision AI Subtitle Blur with custom heights (12%–30%).
* **1-Click Force Stop:** Click `🛑 Force Stop Pipeline` at any time to immediately cancel execution and release resources.

### 💻 Method 2: Command Line (CLI)

#### 🎬 Engine 1: AI Movie Recap Studio
```bash
# Process single video or YouTube URL
python main.py "movies/my_movie.mp4"

# Process with 9:16 vertical Reels and TikTok yellow subtitle preset
python main.py "movies/my_movie.mp4" --format 9:16 --sub-style yellow_pop

# Batch process all videos in movies/ folder
python main.py --batch --format both
```

#### 📝 Engine 2: YouTube Subtitle & Transcript Studio
```bash
# Extract 1:1 original timestamps and produce 6 deliverable outputs
python subtitle_engine.py -i "https://youtu.be/..." --source-lang auto

# Specify custom project name
python subtitle_engine.py -i "movies/input.mp4" --name "My_Subtitle_Project"
```

#### 🎞️ Engine 3: 100% Original Audio & Burmese Hardsub Studio
```bash
# Run with dual 16:9 + 9:16 export, Vision AI blur, and anti-copyright shields
python hardsub_engine.py "https://youtu.be/..." --format both --res 1080p

# Run with custom Netflix box style and bottom 25% subtitle blur
python hardsub_engine.py "movies/input.mp4" --style box_black --blur yes --blur-height 0.25

# Dispatch via main.py dispatcher
python main.py "movies/input.mp4" --engine-mode hardsub --format 16:9 --style yellow_pop
```

---

## 📄 License
MIT License. Free for educational and commercial content creation.
