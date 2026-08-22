import unittest

from scripts.release_metadata import ReleaseMetadataError, validate_git_description


class ReleaseMetadataTests(unittest.TestCase):
    def test_release_candidate_tag_is_accepted(self):
        self.assertEqual(
            validate_git_description(
                "v3.3.0-rc2-0-g1234abcd", "3.3.0-rc2"
            ),
            "v3.3.0-rc2",
        )

    def test_development_commit_after_release_is_accepted(self):
        self.assertEqual(
            validate_git_description(
                "v3.3.0-rc2-4-g1234abcd", "3.3.0-rc2"
            ),
            "v3.3.0-rc2",
        )

    def test_backup_tag_is_rejected_like_moonraker(self):
        with self.assertRaisesRegex(ReleaseMetadataError, "semantic release tag"):
            validate_git_description(
                "backup/pre-detection-hardening-20260822-3-g5e79f633",
                "3.3.0-rc2",
            )

    def test_tag_must_match_runtime_version(self):
        with self.assertRaisesRegex(ReleaseMetadataError, "runtime version"):
            validate_git_description("v3.2.2-7-g1234abcd", "3.3.0-rc2")

    def test_dirty_release_is_rejected(self):
        with self.assertRaisesRegex(ReleaseMetadataError, "dirty"):
            validate_git_description(
                "v3.3.0-rc2-0-g1234abcd-dirty", "3.3.0-rc2"
            )


if __name__ == "__main__":
    unittest.main()
