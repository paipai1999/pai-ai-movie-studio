import os
import sys
import unittest
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from brain.memory import MovieState

class TestMovieState(unittest.TestCase):

    def test_state_critical_attributes_exist(self):
        """Verify all attributes required by MasterAgent and WebUI exist on MovieState."""
        state = MovieState(movie_name="Sample_Movie")
        self.assertTrue(hasattr(state, "errors"), "MovieState must have 'errors' attribute")
        self.assertTrue(hasattr(state, "warnings"), "MovieState must have 'warnings' attribute")
        self.assertTrue(hasattr(state, "phase_statuses"), "MovieState must have 'phase_statuses' attribute")
        self.assertTrue(hasattr(state, "pipeline_status"), "MovieState must have 'pipeline_status' attribute")
        self.assertTrue(hasattr(state, "phase_durations"), "MovieState must have 'phase_durations' attribute")
        self.assertTrue(hasattr(state, "total_duration_sec"), "MovieState must have 'total_duration_sec' attribute")
        self.assertTrue(hasattr(state, "total_duration_formatted"), "MovieState must have 'total_duration_formatted' attribute")
        self.assertTrue(hasattr(state, "clean_video_path"), "MovieState must have 'clean_video_path' attribute")
        self.assertTrue(hasattr(state, "reels_video_path"), "MovieState must have 'reels_video_path' attribute")

    def test_state_initial_values(self):
        """Verify MovieState default values are correctly typed."""
        state = MovieState(movie_name="Sample_Movie")
        self.assertEqual(state.pipeline_status, "QUEUED")
        self.assertEqual(state.progress, 0)
        self.assertIsInstance(state.errors, list)
        self.assertIsInstance(state.warnings, list)
        self.assertIsInstance(state.phase_statuses, dict)
        self.assertIsInstance(state.phase_durations, dict)

    def test_phase_tracking_lifecycle(self):
        """Verify phase completion tracking and targeted reset."""
        state = MovieState(movie_name="Sample_Movie")
        self.assertFalse(state.is_phase_completed("Phase 1"))
        state.mark_phase_completed("Phase 1", {"summary": "Done"})
        self.assertTrue(state.is_phase_completed("Phase 1"))
        self.assertEqual(state.get_last_completed_phase(), "Phase 1")

        state.mark_phase_completed("Phase 2")
        state.mark_phase_completed("Phase 3")
        self.assertEqual(state.get_last_completed_phase(), "Phase 3")

        # Reset from Phase 2 should remove Phase 2 and Phase 3
        state.reset_from_phase("Phase 2")
        self.assertTrue(state.is_phase_completed("Phase 1"))
        self.assertFalse(state.is_phase_completed("Phase 2"))
        self.assertFalse(state.is_phase_completed("Phase 3"))

    def test_state_json_save_and_load(self):
        """Verify MovieState saves to JSON and reloads with 100% fidelity."""
        state = MovieState(movie_name="Persistence_Test")
        state.errors.append("Test error")
        state.warnings.append("Test warning")
        state.phase_statuses["Phase 1"] = "COMPLETED"
        state.pipeline_status = "COMPLETED"

        with tempfile.TemporaryDirectory() as td:
            filepath = os.path.join(td, "state.json")
            state.save_to_json(filepath)
            self.assertTrue(os.path.exists(filepath))

            loaded = MovieState.load_from_json(filepath)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.movie_name, "Persistence_Test")
            self.assertEqual(loaded.errors, ["Test error"])
            self.assertEqual(loaded.warnings, ["Test warning"])
            self.assertEqual(loaded.pipeline_status, "COMPLETED")
            self.assertEqual(loaded.phase_statuses.get("Phase 1"), "COMPLETED")

    def test_custom_movie_state_sqlite_persistence(self):
        """Verify save_custom_movie_state successfully writes to SQLite and is readable via list_movie_states."""
        from brain.sqlite_store import save_custom_movie_state, load_movie_state, list_movie_states

        with tempfile.TemporaryDirectory() as td:
            save_custom_movie_state(
                project_dir="hardsub_proj_123",
                movie_name="My Hardsub Drama",
                movie_path="movies/drama.mp4",
                language="burmese",
                whisper_model="faster-whisper",
                progress=100,
                current_phase="Completed",
                state_dict={"engine_type": "hardsub", "records": 42},
                output_dir=td
            )

            loaded = load_movie_state("hardsub_proj_123", output_dir=td)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["movie_name"], "My Hardsub Drama")
            self.assertEqual(loaded["language"], "burmese")
            self.assertEqual(loaded["whisper_model"], "faster-whisper")
            self.assertEqual(loaded["state_json"]["engine_type"], "hardsub")
            self.assertEqual(loaded["state_json"]["records"], 42)

            all_states = list_movie_states(output_dir=td)
            self.assertEqual(len(all_states), 1)
            self.assertEqual(all_states[0]["project_dir"], "hardsub_proj_123")


if __name__ == "__main__":
    unittest.main()
