import json
import tempfile
import unittest
from pathlib import Path

from evals.stt_score import edit_counts, normalize, score


class SttScoreTests(unittest.TestCase):
    def test_normalize_removes_edacc_non_speech_tags(self) -> None:
        self.assertEqual(
            normalize("<LAUGH> IT’S John's test!"), ["it's", "john's", "test"]
        )

    def test_edit_counts_separates_error_types(self) -> None:
        self.assertEqual(edit_counts(["a", "b", "c"], ["a", "x", "c", "d"]), (1, 0, 1))
        self.assertEqual(edit_counts(["a", "b", "c"], ["a", "c"]), (0, 1, 0))

    def test_score_uses_aggregate_word_error_rate(self) -> None:
        manifest = [
            {"id": "one", "l1": "A", "reference": "ONE TWO", "duration": 2.0},
            {
                "id": "two",
                "l1": "B",
                "reference": "THREE FOUR FIVE SIX",
                "duration": 4.0,
            },
        ]
        predictions = [
            {
                "id": "one",
                "engine": "test",
                "text": "ONE",
                "audio_seconds": 2.0,
                "inference_seconds": 1.0,
            },
            {
                "id": "two",
                "engine": "test",
                "text": "THREE FOUR FIVE SIX",
                "audio_seconds": 4.0,
                "inference_seconds": 1.0,
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.jsonl"
            predictions_path = root / "predictions.jsonl"
            manifest_path.write_text(
                "".join(json.dumps(row) + "\n" for row in manifest), encoding="utf-8"
            )
            predictions_path.write_text(
                "".join(json.dumps(row) + "\n" for row in predictions), encoding="utf-8"
            )
            result = score(manifest_path, predictions_path)
        self.assertAlmostEqual(result["summary"]["wer"], 1 / 6, places=6)
        self.assertAlmostEqual(result["summary"]["rtf"], 1 / 3, places=6)

    def test_score_rejects_incomplete_predictions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.jsonl"
            predictions_path = root / "predictions.jsonl"
            manifest_path.write_text(
                '{"id":"one","l1":"A","reference":"ONE"}\n', encoding="utf-8"
            )
            predictions_path.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "prediction ids differ"):
                score(manifest_path, predictions_path)


if __name__ == "__main__":
    unittest.main()
