import argparse
import csv
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    import requests
except Exception as exc:
    print("The 'requests' package is required. Please install it: pip install requests", file=sys.stderr)
    raise


OPEN_FACTS_SOURCES: List[Tuple[str, str]] = [
    ("world.openfoodfacts.org", "openfoodfacts"),
    ("world.openbeautyfacts.org", "openbeautyfacts"),
    ("world.openpetfoodfacts.org", "openpetfoodfacts"),
]


def normalize_barcode(raw: str) -> str:
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    return digits


def pick_best_image_url(product: Dict) -> Optional[str]:
    # Prefer high-quality fields first
    preferred_keys = [
        "image_front_url",
        "image_url",
        "image_pack_url",
        "image_ingredients_url",
        "image_nutrition_url",
        "image_small_url",
        "image_thumb_url",
    ]

    for key in preferred_keys:
        url = product.get(key)
        if isinstance(url, str) and url.strip():
            return url.strip()

    # Try selected_images structure if available
    selected = product.get("selected_images")
    if isinstance(selected, dict):
        # front / ingredients / nutrition; display / small / thumb; language keys vary
        for section in ("front", "ingredients", "nutrition"):
            sec = selected.get(section)
            if not isinstance(sec, dict):
                continue
            for size in ("display", "small", "thumb"):
                sz = sec.get(size)
                if not isinstance(sz, dict):
                    continue
                # pick any language key deterministically (prefer 'en' if present)
                if "en" in sz and isinstance(sz["en"], str) and sz["en"].strip():
                    return sz["en"].strip()
                for _, candidate in sorted(sz.items()):
                    if isinstance(candidate, str) and candidate.strip():
                        return candidate.strip()

    return None


