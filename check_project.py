"""Run with PyCharm's Run action to check the bot without starting Telegram."""
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

from waiterbot.catalog import Catalog

BASE_DIR = Path(__file__).resolve().parent


def main():
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.executable,
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "success": False,
    }
    try:
        report["questions"] = Catalog(BASE_DIR).reload()
        print("Questions:", report["questions"])
        suite = unittest.defaultTestLoader.discover(str(BASE_DIR / "tests"))
        result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
        report.update(tests=result.testsRun, failures=len(result.failures),
                      errors=len(result.errors), success=result.wasSuccessful())
        return 0 if result.wasSuccessful() else 1
    except Exception as error:
        report["error"] = type(error).__name__ + ": " + str(error)
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        destination = BASE_DIR / "data" / "check-results.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Report:", destination)


if __name__ == "__main__":
    raise SystemExit(main())
