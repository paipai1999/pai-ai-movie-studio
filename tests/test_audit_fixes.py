"""
Automated tests verifying comprehensive audit fixes.
"""
import unittest
from unittest.mock import patch, MagicMock
from brain.memory import MovieState, TranscriptSegment
from brain.gemini_client import _FALLBACK_MODELS
from agents.qa_agent import QAAgent
from agents.audio_agent import AudioAgent


class TestAuditFixes(unittest.TestCase):

    def test_movie_state_subtitles_burned_flag(self):
        """Verify subtitles_burned exists on MovieState and defaults to False."""
        state = MovieState(movie_name="AuditTest")
        self.assertFalse(state.subtitles_burned)
        state.subtitles_burned = True
        self.assertTrue(state.subtitles_burned)

    def test_gemini_fallback_models_include_production(self):
        """Verify _FALLBACK_MODELS includes standard Google AI Studio production models."""
        for required_model in ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.5-flash"]:
            self.assertIn(required_model, _FALLBACK_MODELS)

    def test_qa_agent_scene_id_collision_prevention(self):
        """Verify QAAgent does not collide 'scene_1' and 'action_bridge_1' into '1'."""
        qa = QAAgent()
        state = MovieState(movie_name="CollisionTest")
        state.language = "english"
        state.generated_script = [
            {
                "scene_id": "scene_1",
                "narration": "Original narration for main scene 1 which is very long and needs to be shortened significantly to fit timing.",
                "start_sec": 0.0,
                "end_sec": 2.0,
            },
            {
                "scene_id": "action_bridge_1",
                "narration": "Original narration for bridge 1 which is also quite long and exceeds the allowed duration.",
                "start_sec": 2.0,
                "end_sec": 4.0,
            }
        ]

        fake_llm_response = """
        [
            {"scene_id": "scene_1", "rewritten_narration": "Short scene 1."},
            {"scene_id": "action_bridge_1", "rewritten_narration": "Short bridge 1."}
        ]
        """
        with patch("brain.gemini_client.call_gemini", return_value=(fake_llm_response, None)):
            with patch("brain.config.load_config", return_value={"gemini": {"enabled": True, "api_keys": ["fake-key"]}}):
                updated_state = qa.enforce_duration_constraints(state)

        # Both should have their OWN distinct rewritten narration
        script = updated_state.generated_script
        self.assertEqual(script[0]["narration"], "Short scene 1.")
        self.assertEqual(script[1]["narration"], "Short bridge 1.")

    def test_audio_agent_correct_transcript_preserves_all_segments(self):
        """Verify correct_transcript does not truncate large transcripts and preserves all segments."""
        state = MovieState(movie_name="TruncationTest")
        # Create 150 segments (which would previously exceed 40000 chars if long or get truncated)
        original_segments = [
            TranscriptSegment(start=float(i * 3), end=float(i * 3 + 2.5), text=f"Dialogue segment {i}")
            for i in range(150)
        ]
        state.transcript = list(original_segments)

        # Mock call_gemini to simulate a batch returning corrected text for each chunk
        def mock_call_gemini(sys_p, user_p, api_key, model=None, temperature=None):
            import re
            lines = re.findall(r'\[([\d.]+)-([\d.]+)\]\s*(.*)', user_p)
            segments_json = [{"start": float(l[0]), "end": float(l[1]), "text": f"Corrected {l[2]}"} for l in lines]
            import json
            return json.dumps(segments_json), None

        with patch("brain.gemini_client.call_gemini", side_effect=mock_call_gemini):
            with patch("brain.config.load_config", return_value={"gemini": {"enabled": True, "api_keys": ["fake-key"]}}):
                audio_agent = AudioAgent("dummy_path.mp4")
                res_state = audio_agent.correct_transcript(state)

        self.assertEqual(len(res_state.transcript), 150)
        self.assertTrue(res_state.transcript[0].text.startswith("Corrected Dialogue segment 0"))
        self.assertTrue(res_state.transcript[149].text.startswith("Corrected Dialogue segment 149"))

    def test_downloader_agent_none_filename_guard(self):
        """Verify DownloaderAgent handles None filename without raising TypeError."""
        from agents.downloader_agent import DownloaderAgent
        dl = DownloaderAgent(output_dir="temp_test_dl")
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_instance = MagicMock()
            mock_ydl_cls.return_value.__enter__.return_value = mock_instance
            mock_instance.extract_info.return_value = {"title": "dummy_video"}
            mock_instance.prepare_filename.return_value = None

            with self.assertRaises(FileNotFoundError) as ctx:
                dl.download_video("https://youtube.com/watch?v=dummy123")
            self.assertIn("Download seemed to succeed but file not found", str(ctx.exception))

    def test_qa_agent_review_model_workhorse_defined(self):
        """Verify QAAgent.review does not raise NameError for model_workhorse during language check."""
        qa = QAAgent()
        state = MovieState(movie_name="ModelWorkhorseTest")
        state.generated_script = [{"scene_id": "1", "narration": "မင်္ဂလာပါ။"}]
        cfg_mock = {
            "gemini": {
                "enabled": True,
                "api_keys": ["fake-key"],
                "models": {"workhorse": "gemini-3.5-flash-lite"}
            },
            "qa": {
                "enabled": True,
                "skip_video_qa": True,
                "language_check": True,
                "sync_check": False
            }
        }
        with patch("brain.config.load_config", return_value=cfg_mock):
            with patch.object(qa, "_run_language_check", return_value={"overall_language_score": 8, "blocks": []}):
                with patch.object(qa, "_save_reports"):
                    reviewed = qa.review(state, "dummy_orig.mp4", "dummy_recap.mp4")
                    self.assertIsNotNone(reviewed.qa_results)
                    self.assertEqual(reviewed.qa_results.get("language", {}).get("overall_language_score"), 8)


if __name__ == "__main__":
    unittest.main()
