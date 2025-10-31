import argparse
import csv
import sys
import time
from typing import Dict, List, Optional, Tuple

try:
    import requests
    from bs4 import BeautifulSoup  # type: ignore
except Exception:
    print("This script requires: pip install requests beautifulsoup4", file=sys.stderr)
    raise


def normalize_barcode(raw: str) -> str:
    return "".join(ch for ch in (raw or "") if ch.isdigit())


def _get(url: str, timeout: float = 10.0) -> Optional[str]:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            return None
        return resp.text
    except requests.RequestException:
        return None


def parse_image_candidates(html: str, base_url: str, barcode: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: List[str] = []

    # Meta OpenGraph
    for meta in soup.select('meta[property="og:image"], meta[name="og:image"]'):
        content = meta.get("content")
        if content and content.strip():
            candidates.append(content.strip())

    # Common product image selectors
    for selector in [
        "img#product-image",
        "img.product-img",
        "img.product-image",
        "img.main-image",
        "img[itemprop='image']",
        "div.product-image img",
        "figure img",
    ]:
        for img in soup.select(selector):
            src = img.get("src") or img.get("data-src")
            if src and src.strip():
                candidates.append(src.strip())

    # Any image that embeds the barcode digits in its URL is a strong hint
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        s = src.strip()
        if not s:
            continue
        if barcode and barcode in s:
            candidates.append(s)

    # Deduplicate preserving order
    seen = set()
    unique = []
    for url in candidates:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def extract_go_upc_details(html: str, barcode: str) -> Tuple[List[str], Optional[str]]:
    """Extract image candidates and description from a Go-UPC product page."""
    soup = BeautifulSoup(html, "html.parser")

    # Images: prefer go-upc S3 images, then og:image and other imgs
    imgs: List[str] = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        s = src.strip()
        if not s:
            continue
        if "go-upc.s3.amazonaws.com" in s:
            imgs.append(s)
    # Fallback to generic candidates
    if not imgs:
        imgs = parse_image_candidates(html, "https://go-upc.com", barcode)

    # Description: find heading "Description" then nearby <span> or text container
    description: Optional[str] = None
    # Find h2/h3 containing 'Description'
    heading = None
    for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
        text = (tag.get_text(" ", strip=True) or "").lower()
        if "description" in text:
            heading = tag
            break
    if heading is not None:
        # Look for a following span or p with text
        # First check within parent container
        parent = heading.parent
        if parent:
            cand = parent.find("span") or parent.find("p")
            if cand:
                t = cand.get_text(" ", strip=True)
                if t:
                    description = t
        # If still none, scan next siblings
        if not description:
            sib = heading.next_sibling
            while sib is not None:
                try:
                    if getattr(sib, "name", None) in ("span", "p", "div"):
                        t = sib.get_text(" ", strip=True)
                        if t:
                            description = t
                            break
                except Exception:
                    pass
                sib = sib.next_sibling

    return imgs, description


def lookup_go_upc(barcode: str, verbose: bool = False, delay_s: float = 0.6, retries: int = 1) -> Tuple[List[str], Optional[str]]:
    # Product page pattern observed: https://go-upc.com/lookup/<barcode>
    url = f"https://go-upc.com/lookup/{barcode}"
    for attempt in range(retries + 1):
        if verbose:
            print(f"[go-upc] GET {url} (attempt {attempt + 1}/{retries + 1})")
        html = _get(url)
        if html:
            imgs, desc = extract_go_upc_details(html, barcode)
            if verbose:
                print(f"[go-upc] candidates: {len(imgs)} | has description: {bool(desc)}")
            if imgs or desc:
                return imgs, desc
        time.sleep(delay_s)
    return [], None


def lookup_barcode_lookup(barcode: str, verbose: bool = False, delay_s: float = 0.6, retries: int = 1) -> List[str]:
    # Product page pattern: https://www.barcodelookup.com/<barcode>
    url = f"https://www.barcodelookup.com/{barcode}"
    for attempt in range(retries + 1):
        if verbose:
            print(f"[barcode-lookup] GET {url} (attempt {attempt + 1}/{retries + 1})")
        html = _get(url)
        if html:
            imgs = parse_image_candidates(html, url, barcode)
            if verbose:
                print(f"[barcode-lookup] candidates: {len(imgs)}")
            if imgs:
                return imgs
        time.sleep(delay_s)
    return []


def find_images_from_sites(barcode: str, verbose: bool = False) -> Dict[str, object]:
    results: Dict[str, object] = {
        "go_upc": [],            # List[str]
        "go_upc_description": None,  # Optional[str]
        "barcode_lookup": [],
    }
    b = normalize_barcode(barcode)
    if not b:
        return results
    if verbose:
        print(f"Normalized barcode: {b}")
    go_imgs, go_desc = lookup_go_upc(b, verbose=verbose)
    results["go_upc"] = go_imgs
    results["go_upc_description"] = go_desc
    results["barcode_lookup"] = lookup_barcode_lookup(b, verbose=verbose)
    return results


def enrich_csv(
    input_csv: str,
    barcode_col: str,
    output_csv: Optional[str],
    limit: Optional[int],
    verbose: bool,
    out_dir: Optional[str],
    checkpoint_every: int,
    resume: bool,
) -> str:
    import json
    import os

    with open(input_csv, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    if barcode_col not in fieldnames:
        raise ValueError(f"Barcode column '{barcode_col}' not found. Available: {fieldnames}")

    if isinstance(limit, int) and limit > 0:
        rows = rows[:limit]

    out_fields = list(fieldnames)
    if "image_url_go_upc" not in out_fields:
        out_fields.append("image_url_go_upc")
    if "image_url_barcode_lookup" not in out_fields:
        out_fields.append("image_url_barcode_lookup")
    if "description_go_upc" not in out_fields:
        out_fields.append("description_go_upc")

    base = input_csv.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0]
    out_dir_final = out_dir or "output"
    os.makedirs(out_dir_final, exist_ok=True)
    progress_csv = output_csv or os.path.join(out_dir_final, f"{base}_with_site_images_progress.csv")
    ckpt_path = os.path.join(out_dir_final, f"{base}_with_site_images_progress.ckpt.json")

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

    # Write header if file not exists or empty and not resuming
    needs_header = True
    try:
        if resume:
            with open(progress_csv, "r", encoding="utf-8", newline="") as f:
                # If can open and has a header, don't rewrite
                needs_header = False
    except Exception:
        needs_header = True

    def append_rows(batch: List[Dict[str, str]]):
        nonlocal needs_header
        mode = "a" if not needs_header else "w"
        with open(progress_csv, mode, encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=out_fields)
            if needs_header:
                writer.writeheader()
                needs_header = False
            for r in batch:
                writer.writerow(r)

    processed_count = start_index
    pending_batch: List[Dict[str, str]] = []
    total = len(rows)

    for idx in range(start_index, total):
        row = rows[idx]
        raw = row.get(barcode_col, "")
        b = normalize_barcode(raw)
        if verbose:
            print(f"[{idx + 1}/{total}] barcode: {raw} -> {b}")
        urls = find_images_from_sites(b, verbose=verbose)
        row_out = dict(row)
        row_out["image_url_go_upc"] = (urls["go_upc"][0] if urls["go_upc"] else "")
        row_out["image_url_barcode_lookup"] = (urls["barcode_lookup"][0] if urls["barcode_lookup"] else "")
        row_out["description_go_upc"] = (urls["go_upc_description"] or "")
        pending_batch.append(row_out)
        processed_count += 1

        if checkpoint_every > 0 and (processed_count % checkpoint_every == 0):
            if verbose:
                print(f"Checkpoint: writing {len(pending_batch)} rows (processed={processed_count})")
            append_rows(pending_batch)
            pending_batch = []
            # Update checkpoint
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
    parser = argparse.ArgumentParser(description="HTML fetch product images from Go-UPC and Barcode Lookup.")
    sub = parser.add_subparsers(dest="cmd", required=False)

    p1 = sub.add_parser("single", help="Lookup a single barcode and print image URLs")
    p1.add_argument("barcode", help="Barcode to look up")
    p1.add_argument("--verbose", action="store_true")

    p2 = sub.add_parser("csv", help="Enrich a CSV with image_url_go_upc and image_url_barcode_lookup")
    p2.add_argument("--input", required=True, help="Path to input CSV")
    p2.add_argument("--barcode-col", required=True, help="Column containing barcode")
    p2.add_argument("--output", required=False, help="Output CSV path (overrides out-dir/progress name)")
    p2.add_argument("--limit", type=int, default=0, help="Process only first N rows")
    p2.add_argument("--verbose", action="store_true")
    p2.add_argument("--out-dir", default="output", help="Directory to write outputs (default: output)")
    p2.add_argument("--checkpoint-every", type=int, default=20, help="Write and checkpoint every N rows (default 20)")
    p2.add_argument("--resume", action="store_true", help="Resume from last checkpoint if available")

    parser.add_argument("--verbose", action="store_true", help="Global verbose if no subcommand is used")
    parser.add_argument("barcode", nargs="?", help="If provided without subcommand, behaves like single")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    if args.cmd == "single" or (getattr(args, "barcode", None) and not args.cmd):
        barcode = args.barcode
        verbose = getattr(args, "verbose", False)
        res = find_images_from_sites(barcode, verbose=verbose)
        print("go_upc:")
        for u in res["go_upc"]:
            print(f"  {u}")
        if res.get("go_upc_description"):
            print("go_upc_description:")
            print(f"  {res['go_upc_description']}")
        print("barcode_lookup:")
        for u in res["barcode_lookup"]:
            print(f"  {u}")
        return

    if args.cmd == "csv":
        out_path = enrich_csv(
            input_csv=args.input,
            barcode_col=args.barcode_col,
            output_csv=args.output,
            limit=args.limit,
            verbose=args.verbose,
            out_dir=args.out_dir,
            checkpoint_every=args.checkpoint_every,
            resume=args.resume,
        )
        print(f"Wrote: {out_path}")
        return

    # Help if nothing matched
    print("Usage examples:\n  python html_barcode_image_fetcher.py single 012345678905 --verbose\n  python html_barcode_image_fetcher.py csv --input dataset/file.csv --barcode-col 'Variant Barcode' --limit 100 --verbose")


if __name__ == "__main__":
    main()


