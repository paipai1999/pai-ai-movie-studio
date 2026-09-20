"""
Subtitle Builder & Styling Utility (စာတန်းထိုး တည်ဆောက်မှုနှင့် ဒီဇိုင်းစနစ်)
==========================================================================
Handles generation of ASS (Advanced SubStation Alpha) and SRT (SubRip) subtitles
with support for cinema-grade styling presets, custom font sizing, responsive
aspect ratio dimensions, and natural Burmese syllable wrapping.

ဤ module သည် ASS နှင့် SRT စာတန်းထိုးဖိုင်များကို တည်ဆောက်ပေးပြီး Cinema Box၊
TikTok Yellow စသည့် ဒီဇိုင်းပုံစံများ၊ မြန်မာစာလုံး ပိုင်းဖြတ်မှုများကို စနစ်တကျ စီမံပေးပါသည်။
"""

import os
from typing import List, Dict, Any, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Subtitle Style Presets Configuration (ဒီဇိုင်းပုံစံ အဓိပ္ပာယ်ဖွင့်ဆိုချက်များ)
# ─────────────────────────────────────────────────────────────────────────────
SUBTITLE_STYLE_PRESETS: Dict[str, Dict[str, Any]] = {
    "box_black": {
        "name": "Cinema Box",
        "description": "Netflix-style high contrast subtitle with dark background box",
        "primary_color": "&H00FFFFFF",   # Pure White text
        "outline_color": "&H00000000",   # Black outline
        "back_color": "&HB0000000",      # 70% Opaque black background box
        "border_style": 3,               # 3 = Opaque rectangle box
        "outline_w": 2,
        "shadow": 0,
    },
    "yellow_pop": {
        "name": "TikTok Yellow",
        "description": "Vibrant yellow typography with bold black stroke outline",
        "primary_color": "&H0000FFFF",   # BGR format: Yellow (Blue=0, Green=255, Red=255)
        "outline_color": "&H00000000",   # Solid black stroke
        "back_color": "&H80000000",      # Soft shadow
        "border_style": 1,               # 1 = Outline with shadow
        "outline_w": 3,
        "shadow": 2,
    },
    "white_stroke": {
        "name": "Classic White",
        "description": "Clean white typography with deep black shadow stroke",
        "primary_color": "&H00FFFFFF",   # Pure white
        "outline_color": "&H00000000",   # Black outline
        "back_color": "&H80000000",      # Shadow
        "border_style": 1,               # Outline + shadow
        "outline_w": 3,
        "shadow": 1,
    },
    "cyan_cyber": {
        "name": "Cyber Cyan",
        "description": "Modern cyber cyan neon text with opaque box",
        "primary_color": "&H00FFFF00",   # BGR: Cyan (Blue=255, Green=255, Red=0)
        "outline_color": "&H00000000",
        "back_color": "&HB0000000",
        "border_style": 3,
        "outline_w": 2,
        "shadow": 0,
    },
    "crimson_box": {
        "name": "Thriller Red",
        "description": "Dramatic crimson background box for thriller and suspense films",
        "primary_color": "&H00FFFFFF",   # White text
        "outline_color": "&H00000000",
        "back_color": "&HB00000B0",      # Deep dark red box
        "border_style": 3,
        "outline_w": 2,
        "shadow": 0,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Timecode Formatting Utilities (အချိန်မှတ် အသွင်ပြောင်း ကိရိယာများ)
# ─────────────────────────────────────────────────────────────────────────────
def format_srt_timestamp(seconds: float) -> str:
    """
    Converts a floating-point seconds value into standard SRT timecode (HH:MM:SS,mmm).
    စက္ကန့်ကို စံချိန်မီ SRT အချိန်မှတ် (နာရီ:မိနစ်:စက္ကန့်,မီလီစက္ကန့်) သို့ ပြောင်းပေးသည်။
    """
    total_ms = int(round(max(0.0, float(seconds)) * 1000))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    secs = (total_ms % 60_000) // 1000
    ms = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def format_ass_timestamp(seconds: Any) -> str:
    """
    Converts a floating-point seconds value (or SRT timestamp string) into ASS timecode (H:MM:SS.cc).
    စက္ကန့် (သို့မဟုတ် SRT အချိန်မှတ် စာသား) ကို စံချိန်မီ ASS အချိန်မှတ် သို့ ပြောင်းပေးသည်။
    """
    if isinstance(seconds, str):
        try:
            seconds = float(seconds)
        except ValueError:
            seconds = parse_srt_timestamp(seconds)
    total_cs = int(round(max(0.0, float(seconds)) * 100))
    hours = total_cs // 360_000
    minutes = (total_cs % 360_000) // 6000
    secs = (total_cs % 6000) // 100
    cs = total_cs % 100
    return f"{hours:01d}:{minutes:02d}:{secs:02d}.{cs:02d}"


def parse_srt_timestamp(ts_str: str) -> float:
    """
    Parses an SRT timestamp string (HH:MM:SS,mmm or HH:MM:SS.mmm) into floating-point seconds.
    SRT အချိန်မှတ် စာသားကို floating-point စက္ကန့်အဖြစ် ပြောင်းလဲတွက်ချက်ပေးသည်။
    """
    clean = str(ts_str).replace(",", ".").strip()
    parts = clean.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return float(h) * 3600.0 + float(m) * 60.0 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return float(m) * 60.0 + float(s)
    return float(clean)


# ─────────────────────────────────────────────────────────────────────────────
# Burmese Text Wrapping Utility (မြန်မာစာကြောင်း အဖြတ်အတောက် စီမံခြင်း)
# ─────────────────────────────────────────────────────────────────────────────
def wrap_burmese_text(text: str, max_chars: int = 32) -> str:
    """
    Wraps long Burmese sentences at natural grammatical break points (၊, ။, or space).
    ရှည်လျားသော မြန်မာစာကြောင်းများကို ပုဒ်ဖြတ်ပုဒ်ရပ် သို့မဟုတ် ကွက်လပ်နေရာတွင် အလိုအလျောက် ခေါက်ချပေးသည်။
    """
    text = text.strip()
    if len(text) <= max_chars or "\\N" in text:
        return text

    mid = len(text) // 2
    split_at = -1
    for offset in range(len(text) // 2):
        for candidate in [mid - offset, mid + offset]:
            if 0 <= candidate < len(text) and text[candidate] in (" ", "၊", "။"):
                split_at = candidate
                break
        if split_at != -1:
            break

    if split_at != -1:
        return text[:split_at].strip() + "\\N" + text[split_at:].strip()
    return text


# ─────────────────────────────────────────────────────────────────────────────
# ASS Subtitle Script Builder (ASS စာတန်းထိုး ဖိုင်အပြည့်အစုံ ဖန်တီးခြင်း)
# ─────────────────────────────────────────────────────────────────────────────
def build_ass_script(
    segments: List[Dict[str, Any]],
    preset: str = "box_black",
    video_w: int = 1920,
    video_h: int = 1080,
    resolution: str = "1080p",
    font_name: str = "Padauk",
    margin_bottom: int = 40,
    text_key: str = "burmese",
) -> str:
    """
    Builds a complete, formatted ASS subtitle script string.
    ရွေးချယ်ထားသော style preset နှင့် video resolution အလိုက် အပြည့်အစုံ ASS စာသားကို တည်ဆောက်ပေးသည်။
    """
    # 1. Resolve Style Preset Parameters
    style_info = SUBTITLE_STYLE_PRESETS.get(preset, SUBTITLE_STYLE_PRESETS["box_black"])
    primary_color = style_info["primary_color"]
    outline_color = style_info["outline_color"]
    back_color = style_info["back_color"]
    border_style = style_info["border_style"]
    outline_w = style_info["outline_w"]
    shadow = style_info["shadow"]

    # 2. Adjust font size proportionally based on vertical resolution
    is_vertical = video_h > video_w
    if resolution == "1080p":
        font_size = 38 if is_vertical else 42
    else:
        font_size = 28 if is_vertical else 32

    # 3. Build Header and Style definitions
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        f"PlayResX: {video_w}\n"
        f"PlayResY: {video_h}\n"
        "ScaledBorderAndShadow: yes\n"
        "Collisions: Normal\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_name},{font_size},{primary_color},&H000000FF,{outline_color},{back_color},"
        f"-1,0,0,0,100,100,0,0,{border_style},{outline_w},{shadow},2,15,15,{margin_bottom},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines = [header]

    # 4. Generate dialogue lines with timecodes and wrapping
    for seg in segments:
        txt = seg.get(text_key, "").strip()
        if not txt:
            continue

        # Wrap long dialogue cleanly
        wrapped_txt = wrap_burmese_text(txt, max_chars=34 if is_vertical else 42)
        safe_txt = wrapped_txt.replace("{", "").replace("}", "")

        # Compute start and end in seconds
        start_s = seg.get("start_s", seg.get("start", 0.0))
        end_s = seg.get("end_s", seg.get("end", 0.0))
        if isinstance(start_s, str):
            try:
                parts = start_s.replace(",", ".").split(":")
                start_s = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            except Exception:
                start_s = 0.0
        if isinstance(end_s, str):
            try:
                parts = end_s.replace(",", ".").split(":")
                end_s = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            except Exception:
                end_s = start_s + 2.0

        start_ass = format_ass_timestamp(float(start_s))
        end_ass = format_ass_timestamp(float(end_s))

        lines.append(f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{safe_txt}\n")

    return "".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# SRT Subtitle Script Builder (SRT စာတန်းထိုး ဖိုင်အပြည့်အစုံ ဖန်တီးခြင်း)
# ─────────────────────────────────────────────────────────────────────────────
def build_srt_script(
    segments: List[Dict[str, Any]],
    text_key: str = "burmese",
) -> str:
    """
    Builds a standard SubRip (.srt) subtitle file string.
    စံချိန်မီ .srt ဖိုင်စာသားကို တည်ဆောက်ပေးသည်။
    """
    blocks = []
    idx = 1
    for seg in segments:
        txt = seg.get(text_key, "").strip()
        if not txt:
            continue

        start_s = seg.get("start_s", seg.get("start", 0.0))
        end_s = seg.get("end_s", seg.get("end", 0.0))
        if isinstance(start_s, str) and "," in start_s:
            start_str = start_s
        else:
            start_str = format_srt_timestamp(float(start_s))

        if isinstance(end_s, str) and "," in end_s:
            end_str = end_s
        else:
            end_str = format_srt_timestamp(float(end_s))

        blocks.append(f"{idx}\n{start_str} --> {end_str}\n{txt}\n")
        idx += 1

    return "\n".join(blocks)