def fetch_openfacts_product(barcode: str, host: str, timeout: float = 8.0) -> Optional[Dict]:
    url = f"https://{host}/api/v2/product/{barcode}.json"
    headers = {
        "Accept": "application/json",
        "User-Agent": "Smith-Pharmacy-ImageFinder/1.0 (+shopify-enrichment)"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return None
        if data.get("status") == 1 and isinstance(data.get("product"), dict):
            return data["product"]
        return None
    except requests.RequestException:
        return None
    except json.JSONDecodeError:
        return None


def find_image_url_zero_cost(barcode: str, per_source_delay_s: float = 0.2, retries: int = 2, verbose: bool = False) -> Tuple[Optional[str], Optional[str]]:
    # Try each open source with small delay and exactly `retries` attempts
    for host, source_name in OPEN_FACTS_SOURCES:
        for attempt in range(retries):
            if verbose:
                print(f"  - [{source_name}] attempt {attempt + 1}/{retries}...")
            product = fetch_openfacts_product(barcode, host)
            if product:
                img = pick_best_image_url(product)
                if img:
                    if verbose:
                        print(f"    -> Found image URL from {source_name}")
                    return img, source_name
            # polite delay between attempts
            time.sleep(per_source_delay_s)
    return None, None


def read_csv_rows(path: str) -> Tuple[List[str], List[Dict[str, str]]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = [row for row in reader]
    return fieldnames, rows


def write_csv_rows(path: str, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def process_csv(
    input_csv: str,
    barcode_col: str,
    output_csv: Optional[str] = None,
    per_source_delay_s: float = 0.2,
    retries: int = 2,
    limit: Optional[int] = None,
    verbose: bool = False,
    out_dir: Optional[str] = "Food",
    checkpoint_every: int = 50,
    resume: bool = False,
) -> str:
    if verbose:
        print(f"Loading CSV: {input_csv}")
    fieldnames, rows = read_csv_rows(input_csv)
    if barcode_col not in fieldnames:
        raise ValueError(f"Barcode column '{barcode_col}' not found. Available: {fieldnames}")

    # Optional limit for testing
    if isinstance(limit, int) and limit > 0:
        if verbose:
            print(f"Applying row limit: {limit}")
        rows = rows[:limit]

    out_fieldnames = list(fieldnames)
    if "image_url" not in out_fieldnames:
        out_fieldnames.append("image_url")

    # Output directory and paths
    base_name = os.path.splitext(os.path.basename(input_csv))[0]
    out_dir_final = out_dir or "Food"
    os.makedirs(out_dir_final, exist_ok=True)
    progress_csv = output_csv or os.path.join(out_dir_final, f"{base_name}_with_image_urls_progress.csv")
    ckpt_path = os.path.join(out_dir_final, f"{base_name}_with_image_urls_progress.ckpt.json")

    # Resume checkpoint
    start_index = 0
    if resume:
        try:
            with open(ckpt_path, "r", encoding="utf-8") as cf:
                ckpt = json.load(cf)
                start_index = int(ckpt.get("processed_count", 0))
                if verbose:
                    print(f"Resuming from checkpoint: start_index={start_index}")
        except Exception:
            if verbose:
                print("No checkpoint found; starting fresh.")

    # Determine if we need to write header
    needs_header = True
    if resume:
        try:
            with open(progress_csv, "r", encoding="utf-8", newline="") as _:
                needs_header = False
        except Exception:
            needs_header = True

    def append_rows(batch: List[Dict[str, str]]):
        nonlocal needs_header
        mode = "a" if not needs_header else "w"
        with open(progress_csv, mode, encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=out_fieldnames)
            if needs_header:
                writer.writeheader()
                needs_header = False
            for r in batch:
                writer.writerow(r)

    # Cache to avoid duplicate lookups
    barcode_to_image: Dict[str, Tuple[Optional[str], Optional[str]]] = {}

    processed_count = start_index
    pending_batch: List[Dict[str, str]] = []
    total = len(rows)

    for idx in range(start_index, total):
        row = rows[idx]
        raw = row.get(barcode_col, "")
        norm = normalize_barcode(raw)
        img_url: Optional[str] = None
        if norm:
            if norm not in barcode_to_image:
                if verbose:
                    print(f"Searching [{idx + 1}/{total}] barcode: {norm}")
                img, source = find_image_url_zero_cost(
                    norm,
                    per_source_delay_s=per_source_delay_s,
                    retries=retries,
                    verbose=verbose,
                )
                barcode_to_image[norm] = (img, source)
                if verbose:
                    if img:
                        print(f"  -> RESULT: FOUND ({source}) {img}")
                    else:
                        print("  -> RESULT: NOT FOUND")
            img_url, _ = barcode_to_image.get(norm, (None, None))

        new_row = dict(row)
        new_row["image_url"] = img_url or ""
        pending_batch.append(new_row)
        processed_count += 1

        if checkpoint_every > 0 and (processed_count % checkpoint_every == 0):
            if verbose:
                print(f"Checkpoint: writing {len(pending_batch)} rows (processed={processed_count})")
            append_rows(pending_batch)
            pending_batch = []
            with open(ckpt_path, "w", encoding="utf-8") as cf:
                json.dump({"processed_count": processed_count}, cf)

    # Flush remaining
    if pending_batch:
        if verbose:
            print(f"Final write: {len(pending_batch)} rows (processed={processed_count})")
        append_rows(pending_batch)
        with open(ckpt_path, "w", encoding="utf-8") as cf:
            json.dump({"processed_count": processed_count}, cf)

    return progress_csv


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enrich CSV with image_url by barcode via zero-cost sources.")
    parser.add_argument("--input", required=True, help="Path to input CSV")
    parser.add_argument("--barcode-col", required=True, help="Column name containing UPC/EAN/GTIN")
    parser.add_argument("--output", required=False, help="Optional output CSV path (defaults to Food/progress)")
    parser.add_argument("--delay", type=float, default=0.2, help="Per-attempt delay seconds per source (default 0.2)")
    parser.add_argument("--retries", type=int, default=2, help="Attempts per source (exact tries, default 2)")
    parser.add_argument("--limit", type=int, default=0, help="Process only first N rows for testing (default 100)")
    parser.add_argument("--out-dir", default="Food", help="Directory to write outputs and checkpoint (default Food)")
    parser.add_argument("--checkpoint-every", type=int, default=50, help="Write and checkpoint every N rows (default 50)")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint if available")
    parser.add_argument("--verbose", action="store_true", help="Print step-by-step progress for debugging")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    output_path = process_csv(
        input_csv=args.input,
        barcode_col=args.barcode_col,
        output_csv=args.output,
        per_source_delay_s=args.delay,
        retries=args.retries,
        limit=args.limit,
        verbose=args.verbose,
        out_dir=args.out_dir,
        checkpoint_every=args.checkpoint_every,
        resume=args.resume,
    )
    print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()


