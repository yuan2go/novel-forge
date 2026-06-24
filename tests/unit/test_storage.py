from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.schemas import SourceDocument
from novel_forge.storage.local import LocalStorage


class StorageTests(unittest.TestCase):
    def test_write_and_read_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)
            storage.ensure_layout()
            path = storage.write_asset("raw", SourceDocument(title="A", source="a.txt", content={"text": "x"}))
            loaded = storage.read_asset(path)
            self.assertEqual(loaded.type, "source_document")
            self.assertEqual(storage.counts()["raw"], 1)


if __name__ == "__main__":
    unittest.main()
