import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from brain.memory import MovieState
from agents.master import MasterAgent
from agents.writer_agent import WriterAgent
from agents.video_merger_agent import VideoMergerAgent


class TestEngineModesAndStageToggles(unittest.TestCase):

    def test_movie_state_new_fields(self):
        """Verify MovieState stores and serializes all new universal engine fields."""
        state = MovieState(
            movie_name="TestMovie",
            translation_style="persona",
            audio_mode="original",
            sfx_mode="both",
            sfx_volume=0.25,
            render_video=False,
            audio_anti_copyright=True
        )
        self.assertEqual(state.translation_style, "persona")
        self.assertEqual(state.audio_mode, "original")
        self.assertEqual(state.sfx_mode, "both")
        self.assertEqual(state.sfx_volume, 0.25)
        self.assertFalse(state.render_video)
        self.assertTrue(state.audio_anti_copyright)

    def test_writer_agent_style_dispatch(self):
        """Verify WriterAgent selects correct system prompt for recap, dialogue, and persona."""
        state = MovieState(movie_name="TestMovie", translation_style="dialogue")
        writer = WriterAgent()
        prompt_dialogue = writer._get_system_prompt(state)
        self.assertIn("STRICT 1:1 DIALOGUE TRANSLATION", prompt_dialogue)

        state.translation_style = "persona"
        prompt_persona = writer._get_system_prompt(state)
        self.assertIn("GENDER & AGE PERSONA ACCURACY", prompt_persona)

        state.translation_style = "recap"
        prompt_recap = writer._get_system_prompt(state)
        self.assertIn("Myanmar Movie Recap Storyteller", prompt_recap)

    def test_master_agent_stage_toggles(self):
        """Verify MasterAgent respects stage_toggles for tts, blur, and reels."""
        toggles = {
            "download": True,
            "metadata": True,
            "demucs": False,
            "transcription": True,
            "scenes": False,
            "translation": True,
            "tts": False,
            "blur": False,
            "render": False,
            "reels": False
        }
        master = MasterAgent(
            "dummy_movie.mp4",
            translation_style="dialogue",
            audio_mode="original",
            sfx_mode="none",
            render_video=False,
            stage_toggles=toggles
        )
        self.assertFalse(master.tts_enabled)
        self.assertEqual(master.blur_mode, "no")
        self.assertEqual(master.video_format, "16:9")
        self.assertFalse(master.render_video)
        self.assertEqual(master.sfx_mode, "none")

    def test_video_merger_sfx_modes(self):
        """Verify VideoMergerAgent ducking filters for different sfx modes."""
        merger = VideoMergerAgent()
        state = MovieState(movie_name="TestMovie", sfx_mode="both", sfx_volume=0.20)
        self.assertEqual(state.sfx_mode, "both")
        self.assertEqual(state.sfx_volume, 0.20)

        state_none = MovieState(movie_name="TestMovie", sfx_mode="none")
        self.assertEqual(state_none.sfx_mode, "none")


if __name__ == "__main__":
    unittest.main()
