\
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path

def main() -> int:
    ap = argparse.ArgumentParser(description="Create a deterministic smoke sample from a CSV.")
    ap.add_argument("input_csv", type=Path)
    ap.add_argument("output_csv", type=Path)
    ap.add_argument("--ratio", type=float, default=0.1, help="Approx keep ratio (default 0.1). Implemented as keep every Nth row.")
    ap.add_argument("--max-rows", type=int, default=5000, help="Hard cap on kept data rows (default 5000).")
    ap.add_argument("--min-rows", type=int, default=200, help="Ensure at least this many data rows (default 200).")
    args = ap.parse_args()

    if args.ratio <= 0 or args.ratio > 1:
        raise SystemExit("--ratio must be in (0, 1].")

    step = max(1, int(round(1.0 / args.ratio)))

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)

    kept = 0
    total = 0

    with args.input_csv.open("r", newline="", encoding="utf-8") as fin, args.output_csv.open("w", newline="", encoding="utf-8") as fout:
        reader = csv.reader(fin)
        writer = csv.writer(fout)

        header = next(reader, None)
        if header is None:
            raise SystemExit("Input CSV is empty.")
        writer.writerow(header)

        for idx, row in enumerate(reader, start=1):
            total += 1
            # Keep every Nth row deterministically
            if (idx % step) == 0:
                writer.writerow(row)
                kept += 1
                if kept >= args.max_rows:
                    break

        # If the sampling kept too few rows, top-up by taking the first rows
        if kept < args.min_rows:
            # Rewind and copy additional rows deterministically from the start
            fin.seek(0)
            reader = csv.reader(fin)
            _ = next(reader, None)  # header
            # write additional rows until min_rows reached (skip duplicates via idx rule)
            already = kept
            for idx, row in enumerate(reader, start=1):
                if already >= args.min_rows:
                    break
                # Avoid writing rows that would have been written by the idx%step rule
                if (idx % step) != 0:
                    writer.writerow(row)
                    already += 1

    print(f"Wrote sample: {args.output_csv} (kept={max(kept, args.min_rows)} from total={total}, step={step})")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
