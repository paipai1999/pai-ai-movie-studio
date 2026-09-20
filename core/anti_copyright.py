"""
Platform Anti-Copyright Shield Utilities (မူပိုင်ခွင့် ကာကွယ်ရေး filter စနစ်)
=======================================================================
Provides video and audio filtergraph generators for evading Content ID
fingerprinting algorithms on YouTube, Facebook, TikTok, and Reels.

ဤ module သည် ဗီဒီယိုနှင့် အသံ ဖိုင်များအား မူပိုင်ခွင့် fingerprinting မှ ကာကွယ်ရန်
Mirror (ဘယ်ညာလှည့်)၊ 1.02x Zoom၊ Color Grading EQ နှင့် Audio Tempo Shield
(atempo=1.008) filtergraph များကို စနစ်တကျ တည်ဆောက်ပေးပါသည်။
"""

from typing import List


def build_video_anti_copyright_filters(
    mirror: bool = False,
    color_grading: bool = True,
) -> List[str]:
    """
    Generates video filtergraph components for anti-copyright evasion.
    
    1. Mirror (hflip): Flips video horizontally so frame fingerprint differs.
    2. 1.02x Zoom + Crop: Crops out outermost 2% borders to break exact bounding boxes.
    3. Color Grading EQ: Subtly alters contrast (1.03), brightness (0.01), saturation (1.05).
    
    မူပိုင်ခွင့် ကာကွယ်ရေးအတွက် Video filters (လှည့်ခြင်း၊ ချဲ့ခြင်း၊ အရောင်ချိန်ခြင်း) စာရင်းကို ထုတ်ပေးသည်။
    """
    filters: List[str] = []

    # Step 1: Horizontal Flip if requested
    if mirror:
        filters.append("hflip")

    # Step 2: 1.02x Zoom and Color Grading
    if color_grading:
        # Scale up by 2%, crop back to original dimensions, and adjust color curve
        zoom_crop = "scale=1.02*iw:1.02*ih,crop=iw/1.02:ih/1.02"
        color_eq = "eq=contrast=1.03:brightness=0.01:saturation=1.05"
        filters.append(zoom_crop)
        filters.append(color_eq)

    return filters


def build_audio_anti_copyright_filters(
    audio_shield: bool = False,
) -> List[str]:
    """
    Generates audio filtergraph components for audio Content ID evasion.
    
    Uses atempo=1.008 (subtle 0.8% speedup/perturbation) which is virtually
    imperceptible to human ears, but alters audio acoustic waveforms sufficiently
    to disrupt automated acoustic fingerprint matching algorithms.
    
    အသံ Content ID ရှောင်လွှဲနိုင်ရန် atempo=1.008 audio filter ကို ထည့်သွင်းပေးသည်။
    """
    filters: List[str] = []

    if audio_shield:
        filters.append("atempo=1.008")

    return filters
