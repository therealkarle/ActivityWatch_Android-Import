from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import google_drive_to_activitywatch as aw


class ConfigTests(unittest.TestCase):
    def test_build_config_reads_afk_duplicate_bucket_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_path = tmp_path / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "google_drive_folder_id": "folder-id",
                        "google_drive_service_account_file": "service-account.json",
                        "afk_duplicate_bucket_ids": ["aw-import-unlock_FloneA54"],
                        "afk_duplicate_upload_original_bucket": False,
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(aw, "CONFIG_FILE", config_path):
                config = aw.build_config()

        self.assertEqual(config.afk_duplicate_bucket_ids, ["aw-import-unlock_FloneA54"])
        self.assertFalse(config.afk_duplicate_upload_original_bucket)


class AfkBucketTests(unittest.TestCase):
    def test_build_afk_duplicate_bucket_rewrites_bucket_id(self) -> None:
        bucket = aw.ExportBucket(
            bucket_id="aw-import-unlock_FloneA54",
            bucket_type="manual",
            client="google_drive_to_activitywatch",
            hostname="FloneA54",
            data={},
            records=[{"timestamp": "2026-01-01T00:00:00Z"}],
        )

        duplicated = aw.build_afk_duplicate_bucket(bucket)

        self.assertEqual(duplicated.bucket_id, "aw-watcher-afk_FloneA54")
        self.assertEqual(duplicated.hostname, "FloneA54")
        self.assertEqual(duplicated.records, bucket.records)
        self.assertEqual(duplicated.bucket_type, "afk")

    def test_should_duplicate_as_afk_matches_exact_bucket_id(self) -> None:
        self.assertTrue(
            aw.should_duplicate_as_afk(
                "aw-import-unlock_FloneA54",
                ["aw-import-unlock_FloneA54"],
            )
        )
        self.assertFalse(
            aw.should_duplicate_as_afk(
                "aw-import-activity_FloneA54",
                ["aw-import-unlock_FloneA54"],
            )
        )

    def test_should_upload_original_bucket_respects_toggle(self) -> None:
        configured = {"aw-import-unlock_FloneA54"}
        self.assertFalse(
            aw.should_upload_original_bucket(
                "aw-import-unlock_FloneA54",
                configured,
                False,
            )
        )
        self.assertTrue(
            aw.should_upload_original_bucket(
                "aw-import-unlock_FloneA54",
                configured,
                True,
            )
        )
        self.assertTrue(
            aw.should_upload_original_bucket(
                "aw-import-activity_FloneA54",
                configured,
                False,
            )
        )


if __name__ == "__main__":
    unittest.main()
