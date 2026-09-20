import os
import sys
import unittest
import time
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from web_ui import (
    list_raw_keys,
    save_keys,
    SaveKeysRequest,
    _cleanup_old_jobs,
    jobs,
    jobs_lock,
    JOB_RETENTION_SECONDS,
)


class TestWebAPISecurityAndLifecycle(unittest.TestCase):

    def test_list_raw_keys_is_masked(self):
        """Verify list_raw_keys() returns masked keys and never exposes full plaintext API keys."""
        dummy_keys = ["AIzaSyA1234567890abcdefghijklmnopq", "AIzaSyB9876543210zyxwvutsrqponmlkj"]
        with patch("brain.config.load_config", return_value={"gemini": {"api_keys": dummy_keys}}):
            data = list_raw_keys()
            returned_keys = data["keys"]
            self.assertEqual(len(returned_keys), 2)
            for k in returned_keys:
                self.assertIn("...", k)
                self.assertTrue(k.startswith("AIzaSy"))
                # Key must NOT contain full sensitive middle portion
                self.assertNotIn("1234567890abcdef", k)
                self.assertNotIn("9876543210zyxwvu", k)

    def test_save_keys_reconciles_masked_keys(self):
        """Verify save_keys resolves masked keys back to their original full keys without losing data."""
        real_key_1 = "AIzaSyOriginalKeyNumberOne9999XYZ"
        real_key_2 = "AIzaSyOriginalKeyNumberTwo8888ABC"
        
        with patch("brain.config.load_config", return_value={"gemini": {"api_keys": [real_key_1, real_key_2]}}):
            with patch("brain.config.save_config") as mock_save:
                # User submits the masked version of key 1, plus a brand-new raw key 3
                masked_key_1 = real_key_1[:6] + "..." + real_key_1[-4:]
                new_key_3 = "AIzaSyBrandNewKeyNumberThree7777"
                
                req = SaveKeysRequest(keys=[masked_key_1, new_key_3])
                res = save_keys(req)
                
                self.assertTrue(res["success"])
                saved_config = mock_save.call_args[0][0]
                saved_keys = saved_config["gemini"]["api_keys"]
                
                # Masked key 1 should have been resolved to full real_key_1
                self.assertIn(real_key_1, saved_keys)
                self.assertIn(new_key_3, saved_keys)
                self.assertNotIn(real_key_2, saved_keys)  # user omitted key 2, so it got removed

    def test_cleanup_old_jobs_includes_cancelled(self):
        """Verify _cleanup_old_jobs purges cancelled jobs older than retention window."""
        old_time = time.time() - (JOB_RETENTION_SECONDS + 100)
        with jobs_lock:
            jobs["test_cancelled_job"] = {
                "status": "cancelled",
                "phase": "Stopped by user",
                "created_at": old_time
            }
            jobs["test_recent_cancelled_job"] = {
                "status": "cancelled",
                "phase": "Stopped by user",
                "created_at": time.time()
            }
            
            _cleanup_old_jobs()
            
            self.assertNotIn("test_cancelled_job", jobs)
            self.assertIn("test_recent_cancelled_job", jobs)
            
            # Clean up
            jobs.pop("test_recent_cancelled_job", None)

    def test_cors_credentials_disabled(self):
        """Verify CORS allow_credentials is False to comply with W3C spec for wildcard origins."""
        from web_ui import app
        cors_middlewares = [m for m in app.user_middleware if "CORSMiddleware" in str(m.cls)]
        if cors_middlewares:
            cors_kw = cors_middlewares[0].kwargs
            self.assertFalse(cors_kw.get("allow_credentials", True))

    def test_web_ui_password_auth_protection(self):
        """Verify WEB_UI_PASSWORD blocks unauthenticated requests with HTTP 401."""
        from web_ui import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        
        old_pw = os.environ.get("WEB_UI_PASSWORD")
        try:
            os.environ["WEB_UI_PASSWORD"] = "SecretPassword123"
            
            # Unauthenticated request should get 401
            res = client.get("/api/config")
            self.assertEqual(res.status_code, 401)

            # Authenticated with query param
            res_auth = client.get("/api/config?token=SecretPassword123")
            self.assertEqual(res_auth.status_code, 200)

            # Authenticated with Bearer header
            res_hdr = client.get("/api/config", headers={"Authorization": "Bearer SecretPassword123"})
            self.assertEqual(res_hdr.status_code, 200)
        finally:
            if old_pw:
                os.environ["WEB_UI_PASSWORD"] = old_pw
            else:
                os.environ.pop("WEB_UI_PASSWORD", None)

    def test_preview_subtitle_hardsub_qc_report(self):
        """Verify /api/subtitle/preview/{movie_name} finds 06_translation_qc_report.txt from HardsubEngine."""
        from web_ui import app
        from fastapi.testclient import TestClient
        client = TestClient(app)

        test_proj = os.path.join("outputs", "test_hardsub_qc_proj")
        os.makedirs(test_proj, exist_ok=True)
        qc_file = os.path.join(test_proj, "06_translation_qc_report.txt")
        with open(qc_file, "w", encoding="utf-8") as f:
            f.write("HARDSUB STUDIO QUALITY CHECK REPORT SAMPLE")

        try:
            res = client.get("/api/subtitle/preview/test_hardsub_qc_proj")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("HARDSUB STUDIO QUALITY CHECK REPORT SAMPLE", data.get("qc_report", ""))
        finally:
            import shutil
            if os.path.exists(test_proj):
                shutil.rmtree(test_proj, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
