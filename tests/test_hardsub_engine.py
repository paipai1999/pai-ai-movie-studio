"""
Unit tests for HardsubEngine (100% Original Audio & Burmese Hardsub Studio).
"""

import os
import sys
import unittest
import tempfile
import shutil
from unittest.mock import patch

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from hardsub_engine import (
    HardsubEngine,
    _format_srt_timestamp,
    _parse_srt_timestamp,
    _format_ass_timestamp,
    _get_safe_ascii_id,
)
from brain.prompts import HARDSUB_BURMESE_TRANSLATION_SYSTEM_PROMPT


class TestHardsubEngine(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.engine = HardsubEngine(output_base_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_safe_ascii_id(self):
        """Test generating ASCII-safe unique IDs for ffmpeg filters on Windows."""
        res1 = _get_safe_ascii_id("မြန်မာရုပ်ရှင်_2026")
        self.assertTrue(res1.isascii())
        self.assertTrue(all(c.isalnum() or c == '_' for c in res1))

        res2 = _get_safe_ascii_id("My Movie $!#")
        self.assertTrue(res2.isascii())
        self.assertTrue(all(c.isalnum() or c == '_' for c in res2))

    def test_timestamp_conversions(self):
        """Test timestamp formatting to SRT and ASS time formats."""
        sec = 125.750  # 02:05.750
        srt_time = _format_srt_timestamp(sec)
        self.assertEqual(srt_time, "00:02:05,750")

        parsed = _parse_srt_timestamp(srt_time)
        self.assertAlmostEqual(parsed, sec, places=2)

        ass_time_str = _format_ass_timestamp("00:02:05,750")
        self.assertEqual(ass_time_str, "0:02:05.75")

        ass_time_float = _format_ass_timestamp(sec)
        self.assertEqual(ass_time_float, "0:02:05.75")

    def test_ass_file_generation_16x9(self):
        """Test ASS subtitle file creation for 16:9 Landscape."""
        segments = [
            {
                "id": 1,
                "start": 1.0,
                "end": 4.5,
                "burmese": "ကျနော် သတိပေးလိုက်မယ်နော် ခင်ဗျာ။",
            },
            {
                "id": 2,
                "start": 5.0,
                "end": 8.0,
                "burmese": "ကျွန်မ သိပါတယ်ရှင်။",
            }
        ]
        ass_path = os.path.join(self.temp_dir, "test_16_9.ass")
        self.engine._generate_ass_file(segments, ass_path, video_w=1920, video_h=1080, preset="box_black")

        self.assertTrue(os.path.exists(ass_path))
        with open(ass_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("PlayResX: 1920", content)
        self.assertIn("PlayResY: 1080", content)
        self.assertIn("Dialogue: 0,0:00:01.00,0:00:04.50", content)
        self.assertIn("ကျနော် သတိပေးလိုက်မယ်နော်", content)
        self.assertIn("ခင်ဗျာ။", content)
        self.assertIn("ကျွန်မ သိပါတယ်ရှင်။", content)

    def test_ass_file_generation_9x16_vertical(self):
        """Test ASS subtitle file creation for 9:16 Vertical Reels Canvas."""
        segments = [
            {
                "id": 1,
                "start": 1.0,
                "end": 3.0,
                "burmese": "ဖေဖေ သား ဗိုက်ဆာတယ်ဗျာ။",
            }
        ]
        ass_path = os.path.join(self.temp_dir, "test_9_16.ass")
        self.engine._generate_ass_file(segments, ass_path, video_w=1080, video_h=1920, preset="yellow_pop")

        self.assertTrue(os.path.exists(ass_path))
        with open(ass_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("PlayResX: 1080", content)
        self.assertIn("PlayResY: 1920", content)
        self.assertIn("ဖေဖေ သား ဗိုက်ဆာတယ်ဗျာ။", content)

    def test_prompts_gender_persona_instructions(self):
        """Test that the system prompt strictly contains speaker persona rules."""
        prompt = HARDSUB_BURMESE_TRANSLATION_SYSTEM_PROMPT
        self.assertIn("ကျနော်", prompt)
        self.assertIn("ခင်ဗျာ", prompt)
        self.assertIn("ကျွန်မ", prompt)
        self.assertIn("ရှင်", prompt)
        self.assertIn("သား", prompt)
        self.assertIn("သမီး", prompt)
        self.assertIn("1:1", prompt)

    @patch("hardsub_engine.call_gemini")
    def test_dialogue_translation_mock(self, mock_gemini):
        """Test dialogue translation with mocked Gemini persona response."""
        self.engine.config_data = {
            "gemini": {
                "api_keys": ["test_key_12345"],
                "models": {"workhorse": "gemini-3.5-flash-lite"}
            }
        }
        mock_gemini.return_value = (
            '[\n'
            '  {"id": 1, "burmese": "မင်္ဂလာပါ ခင်ဗျာ၊ ကျနော်ကတော့ မင်းသားပါ။", "gender": "male"},\n'
            '  {"id": 2, "burmese": "ဟုတ်ကဲ့ပါရှင်၊ ကျွန်မ ကူညီပေးပါ့မယ်။", "gender": "female"}\n'
            ']',
            "gemini-3.5-flash-lite"
        )

        raw_segments = [
            {"id": 1, "start": 1.0, "end": 3.0, "start_ts": "00:00:01,000", "end_ts": "00:00:03,000", "original": "Hello sir, I am the hero.", "burmese": ""},
            {"id": 2, "start": 3.5, "end": 5.5, "start_ts": "00:00:03,500", "end_ts": "00:00:05,500", "original": "Yes, I will help you.", "burmese": ""},
        ]

        translated = self.engine._translate_dialogue(raw_segments, source_language="en")
        self.assertEqual(len(translated), 2)
        self.assertEqual(translated[0]["burmese"], "မင်္ဂလာပါ ခင်ဗျာ၊ ကျနော်ကတော့ မင်းသားပါ။")
        self.assertEqual(translated[0]["speaker_gender"], "male")
        self.assertEqual(translated[1]["burmese"], "ဟုတ်ကဲ့ပါရှင်၊ ကျွန်မ ကူညီပေးပါ့မယ်။")
        self.assertEqual(translated[1]["speaker_gender"], "female")

    def test_save_artifacts_and_reports(self):
        """Test saving SRT, JSON records, state.json, and audit quality report."""
        project_dir = os.path.join(self.temp_dir, "test_proj")
        os.makedirs(project_dir, exist_ok=True)

        segments = [
            {"id": 1, "start": 1.0, "end": 3.0, "start_ts": "00:00:01,000", "end_ts": "00:00:03,000", "original": "I am coming sir.", "burmese": "ကျနော် လာပါပြီ ခင်ဗျာ။", "speaker_gender": "male"},
            {"id": 2, "start": 4.0, "end": 6.0, "start_ts": "00:00:04,000", "end_ts": "00:00:06,000", "original": "I understand.", "burmese": "ကျွန်မ နားလည်ပါတယ်ရှင်။", "speaker_gender": "female"},
            {"id": 3, "start": 7.0, "end": 9.0, "start_ts": "00:00:07,000", "end_ts": "00:00:09,000", "original": "Dad!", "burmese": "ဖေဖေ သားပါဗျာ။", "speaker_gender": "child"},
        ]
        video_meta = {"duration": 10.0, "width": 1920, "height": 1080}

        self.engine._export_reports(project_dir, "My Movie", segments, video_meta, "whisper")

        srt_file = os.path.join(project_dir, "05_subtitle_burmese.srt")
        json_file = os.path.join(project_dir, "records_data.json")
        state_file = os.path.join(project_dir, "state.json")
        qc_file = os.path.join(project_dir, "06_translation_qc_report.txt")

        self.assertTrue(os.path.exists(srt_file))
        self.assertTrue(os.path.exists(json_file))
        self.assertTrue(os.path.exists(state_file))
        self.assertTrue(os.path.exists(qc_file))

        with open(qc_file, "r", encoding="utf-8") as f:
            qc_content = f.read()
        self.assertIn("Total Dialogue Records : 3", qc_content)
        self.assertIn("100% Original Audio Preserved", qc_content)
        self.assertIn("Male Personas Detected : 1", qc_content)
        self.assertIn("Female Personas Detected: 1", qc_content)
        self.assertIn("Child Personas Detected: 1", qc_content)

    def test_custom_blur_height(self):
        """Test that custom_blur_height accurately scales the blur region dimensions."""
        video_path = os.path.join(self.temp_dir, "dummy.mp4")
        with open(video_path, "wb") as f:
            f.write(b"0")

        # Test with 25% height
        eff_y_25, eff_h_25, do_blur_25 = self.engine._detect_subtitle_blur_region(
            video_path,
            blur_mode="yes",
            custom_blur_height=0.25
        )
        self.assertTrue(do_blur_25)
        self.assertAlmostEqual(eff_h_25, 0.25)
        self.assertAlmostEqual(eff_y_25, 0.75)

        # Test with 12% compact height
        eff_y_12, eff_h_12, do_blur_12 = self.engine._detect_subtitle_blur_region(
            video_path,
            blur_mode="yes",
            custom_blur_height=0.12
        )
        self.assertTrue(do_blur_12)
        self.assertAlmostEqual(eff_h_12, 0.12)
        self.assertAlmostEqual(eff_y_12, 0.88)

    @patch("subprocess.run")
    def test_render_hardsub_audio_anti_copyright(self, mock_run):
        """Test that audio_anti_copyright injects atempo=1.008 into FFmpeg filter_complex."""
        video_in = os.path.join(self.temp_dir, "in.mp4")
        video_out = os.path.join(self.temp_dir, "out.mp4")
        ass_path = os.path.join(self.temp_dir, "sub.ass")
        for p in [video_in, ass_path]:
            with open(p, "w", encoding="utf-8") as f:
                f.write("content")

        blur_info = (0.82, 0.18, False)

        # 1. With audio_anti_copyright=True
        self.engine._render_hardsub_video(
            video_path=video_in,
            output_path=video_out,
            ass_path=ass_path,
            blur_info=blur_info,
            aspect_ratio="16:9",
            resolution="1080p",
            color_grading=False,
            mirror=False,
            audio_anti_copyright=True
        )
        called_cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(called_cmd)
        self.assertIn("atempo=1.008", cmd_str)
        self.assertIn("[aout]", cmd_str)

        # 2. With audio_anti_copyright=False
        self.engine._render_hardsub_video(
            video_path=video_in,
            output_path=video_out,
            ass_path=ass_path,
            blur_info=blur_info,
            aspect_ratio="16:9",
            resolution="1080p",
            color_grading=False,
            mirror=False,
            audio_anti_copyright=False
        )
        called_cmd_plain = mock_run.call_args[0][0]
        cmd_str_plain = " ".join(called_cmd_plain)
        self.assertNotIn("atempo=1.008", cmd_str_plain)
        self.assertIn("-map 0:a?", cmd_str_plain)

    def test_export_reports_saves_ass(self):
        """Test that _export_reports copies the ASS file to 05_subtitle_burmese.ass."""
        proj_dir = os.path.join(self.temp_dir, "proj_test")
        os.makedirs(proj_dir, exist_ok=True)
        sample_ass = os.path.join(self.temp_dir, "temp_sub.ass")
        with open(sample_ass, "w", encoding="utf-8") as f:
            f.write("[Script Info]\nTitle: Test ASS")

        segments = [{"id": 1, "start": 0.0, "end": 2.0, "start_ts": "00:00:00,000", "end_ts": "00:00:02,000", "burmese": "စမ်းသပ်ချက်"}]
        meta = {"duration": 2.0}
        self.engine._export_reports(proj_dir, "test_movie", segments, meta, "whisper", ass_path=sample_ass)

        target_ass = os.path.join(proj_dir, "05_subtitle_burmese.ass")
        self.assertTrue(os.path.exists(target_ass))
        with open(target_ass, "r", encoding="utf-8") as f:
            self.assertIn("[Script Info]", f.read())

    @patch("hardsub_engine.call_gemini")
    def test_translate_dialogue_resilient_partial(self, mock_gemini):
        """Test resilient translation mapping when LLM returns 1 item instead of 2 on retry."""
        # Mock Gemini returning 1 item for a 2-item chunk
        mock_gemini.return_value = ('[{"id": 1, "burmese": "ကျနော် သိပါပြီ ခင်ဗျာ။", "speaker_gender": "male"}]', 0)
        segments = [
            {"id": 1, "original": "I understand sir.", "start": 0.0, "end": 2.0},
            {"id": 2, "original": "Thank you.", "start": 2.1, "end": 4.0},
        ]
        res = self.engine._translate_dialogue(segments)
        self.assertEqual(res[0]["burmese"], "ကျနော် သိပါပြီ ခင်ဗျာ။")
        self.assertEqual(res[0]["speaker_gender"], "male")
        # Item 2 should have safe fallback to original text instead of dropping item 1
        self.assertEqual(res[1]["burmese"], "Thank you.")

    @patch("subprocess.run")
    def test_render_hardsub_escapes_special_chars(self, mock_run):
        """Test that filenames with special characters (quotes, colons) are escaped in subtitles filter."""
        video_in = os.path.join(self.temp_dir, "in.mp4")
        video_out = os.path.join(self.temp_dir, "out.mp4")
        # Filename with single quote
        ass_path = os.path.join(self.temp_dir, "sub'test:special.ass")
        for p in [video_in, ass_path]:
            with open(p, "w", encoding="utf-8") as f:
                f.write("content")

        self.engine._render_hardsub_video(
            video_path=video_in,
            output_path=video_out,
            ass_path=ass_path,
            blur_info=(0.8, 0.2, False),
            aspect_ratio="16:9",
            resolution="1080p",
        )
        called_cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(called_cmd)
        self.assertIn(r"sub\'test\:special.ass", cmd_str)


if __name__ == "__main__":
    unittest.main()

