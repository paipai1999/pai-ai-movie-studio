"""
Core Media & Subtitle Processing Package (ဗဟိုပြု မီဒီယာနှင့် စာတန်းထိုး Processing စနစ်)
========================================================================================
This package provides centralized, reusable utilities for media processing,
subtitle generation, styling presets, anti-copyright evasion shields, and video blur.

ဤ package သည် Pai AI Movie Studio တစ်ခုလုံးအတွက် ဗဟိုပြု media processing၊
စာတန်းထိုးဖန်တီးမှု၊ Style Presets နှင့် မူပိုင်ခွင့် ကာကွယ်ရေး filter များကို ပံ့ပိုးပေးပါသည်။
"""

from core.subtitle_builder import (
    format_srt_timestamp,
    format_ass_timestamp,
    parse_srt_timestamp,
    wrap_burmese_text,
    build_ass_script,
    build_srt_script,
    SUBTITLE_STYLE_PRESETS,
)
from core.anti_copyright import (
    build_video_anti_copyright_filters,
    build_audio_anti_copyright_filters,
)
from core.video_blur import (
    calculate_blur_box,
    build_boxblur_filter,
)

__all__ = [
    "format_srt_timestamp",
    "format_ass_timestamp",
    "wrap_burmese_text",
    "build_ass_script",
    "build_srt_script",
    "SUBTITLE_STYLE_PRESETS",
    "build_video_anti_copyright_filters",
    "build_audio_anti_copyright_filters",
    "calculate_blur_box",
    "build_boxblur_filter",
]
