import os
import sys
import unittest
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.master import MasterAgent
from brain.planner import BatchProcessor

class TestCancellation(unittest.TestCase):

    def setUp(self):
        self.orig_cancel_env = os.environ.get("CURRENT_JOB_CANCELLED")
        os.environ["CURRENT_JOB_CANCELLED"] = "0"

    def tearDown(self):
        os.environ["CURRENT_JOB_CANCELLED"] = "0"

    def test_master_agent_init_not_cancelled(self):
        """Verify MasterAgent starts in non-cancelled state."""
        evt = threading.Event()
        agent = MasterAgent("movies/dummy.mp4", cancel_event=evt)
        self.assertFalse(agent._is_cancelled())

    def test_master_agent_threading_event_triggers_cancel(self):
        """Verify setting cancel_event triggers _is_cancelled immediately."""
        evt = threading.Event()
        agent = MasterAgent("movies/dummy.mp4", cancel_event=evt)
        self.assertFalse(agent._is_cancelled())
        evt.set()
        self.assertTrue(agent._is_cancelled())

    def test_master_agent_env_var_triggers_cancel(self):
        """Verify setting CURRENT_JOB_CANCELLED env variable triggers _is_cancelled."""
        agent = MasterAgent("movies/dummy.mp4")
        self.assertFalse(agent._is_cancelled())
        os.environ["CURRENT_JOB_CANCELLED"] = "1"
        self.assertTrue(agent._is_cancelled())

    def test_master_agent_phase_raises_on_cancel(self):
        """Verify _phase() raises InterruptedError and sets CANCELLED status when stopped."""
        evt = threading.Event()
        agent = MasterAgent("movies/dummy.mp4", cancel_event=evt)
        evt.set()
        with self.assertRaises(InterruptedError):
            agent._phase("Phase 1: Video & Metadata Analysis")
        self.assertEqual(agent.state.pipeline_status, "CANCELLED")

    def test_batch_processor_cancel_event_binding(self):
        """Verify BatchProcessor correctly binds and stores cancel_event."""
        evt = threading.Event()
        proc = BatchProcessor(cancel_event=evt)
        self.assertIs(proc.cancel_event, evt)

if __name__ == "__main__":
    unittest.main()
