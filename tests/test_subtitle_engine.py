"""
Unit tests for the YouTube Video to Burmese Subtitle & Transcript Engine.
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

from subtitle_engine import (
    SubtitleEngine,
    _format_srt_timestamp,
    _parse_srt_timestamp,
)


class TestSubtitleEngine(unittest.TestCase):

    def setUp(self):
        self.orig_cancel = os.environ.get("CURRENT_JOB_CANCELLED")
        os.environ["CURRENT_JOB_CANCELLED"] = "0"
        self.temp_dir = tempfile.mkdtemp()
        self.engine = SubtitleEngine(output_base_dir=self.temp_dir)

    def tearDown(self):
        if self.orig_cancel is not None:
            os.environ["CURRENT_JOB_CANCELLED"] = self.orig_cancel
        else:
            os.environ.pop("CURRENT_JOB_CANCELLED", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_timestamp_formatting_and_parsing(self):
        """Test timestamp formatting to HH:MM:SS,mmm and reverse parsing."""
        cases = [
            (0.0, "00:00:00,000"),
            (2.5, "00:00:02,500"),
            (68.123, "00:01:08,123"),
            (3665.456, "01:01:05,456"),
        ]
        for sec, expected_str in cases:
            formatted = _format_srt_timestamp(sec)
            self.assertEqual(formatted, expected_str)
            parsed = _parse_srt_timestamp(formatted)
            self.assertAlmostEqual(parsed, sec, places=2)

    def test_parse_srt_file(self):
        """Test parsing an SRT file into structured segment dicts."""
        sample_srt = (
            "1\n"
            "00:00:02,500 --> 00:00:06,800\n"
            "Original spoken sentence 1.\n\n"
            "2\n"
            "00:00:07,100 --> 00:00:10,900\n"
            "Another spoken sentence 2.\n\n"
        )
        srt_path = os.path.join(self.temp_dir, "test.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(sample_srt)

        segments = self.engine._parse_subtitle_file(srt_path)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["no"], 1)
        self.assertEqual(segments[0]["start"], "00:00:02,500")
        self.assertEqual(segments[0]["end"], "00:00:06,800")
        self.assertEqual(segments[0]["original"], "Original spoken sentence 1.")

        self.assertEqual(segments[1]["no"], 2)
        self.assertEqual(segments[1]["start"], "00:00:07,100")
        self.assertEqual(segments[1]["end"], "00:00:10,900")
        self.assertEqual(segments[1]["original"], "Another spoken sentence 2.")

    def test_clean_and_deduplicate_segments(self):
        """Test deduplication of rolling YouTube auto-captions."""
        dup_segments = [
            {"start_s": 0.0, "end_s": 2.0, "original": "Hello world"},
            {"start_s": 1.0, "end_s": 3.0, "original": "Hello world"},  # Duplicate
            {"start_s": 3.0, "end_s": 5.0, "original": "This is new"},
        ]
        cleaned = self.engine._clean_and_deduplicate_segments(dup_segments)
        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned[0]["no"], 1)
        self.assertEqual(cleaned[0]["original"], "Hello world")
        self.assertEqual(cleaned[1]["no"], 2)
        self.assertEqual(cleaned[1]["original"], "This is new")

    def test_language_detection(self):
        """Test language detection for CJK, Burmese, and English."""
        en_segs = [{"original": "Hello, welcome to this movie explanation."}]
        zh_segs = [{"original": "你好，今天我们要讲述一个特别的故事。"}]
        my_segs = [{"original": "မင်္ဂလာပါ ဒီနေ့မှာတော့ ထူးဆန်းတဲ့ ဇာတ်လမ်းကို တင်ဆက်ပေးပါမယ်။"}]

        lang, _ = self.engine._detect_language(en_segs)
        self.assertEqual(lang, "en")

        lang, _ = self.engine._detect_language(zh_segs)
        self.assertEqual(lang, "zh")

        lang, _ = self.engine._detect_language(my_segs)
        self.assertEqual(lang, "my")

    def test_quality_check_report_generation(self):
        """Test that Quality Check produces report and verifies 1:1 timestamps."""
        segments = [
            {
                "no": 1,
                "start_s": 1.0,
                "end_s": 4.0,
                "start": "00:00:01,000",
                "end": "00:00:04,000",
                "original": "This is a test sentence.",
                "english": "This is a test sentence.",
                "burmese": "ဒါက စမ်းသပ်စာကြောင်း ဖြစ်ပါတယ်။",
                "status": "Verified",
            },
            {
                "no": 2,
                "start_s": 4.5,
                "end_s": 8.0,
                "start": "00:00:04,500",
                "end": "00:00:08,000",
                "original": "We are verifying timestamp accuracy.",
                "english": "We are verifying timestamp accuracy.",
                "burmese": "ကျွန်တော်တို့ အချိန်မှတ် တိကျမှုကို စစ်ဆေးနေပါတယ်။",
                "status": "Verified",
            },
        ]
        meta = {"title": "Test Video", "duration": 10.0}
        report, passed = self.engine._perform_quality_check(
            segments,
            video_path=os.path.join(self.temp_dir, "01_video_original.mp4"),
            video_metadata=meta,
            sub_source_type="Test Harness",
            detected_lang="en"
        )
        self.assertTrue(passed)
        self.assertIn("[PASS] Exact 1:1 Match", report)
        self.assertIn("[APPROVED] Production-Ready", report)
        self.assertIn("00:00:01,000", report)

    def test_deliverables_output_creation(self):
        """Verify that all 6 required deliverables + records_data.json are written."""
        proj_dir = os.path.join(self.temp_dir, "test_proj")
        os.makedirs(proj_dir, exist_ok=True)
        # Create dummy 01_video_original.mp4
        dummy_video = os.path.join(proj_dir, "01_video_original.mp4")
        with open(dummy_video, "w") as f:
            f.write("dummy video data")

        segments = [
            {
                "no": 1,
                "start_s": 2.0,
                "end_s": 5.0,
                "start": "00:00:02,000",
                "end": "00:00:05,000",
                "original": "Hello world.",
                "english": "Hello world.",
                "burmese": "မင်္ဂလာပါ ကမ္ဘာကြီး။",
                "status": "Verified",
            }
        ]
        qc_report = "QUALITY CHECK REPORT DUMMY CONTENT"

        files = self.engine._write_deliverable_files(proj_dir, segments, qc_report)

        # Check all 6 files
        self.assertTrue(os.path.exists(files["01_video_original"]))
        self.assertTrue(os.path.exists(files["02_transcript_original"]))
        self.assertTrue(os.path.exists(files["03_transcript_english"]))
        self.assertTrue(os.path.exists(files["04_transcript_burmese"]))
        self.assertTrue(os.path.exists(files["05_subtitle_burmese"]))
        self.assertTrue(os.path.exists(files["06_quality_check_report"]))
        self.assertTrue(os.path.exists(files["records_data_json"]))

        # Verify SRT format in 05_subtitle_burmese.srt
        with open(files["05_subtitle_burmese"], "r", encoding="utf-8") as f:
            srt_content = f.read()
            self.assertIn("1\n00:00:02,000 --> 00:00:05,000\nမင်္ဂလာပါ ကမ္ဘာကြီး။", srt_content)

    def test_clean_subtitle_text_strips_quotes(self):
        """Verify that _clean_subtitle_text strips all straight and curly quotes."""
        cases = [
            ('"ညီမလေးရေ... နင့်ကို ဘယ်သူမှ မယူရင်တော့"', "ညီမလေးရေ... နင့်ကို ဘယ်သူမှ မယူရင်တော့"),
            ('“ဒီလိုဟာမျိုးကို!” လို့ အော်ငေါက်ကြပါတယ်။', "ဒီလိုဟာမျိုးကို! လို့ အော်ငေါက်ကြပါတယ်။"),
            ("1. 'အိုးကို သွားကိုင်ရဲရတာလဲ'", "အိုးကို သွားကိုင်ရဲရတာလဲ"),
            ("Line 5: “သုံးခါဆူအောင် ကျိုရတယ်” လို့ သူမက ပြန်ဖြေလိုက်ပါတယ်။", "သုံးခါဆူအောင် ကျိုရတယ် လို့ သူမက ပြန်ဖြေလိုက်ပါတယ်။"),
        ]
        for raw, expected in cases:
            cleaned = self.engine._clean_subtitle_text(raw)
            self.assertEqual(cleaned, expected)
            self.assertNotIn('"', cleaned)
            self.assertNotIn('“', cleaned)
            self.assertNotIn('”', cleaned)
            self.assertNotIn("'", cleaned)

    @patch("subtitle_engine.call_gemini")
    def test_translate_segments_resilient_partial(self, mock_gemini):
        """Test resilient partial translation in subtitle_engine when LLM returns 1 item instead of 2."""
        mock_gemini.return_value = ('["တစ်ရက်မှာတော့ သူမ ထွက်လာခဲ့တယ်။"]', 0)
        segments = [
            {"id": 1, "original": "One day she came out.", "english": "One day she came out."},
            {"id": 2, "original": "She looked around.", "english": "She looked around."},
        ]
        self.engine._translate_to_burmese(segments, "en")
        self.assertEqual(segments[0]["burmese"], "တစ်ရက်မှာတော့ သူမ ထွက်လာခဲ့တယ်။")
        # Second item should safely fallback to english rather than reverting the first
        self.assertEqual(segments[1]["burmese"], "She looked around.")

    def test_subtitle_engine_cancellation(self):
        """Verify SubtitleEngine raises InterruptedError when cancel_event is set."""
        import threading
        evt = threading.Event()
        sub_engine = SubtitleEngine(output_base_dir=self.temp_dir, cancel_event=evt)
        # Initially not cancelled
        sub_engine._check_cancellation()
        # Set cancel event
        evt.set()
        with self.assertRaises(InterruptedError):
            sub_engine._check_cancellation()


if __name__ == "__main__":
    unittest.main()
