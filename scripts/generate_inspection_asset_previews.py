"""Generate all browser-friendly previews for STAFIM inspection assets.

Runs both:
- HEIC -> JPEG preview
- PDF page 1 -> JPEG preview

Usage:
  python backend/migrations/005_add_inspection_image_previews.py
  python scripts/generate_inspection_asset_previews.py --dry-run
  python scripts/generate_inspection_asset_previews.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.generate_heic_inspection_previews import run as run_heic
from scripts.generate_pdf_inspection_previews import run as run_pdf


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate JPEG previews for HEIC and PDF inspection assets.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--heic-quality", type=int, default=88)
    parser.add_argument("--pdf-dpi", type=int, default=160)
    args = parser.parse_args()

    heic_stats = run_heic(dry_run=args.dry_run, quality=args.heic_quality)
    pdf_stats = run_pdf(dry_run=args.dry_run, dpi=args.pdf_dpi)
    print("all preview generation finished")
    print("  HEIC: " + ", ".join(f"{k}={v}" for k, v in heic_stats.items()))
    print("  PDF : " + ", ".join(f"{k}={v}" for k, v in pdf_stats.items()))


if __name__ == "__main__":
    main()
