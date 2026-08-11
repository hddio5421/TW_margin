"""Backward-compatible wrapper for the historical 2026-08-06 repair.

The real implementation now lives in ``fetch_real_data.py`` so every normal
update and missed-day backfill uses the same official download format and the
same post-processing pipeline.
"""

from fetch_real_data import process_and_update


if __name__ == "__main__":
    process_and_update("2026-08-06")
