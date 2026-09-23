"""Detect stale source evidence; this is not an authenticity/signature check."""
import json
from pathlib import Path

from verify import ROOT, source_manifest


def main() -> int:
    report = json.loads((ROOT / "evidence/verification.json").read_text(encoding="utf-8"))
    actual = source_manifest()
    expected = report["source_files"]
    changed = sorted(k for k in set(expected) | set(actual) if expected.get(k) != actual.get(k))
    if changed or report["status"] != "PASS":
        print("STALE_OR_FAILED_EVIDENCE", *changed, sep="\n")
        return 1
    print("SOURCE_MATCHES_LOCAL_TEST_EVIDENCE; no game/driver/remote verification implied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
