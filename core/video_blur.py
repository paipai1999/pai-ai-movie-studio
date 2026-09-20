"""
Vision AI Subtitle Blur Utilities (စာတန်းဟောင်း Blur လုပ်ခြင်း Utility စနစ်)
========================================================================
Calculates bounding box coordinates and generates FFmpeg filtergraph strings
for blurring existing hardcoded burnt-in subtitles in source videos.

ဤ module သည် မူရင်းဗီဒီယိုတွင် ပါရှိပြီးသား စာတန်းဟောင်းများကို Vision AI ဖြင့်
ရှာဖွေကာ အောက်ခြေ သတ်မှတ်ရာခိုင်နှုန်းကို boxblur ပြုလုပ်ပေးသည့် filter ကို ဖန်တီးပေးပါသည်။
"""

from typing import Tuple, Optional


def calculate_blur_box(
    blur_mode: str = "auto",
    blur_height: Optional[float] = None,
    default_height: float = 0.18,
) -> Tuple[float, float, bool]:
    """
    Calculates the vertical start position (start_y_pct), height (height_pct),
    and whether blur should be active (do_blur).
    
    Parameters:
    - blur_mode: 'auto', 'force', or 'disabled' / 'none'
    - blur_height: User-specified height percentage (e.g. 0.12, 0.18, 0.25)
    - default_height: Default blur height if none specified (default 0.18 = 18%)
    
    Returns:
    - (start_y_pct, height_pct, do_blur)
    
    Blur ပြုလုပ်မည့် အမြင့်ရာခိုင်နှုန်းနှင့် စတင်မည့် Y နေရာကို တွက်ချက်ပေးသည်။
    """
    mode = str(blur_mode or "auto").strip().lower()
    if mode in ("disabled", "none", "off", "false"):
        return (0.0, 0.0, False)

    # Resolve height percentage (clamp between 5% and 40%)
    h_pct = float(blur_height if blur_height is not None else default_height)
    h_pct = max(0.05, min(0.40, h_pct))

    # Calculate starting Y coordinate (bottom aligned)
    start_y_pct = round(1.0 - h_pct, 4)
    do_blur = True

    return (start_y_pct, h_pct, do_blur)


def build_boxblur_filter(
    start_y_pct: float,
    height_pct: float,
    luma_radius: int = 18,
    luma_power: int = 3,
) -> Tuple[str, str]:
    """
    Generates the FFmpeg crop, boxblur, and overlay filter expressions.
    
    Returns:
    - (crop_and_blur_filter, overlay_expression)
    
    FFmpeg အတွက် crop နှင့် boxblur filter အဆင့်များကို တည်ဆောက်ပေးသည်။
    """
    crop_blur = (
        f"crop=iw:ih*{height_pct:.4f}:0:ih*{start_y_pct:.4f},"
        f"boxblur=luma_radius={luma_radius}:luma_power={luma_power}"
    )
    overlay_pos = f"0:H*{start_y_pct:.4f}"
    return crop_blur, overlay_pos
