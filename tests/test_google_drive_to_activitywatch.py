from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import aw_sync_android_gdrive as aw


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
                        "afk_duplicate_bucket_ids": ["aw-watcher-window_FloneA54"],
                        "afk_duplicate_upload_original_bucket": False,
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(aw, "CONFIG_FILE", config_path):
                config = aw.build_config()

        self.assertEqual(config.afk_duplicate_bucket_ids, ["aw-watcher-window_FloneA54"])
        self.assertFalse(config.afk_duplicate_upload_original_bucket)


class AfkBucketTests(unittest.TestCase):
    def test_build_afk_duplicate_bucket_rewrites_bucket_id(self) -> None:
        bucket = aw.ExportBucket(
            bucket_id="aw-watcher-window_FloneA54",
            bucket_type="currentwindow",
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

    def test_build_afk_duplicate_events_only_emits_not_afk_spans(self) -> None:
        window_events = [
            {"timestamp": "2026-06-28T08:00:00Z", "duration": 0.0, "data": {}},
            {"timestamp": "2026-06-28T08:05:00Z", "duration": 0.0, "data": {}},
        ]

        afk_events = aw.build_afk_duplicate_events(window_events)

        self.assertEqual(len(afk_events), 2)
        self.assertTrue(all(event["data"]["status"] == "not-afk" for event in afk_events))
        self.assertEqual(afk_events[0]["duration"], 120.0)
        self.assertEqual(afk_events[1]["duration"], 120.0)

    def test_should_duplicate_as_afk_matches_exact_bucket_id(self) -> None:
        self.assertTrue(
            aw.should_duplicate_as_afk(
                "aw-watcher-window_FloneA54",
                {"aw-watcher-window_FloneA54"},
            )
        )
        self.assertFalse(
            aw.should_duplicate_as_afk(
                "aw-import-activity_FloneA54",
                {"aw-watcher-window_FloneA54"},
            )
        )

    def test_should_upload_original_bucket_respects_toggle(self) -> None:
        configured = {"aw-watcher-window_FloneA54"}
        self.assertFalse(
            aw.should_upload_original_bucket(
                "aw-watcher-window_FloneA54",
                configured,
                False,
            )
        )
        self.assertTrue(
            aw.should_upload_original_bucket(
                "aw-watcher-window_FloneA54",
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

    def test_window_collect_events_preserves_duration(self) -> None:
        config = aw.AppConfig(
            google_drive_folder_id="folder-id",
            google_drive_service_account_file=None,
            input_file_globs=["*"],
            last_sync_file=Path("last_sync.txt"),
            activitywatch_base_url="http://localhost:5600",
            activitywatch_hostname="FloneA54",
            afk_duplicate_bucket_ids=[],
            afk_duplicate_upload_original_bucket=True,
            timestamp_fields=["timestamp"],
            duration_fields=["duration"],
            payload_fields=["data"],
            encoding="utf-8",
            request_timeout_seconds=15,
        )
        records = [
            {"timestamp": "2026-06-28T08:00:00Z", "duration": 999},
            {"timestamp": "2026-06-28T08:01:00Z", "duration": 999},
        ]

        events, newest = aw.collect_events(records, config, None)

        self.assertEqual(len(events), 2)
        self.assertTrue(all(event["duration"] == 999.0 for event in events))
        self.assertEqual(aw.parse_timestamp(events[0]["timestamp"]), aw.parse_timestamp("2026-06-28T08:00:00Z"))
        self.assertEqual(newest, aw.parse_timestamp("2026-06-28T08:01:00Z"))


if __name__ == "__main__":
    unittest.main()
