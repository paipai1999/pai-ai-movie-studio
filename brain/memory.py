import json
import os
import re
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str

class SpeakerSegment(BaseModel):
    """Phase 1 Gemini output: speaker-tagged dialogue with exact video timestamps."""
    speaker: str          # Character name (e.g. "Anya", "Arthur", "Unknown")
    text: str             # Exact dialogue as spoken
    start_sec: float      # Second in video when this line starts
    end_sec: float        # Second in video when this line ends

class SceneData(BaseModel):
    scene_id: int
    start_time: str = ""
    end_time: str = ""
    start_sec: float = 0.0
    end_sec: float = 0.0
    summary: Optional[str] = None
    characters_detected: List[str] = Field(default_factory=list)
    subtitles: List[str] = Field(default_factory=list)

class MovieState(BaseModel):
    movie_name: str
    movie_path: Optional[str] = None   # Fix: was missing — Vision Mode always fell back silently
    file_path: Optional[str] = None
    audio_path: Optional[str] = None
    language: Optional[str] = None
    whisper_model: Optional[str] = None
    duration: Optional[str] = None
    fps: Optional[float] = None
    frames_count: Optional[int] = None
    resolution: Optional[str] = None
    genre: Optional[str] = None
    characters: List[str] = Field(default_factory=list)
    transcript: List[TranscriptSegment] = Field(default_factory=list)
    timeline: List[SceneData] = Field(default_factory=list)
    story_structure: Optional[Dict[str, Any]] = None
    speaker_transcript: List[Any] = Field(default_factory=list)  # Phase 1: SpeakerSegment list
    generated_script: Optional[List[Dict[str, Any]]] = None
    seo_metadata: Optional[Dict[str, Any]] = None
    subtitle_detection: Optional[Dict[str, Any]] = None
    subtitle_mode: Optional[str] = "auto"
    subtitle_style_preset: Optional[str] = "box_black"  # "box_black" | "yellow_pop" | "white_stroke" | "cyan_cyber" | "crimson_box"
    custom_thumb_title: Optional[str] = None
    watermark_override: Optional[Dict[str, Any]] = None
    video_format: Optional[str] = "both"  # "both" (16:9 + 9:16) | "16:9" | "9:16"
    reels_video_path: Optional[str] = None  # Path to generated 9:16 Facebook Reels video
    clean_video_path: Optional[str] = None  # Path to un-subtitled video copy (used for 9:16 Reels canvas source)
    thumbnail_intro_enabled: Optional[bool] = False  # Whether 3-second thumbnail intro should be stitched
    skip_demucs: Optional[bool] = False  # When True, Demucs vocal separation was skipped
    source_language: Optional[str] = "auto"  # Source audio language for Whisper STT (e.g. "auto", "zh", "en", "th", "ko", "ja")
    script_engine: Optional[str] = "recap"  # Narration Script Engine: "recap" (Storyteller) | "translate" (1:1 Dubbing)
    subtitle_timings: List[Any] = Field(default_factory=list)  # Exact (place_time, duration, text) timings synced with audio
    trim_end: Optional[float] = None  # Manual seconds to trim from video end
    no_smart_trim: Optional[bool] = False  # When True, automatic outro trimming is disabled
    outro_card: Optional[bool] = False  # When True, appends 3-second Pai AI Movie Studio outro card
    subtitles_burned: Optional[bool] = False  # Set to True when Myanmar ASS subtitles are burned onto video
    uploaded_video_name: Optional[str] = None  # Stores the GenAI file name (e.g. files/abc)
    sfx_mode: Optional[str] = "original_sfx"  # "original_sfx" | "bgm" | "both" | "none"
    sfx_volume: Optional[float] = 0.15  # 0.05 to 0.50 background volume level under voiceover
    translation_style: Optional[str] = "recap"  # "recap" (Storyteller) | "dialogue" (1:1 Natural) | "persona" (Gender/Kinship)
    audio_mode: Optional[str] = "ai_voiceover"  # "ai_voiceover" | "original" (100% Original Audio) | "none"
    blur_mode: Optional[str] = "auto"  # "auto" | "yes" | "no"
    blur_height: Optional[float] = None  # Custom blur height ratio
    mirror: Optional[bool] = False  # Horizontal mirror for anti-copyright
    audio_anti_copyright: Optional[bool] = False  # Subtle audio tempo perturbation (atempo=1.008)

    model_config = {"extra": "allow"}
    qa_results: Optional[Dict[str, Any]] = None  # Phase 7: QA Agent review results
    output_video_transcript: List[Any] = Field(default_factory=list)  # Phase 7: Re-extracted output video transcript & actions
    phase_durations: Dict[str, float] = Field(default_factory=dict)  # Elapsed seconds per phase (e.g. {"Phase 1": 1.5, ...})
    total_duration_sec: float = 0.0  # Total execution time in seconds
    total_duration_formatted: str = ""  # Total execution time formatted (e.g. "00:04:15" or "4m 15s")
    start_time: Optional[str] = None  # ISO start timestamp
    end_time: Optional[str] = None  # ISO completion timestamp
    current_phase: str = "Initializing..."
    progress: int = 0
    pipeline_status: str = "QUEUED"  # QUEUED | RUNNING | COMPLETED | COMPLETED_WITH_WARNINGS | QA_PENDING | FAILED | CANCELLED
    phase_statuses: Dict[str, str] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    completed_phases: List[str] = Field(default_factory=list)  # Tracks successfully completed pipeline phase IDs
    phase_checkpoints: Dict[str, Any] = Field(default_factory=dict)  # Metadata & artifact paths per completed phase
    speaker_profiles: Dict[str, Dict[str, Any]] = Field(default_factory=dict)  # Multimodal speaker diarization profile

    def mark_phase_completed(self, phase_name: str, details: Dict[str, Any] = None):
        """Marks a pipeline phase as successfully completed with optional checkpoint metadata."""
        if phase_name not in self.completed_phases:
            self.completed_phases.append(phase_name)
        if details is not None:
            self.phase_checkpoints[phase_name] = details

    def is_phase_completed(self, phase_name: str) -> bool:
        """Checks whether a pipeline phase is recorded as completed."""
        return phase_name in self.completed_phases

    def get_last_completed_phase(self) -> Optional[str]:
        """Returns the ID of the latest completed phase, or None if pipeline hasn't run."""
        return self.completed_phases[-1] if self.completed_phases else None

    def reset_from_phase(self, phase_name: str):
        """Removes the given phase and any subsequent phases to allow targeted restart."""
        if phase_name in self.completed_phases:
            idx = self.completed_phases.index(phase_name)
            to_remove = self.completed_phases[idx:]
            self.completed_phases = self.completed_phases[:idx]
            for p in to_remove:
                self.phase_checkpoints.pop(p, None)

    @property
    def duration_sec(self) -> float:
        """Returns video duration as float seconds, parsed from HH:MM:SS duration string."""
        if not self.duration:
            return 0.0
        try:
            parts = str(self.duration).split(':')
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
            else:
                return float(self.duration)
        except Exception:
            return 0.0

    @duration_sec.setter
    def duration_sec(self, val: float):
        """Sets duration string from float seconds."""
        if val is None or float(val) <= 0.0:
            self.duration = None
            return
        total_sec = float(val)
        h = int(total_sec // 3600)
        m = int((total_sec % 3600) // 60)
        s = total_sec % 60
        self.duration = f"{h:02d}:{m:02d}:{s:05.2f}"
    
    @staticmethod
    def _slugify_path_component(value: str) -> str:
        value = str(value).strip()
        value = re.sub(r'[\\/:*?"<>|]+', '', value)
        value = re.sub(r'[\s]+', ' ', value)
        value = value.strip(' ._-')
        return value or 'untitled'

    @property
    def project_dir(self) -> str:
        movie_name = str(self.movie_name or '').strip()
        match = re.search(
            r'(.+?)[_\s-]*((?:Season\s*\d+|S\d+E\d+|Episode\s*\d+|Ep\s*\d+|Ep\s*\d+[A-Za-z]?)(?:.*)?)$',
            movie_name,
            flags=re.IGNORECASE,
        )
        if match:
            series = self._slugify_path_component(match.group(1))
            episode = self._slugify_path_component(match.group(2))
            return os.path.join(series, episode)
        return self._slugify_path_component(movie_name)

    def save_to_json(self, filepath: str):
        dirname = os.path.dirname(filepath)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        tmp_path = filepath + ".tmp"
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(self.model_dump_json(indent=4))
            os.replace(tmp_path, filepath)
        except Exception as e:
            print(f"[ERROR] MovieState: Failed to save state to {filepath}: {e}")
            if os.path.exists(tmp_path):
                try: os.remove(tmp_path)
                except Exception: pass

    @classmethod
    def load_from_json(cls, filepath: str) -> Optional['MovieState']:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return cls(**data)
        except FileNotFoundError:
            print(f"[WARN] MovieState: State file not found: {filepath}")
            return None
        except Exception as e:
            print(f"[ERROR] MovieState: Failed to load state from {filepath}: {e}")
            return None
