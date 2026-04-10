"""
HTML-based label rendering for multi-label print jobs.

Why HTML instead of PDF:
The browser PDF viewer -> Windows print dialog -> Dymo driver pipeline
is unreliable for multi-page custom-sized PDFs. Edge/Chrome often send
only page 1 to the printer. Rendering labels as an HTML page with
@page CSS and page-break-after lets the browser drive printing
directly, which is reliable across browsers and Dymo driver versions.

Each label is a fixed-size div. JsBarcode renders the Code128 barcode
as an SVG so it's crisp at any printer DPI. window.print() is called
automatically on page load.
"""

import datetime
import html as html_escape
from pathlib import Path


_JSBARCODE_SOURCE_CACHE: str | None = None


def _get_jsbarcode_source() -> str:
    """Load the JsBarcode minified source once and cache it.

    We inline JsBarcode into the generated label HTML instead of using
    <script src="/static/js/JsBarcode.all.min.js"> because the frontend
    opens the label document via a blob: URL (URL.createObjectURL +
    window.open). In that context, relative script-src resolution is
    unreliable across browsers and has been observed to silently fail
    in production, which results in the SVG barcode elements never
    being populated -- only the human-readable <div class="barcode-text">
    prints, with no bars above it.

    Inlining the library makes the rendered document fully
    self-contained, eliminating the network + origin variables.
    """
    global _JSBARCODE_SOURCE_CACHE
    if _JSBARCODE_SOURCE_CACHE is None:
        path = (
            Path(__file__).resolve().parent.parent.parent
            / "frontend" / "static" / "js" / "JsBarcode.all.min.js"
        )
        source = path.read_text(encoding="utf-8")
        # Escape </ so an embedded <script> block cannot be prematurely
        # closed by the HTML parser. This is the standard safe-embed
        # pattern for inlining third-party JS into HTML documents.
        _JSBARCODE_SOURCE_CACHE = source.replace("</", "<\\/")
    return _JSBARCODE_SOURCE_CACHE


def _fmt_price(value) -> str:
    try:
        return f"${value:.2f}"
    except Exception:
        return "$0.00"


def _active_price_for_item(item):
    today = datetime.date.today()
    price = item.price
    on_sale = False
    if (
        item.sale_price is not None
        and item.sale_start is not None
        and item.sale_end is not None
        and item.sale_start <= today <= item.sale_end
    ):
        price = item.sale_price
        on_sale = True
    return price, on_sale


def _label_div(item) -> str:
    name = html_escape.escape((item.name or "")[:22])
    active_price, on_sale = _active_price_for_item(item)
    price_str = html_escape.escape(_fmt_price(active_price))
    original_str = html_escape.escape(_fmt_price(item.price)) if on_sale else ""

    booth = getattr(item, "vendor", None)
    booth_number = ""
    if booth:
        booth_number = html_escape.escape(getattr(booth, "booth_number", "") or "")

    barcode_val = html_escape.escape(item.barcode or "")
    original_span = f'<span class="orig">{original_str}</span>' if on_sale else ""
    booth_span = f'<span class="booth">B{booth_number}</span>' if booth_number else ""

    return (
        '<div class="label">'
        f'<div class="name">{name}</div>'
        '<div class="divider"></div>'
        '<div class="price-row">'
        f'<span class="price">{price_str}</span>'
        f'{original_span}'
        f'{booth_span}'
        '</div>'
        f'<svg class="barcode" data-value="{barcode_val}"></svg>'
        f'<div class="barcode-text">{barcode_val}</div>'
        '</div>'
    )


def generate_label_html(items, label_width_in: float = 1.5, label_height_in: float = 1.0) -> str:
    page_w = f"{label_width_in}in"
    page_h = f"{label_height_in}in"
    labels_html = "\n".join(_label_div(item) for item in items)

    css = (
        "@page { size: " + page_w + " " + page_h + "; margin: 0; }"
        "html, body { margin: 0; padding: 0; background: #fff; color: #000;"
        " font-family: Arial, Helvetica, sans-serif;"
        " -webkit-print-color-adjust: exact; print-color-adjust: exact; }"
        ".label { box-sizing: border-box; width: " + page_w + "; height: " + page_h + ";"
        " padding: 0.08in 0.14in; page-break-after: always; break-after: page;"
        " display: flex; flex-direction: column; justify-content: flex-start; overflow: hidden; }"
        ".label:last-child { page-break-after: auto; break-after: auto; }"
        ".name { font-weight: 700; font-size: 8pt; line-height: 1.05;"
        " white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }"
        ".divider { border-top: 0.5pt solid #666; margin: 0.02in 0; }"
        ".price-row { display: flex; align-items: baseline; gap: 0.05in; font-weight: 700; }"
        ".price { font-size: 11pt; flex: 0 0 auto; }"
        ".orig { font-size: 7pt; color: #555; text-decoration: line-through; font-weight: 400; }"
        ".booth { margin-left: auto; font-size: 9pt; }"
        ".barcode { width: 100%; height: auto; display: block; margin-top: 0.03in; }"
        ".barcode-text { font-size: 6pt; text-align: center; letter-spacing: 0.02em; }"
        "@media screen {"
        " body { background: #222; padding: 1rem; }"
        " .label { background: #fff; margin: 0 auto 1rem auto; border: 1px solid #555;"
        " box-shadow: 0 2px 8px rgba(0,0,0,0.4); }"
        "}"
    )

    script = (
        "(function(){"
        "function renderAll(){"
        "var svgs=document.querySelectorAll('svg.barcode');"
        "svgs.forEach(function(svg){"
        "var val=svg.getAttribute('data-value')||'';"
        "if(!val)return;"
        "try{JsBarcode(svg,val,{format:'CODE128',width:1.6,height:32,"
        "displayValue:false,margin:0,background:'#ffffff',lineColor:'#000000'});}"
        "catch(e){console.error('Barcode render failed for',val,e);}"
        "});"
        "}"
        "function doPrint(){renderAll();setTimeout(function(){window.print();},1500);}"
        "if(document.readyState==='complete'){doPrint();}"
        "else{window.addEventListener('load',doPrint);}"
        "})();"
    )

    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>Print labels</title>\n"
        "<script>" + _get_jsbarcode_source() + "</script>\n"
        "<style>" + css + "</style>\n"
        "</head>\n"
        "<body>\n"
        + labels_html + "\n"
        "<script>" + script + "</script>\n"
        "</body>\n"
        "</html>\n"
    )
