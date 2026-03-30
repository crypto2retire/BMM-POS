#!/usr/bin/env python3
"""Resume-capable scraper that reads URLs from product_urls.txt and skips already-scraped items."""
import sys, os, re, csv, time, requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(line_buffering=True)

OUT_DIR = "scraped_images"
CSV_FILE = "scraped_items.csv"
URL_FILE = "product_urls.txt"
DELAY = 0.3

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
}

def scrape_product(session, url):
    try:
        resp = session.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None
    sku = ""
    for script in soup.find_all("script"):
        text = script.string or ""
        match = re.search(r"rico\.sku\s*=\s*'([^']+)'", text)
        if match:
            sku = match.group(1)
            break
    name = ""
    h2 = soup.find("h2")
    if h2:
        name = h2.get_text(strip=True)
    price = ""
    price_el = soup.find(class_=re.compile(r"price"))
    if price_el:
        price_text = price_el.get_text()
        match = re.search(r"\$[\d,.]+", price_text)
        if match:
            price = match.group(0)
    s3_pattern = re.compile(r"ricoconsign-assets\.s3\.")
    image_urls = []
    seen = set()
    for img in soup.find_all("img", src=s3_pattern):
        src = img.get("src", "")
        if src and src not in seen:
            seen.add(src)
            image_urls.append(src)
    return {"name": name, "sku": sku, "price": price, "image_urls": image_urls, "product_url": url}

def download_images(session, product, out_dir):
    filenames = []
    sku = product["sku"] or "unknown_" + re.sub(r"[^a-z0-9]", "", product["name"].lower())[:20]
    for i, img_url in enumerate(product["image_urls"]):
        ext = img_url.rsplit(".", 1)[-1].split("?")[0].lower()
        if ext not in ("jpg", "jpeg", "png", "webp"):
            ext = "jpg"
        filename = f"{sku}_{i}.{ext}"
        filepath = os.path.join(out_dir, filename)
        if os.path.exists(filepath):
            filenames.append(filename)
            continue
        try:
            resp = session.get(img_url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(resp.content)
            filenames.append(filename)
            time.sleep(0.15)
        except Exception as e:
            print(f"    Image download failed: {e}")
    return filenames

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    with open(URL_FILE, "r") as f:
        all_urls = [line.strip() for line in f if line.strip()]
    print(f"Total URLs to scrape: {len(all_urls)}")

    already_scraped = set()
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = row.get("product_url", "").strip()
                if url:
                    already_scraped.add(url)
    print(f"Already scraped: {len(already_scraped)}")

    remaining = [u for u in all_urls if u not in already_scraped]
    print(f"Remaining: {len(remaining)}")

    if not remaining:
        print("Nothing to scrape!")
        return

    fieldnames = ["sku","name","price","image_filenames","primary_image","product_url"]
    write_header = not os.path.exists(CSV_FILE) or os.path.getsize(CSV_FILE) == 0
    csv_f = open(CSV_FILE, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(csv_f, fieldnames=fieldnames)
    if write_header:
        writer.writeheader()
        csv_f.flush()

    session = requests.Session()
    scraped = 0
    errors = 0

    for i, url in enumerate(remaining, 1):
        print(f"[{i}/{len(remaining)}] {url}")
        try:
            product = scrape_product(session, url)
            if not product:
                errors += 1
                continue
            filenames = download_images(session, product, OUT_DIR)
            writer.writerow({
                "sku": product["sku"],
                "name": product["name"],
                "price": product["price"],
                "image_filenames": "|".join(filenames),
                "primary_image": filenames[0] if filenames else "",
                "product_url": product["product_url"],
            })
            csv_f.flush()
            scraped += 1
            print(f"  SKU: {product['sku']} | Images: {len(filenames)} | Name: {product['name'][:50]}")
        except Exception as e:
            print(f"  EXCEPTION: {e}")
            errors += 1
        time.sleep(DELAY)

    csv_f.close()
    print(f"\nDone! Scraped: {scraped}, Errors: {errors}")
    print(f"Total images: {len(os.listdir(OUT_DIR))}")

if __name__ == "__main__":
    main()
