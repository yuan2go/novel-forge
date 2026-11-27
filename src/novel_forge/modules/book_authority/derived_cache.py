from collections import OrderedDict
import hashlib
import json
from threading import RLock


class DerivedResultCache:
    def __init__(self, max_bytes: int = 32 * 1024 * 1024):
        self.max_bytes = max_bytes
        self._rows = OrderedDict()
        self._bytes = 0
        self._lock = RLock()
        self.hits = self.misses = 0

    def get(self, key):
        with self._lock:
            row = self._rows.pop(key, None)
            if row is not None:
                encoded, digest = row
                self._bytes -= len(encoded)
                if hashlib.sha256(encoded).digest() == digest:
                    self._rows[key] = row
                    self._bytes += len(encoded)
                    self.hits += 1
                    return json.loads(encoded)
            self.misses += 1
            return None

    def put(self, key, value):
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        if len(encoded) > self.max_bytes:
            return
        with self._lock:
            previous = self._rows.pop(key, None)
            if previous:
                self._bytes -= len(previous[0])
            while self._rows and self._bytes + len(encoded) > self.max_bytes:
                _, removed = self._rows.popitem(last=False)
                self._bytes -= len(removed[0])
            self._rows[key] = (encoded, hashlib.sha256(encoded).digest())
            self._bytes += len(encoded)

    def clear(self):
        with self._lock:
            self._rows.clear()
            self._bytes = 0
            self.hits = self.misses = 0


task_selection_cache = DerivedResultCache()
