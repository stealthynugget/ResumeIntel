"""Download only the CSV from the primary Kaggle archive into ignored local storage."""
import io
import zipfile
from pathlib import Path

import httpx

URL = "https://www.kaggle.com/api/v1/datasets/download/snehaanbhawal/resume-dataset"
TARGET = Path(__file__).resolve().parents[1] / "data" / "source" / "Resume.csv"


def main():
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    response = httpx.get(URL, follow_redirects=True, timeout=180)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        csv_files = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if not csv_files:
            raise RuntimeError("Kaggle archive contains no CSV")
        TARGET.write_bytes(archive.read(csv_files[0]))
    print(f"Saved {TARGET} ({TARGET.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()

