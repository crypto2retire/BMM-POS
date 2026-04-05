#!/usr/bin/env python3
import sys
import os, re, csv, time, requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote

sys.stdout.reconfigure(line_buffering=True)

BASE = "https://bowenstreet.ricoconsign.com"
OUT_DIR = "scraped_images"
CSV_FILE = "scraped_items.csv"
DELAY = 0.5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
}

CATEGORIES = [
    "Accesories", "Stickers", "Books", "Furniture", "Original Art",
    "Outside", "BowenStreet Repeats", "Handmade items", "Candles",
    "Cards", "Clothing", "Decorations", "Jewelry", "Vintage",
    "Specialty Items", "Upcycled Items", "Studio Class",
    "Vintage Furniture", "Second hand clothes", "Adult clothing",
    "Kids clothing", "Used furniture", "Vintage Clothing",
]

def get_soup(session, url):
    resp = session.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")

def get_product_urls(session):
    product_urls = set()
    pattern = re.compile(r"/store/product/[^/]+/([A-Za-z0-9]+)$")
    for cat in CATEGORIES:
        page = 1
        while True:
            url = f"{BASE}/store/category/{quote(cat)}"
            if page > 1:
                url = f"{BASE}/nextpage?page={page}&category={quote(cat)}"
            print(f"  Crawling: {cat} page {page}")
            try:
                soup = get_soup(session, url)
            except Exception as e:
                print(f"  Error: {e}")
                break
            links = soup.find_all("a", href=pattern)
            if not links:
                break
            new = 0
            for link in links:
                href = link.get("href", "")
                full = urljoin(BASE, href)
                if full not in product_urls:
                    product_urls.add(full)
                    new += 1
            print(f"    Found {new} new products (total: {len(product_urls)})")
            if new == 0:
                break
            page += 1
            time.sleep(DELAY)
    return list(product_urls)

def scrape_product(session, url):
    try:
        soup = get_soup(session, url)
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
            time.sleep(0.2)
        except Exception as e:
            print(f"    Image download failed: {e}")
    return filenames

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    session = requests.Session()
    print("=== Step 1: Collecting product URLs ===")
    product_urls = get_product_urls(session)
    print(f"\nTotal products found: {len(product_urls)}\n")
    print("=== Step 2: Scraping details and downloading images ===")
    fieldnames = ["sku","name","price","image_filenames","primary_image","product_url"]
    csv_f = open(CSV_FILE, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(csv_f, fieldnames=fieldnames)
    writer.writeheader()
    csv_f.flush()
    total_scraped = 0
    with_images = 0
    for i, url in enumerate(product_urls, 1):
        print(f"[{i}/{len(product_urls)}] {url}")
        product = scrape_product(session, url)
        if not product:
            continue
        filenames = download_images(session, product, OUT_DIR)
        row = {
            "sku": product["sku"],
            "name": product["name"],
            "price": product["price"],
            "image_filenames": "|".join(filenames),
            "primary_image": filenames[0] if filenames else "",
            "product_url": product["product_url"],
        }
        writer.writerow(row)
        csv_f.flush()
        total_scraped += 1
        if filenames:
            with_images += 1
        print(f"  SKU: {product['sku']} | Images: {len(filenames)} | Name: {product['name'][:50]}")
        time.sleep(DELAY)
    csv_f.close()
    print(f"\nDone!")
    print(f"  Total items scraped: {total_scraped}")
    print(f"  Items with images:   {with_images}")
    print(f"  Items without:       {total_scraped - with_images}")
    print(f"  CSV: {CSV_FILE}")
    print(f"  Images: {OUT_DIR}/")

if __name__ == "__main__":
    main()
