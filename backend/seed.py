import argparse
import json
import sys
from pathlib import Path

from .db import init_db
from .import_jobs import create_job, run_job


def main():
    parser = argparse.ArgumentParser(description="Import the Kaggle Resume.csv into the local search index")
    parser.add_argument("csv", type=Path)
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit for quick development runs; default: all rows")
    args = parser.parse_args()
    init_db()
    result = run_job(create_job(args.csv, limit=args.limit))
    print(json.dumps(result, indent=2))
    if result["status"] not in {"completed", "completed_with_errors"}:
        sys.exit(1)


if __name__ == "__main__":
    main()
