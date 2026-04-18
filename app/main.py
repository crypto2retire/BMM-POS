import os
import sys
import json
import traceback
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, PlainTextResponse, Response, FileResponse, HTMLResponse
from pathlib import Path
from sqlalchemy import text, select
from fastapi import Depends

logger = logging.getLogger("bmm-startup")
_startup_checks: list[dict] = []


def _record_startup_ok(task: str) -> None:
    _startup_checks.append({"task": task, "status": "ok"})


def _record_startup_failure(task: str, exc: Exception, *, critical: bool = False) -> None:
    _startup_checks.append(
        {
            "task": task,
            "status": "failed",
            "critical": critical,
            "error_type": type(exc).__name__,
        }
    )
    logger.exception("Startup task failed: %s", task)


def _startup_health_payload() -> dict:
    failed = [check["task"] for check in _startup_checks if check["status"] == "failed"]
    return {
        "status": "degraded" if failed else "ok",
        "startup_failure_count": len(failed),
        "startup_failed_tasks": failed,
    }


try:
    print("BMM-POS: importing database...", file=sys.stderr, flush=True)
    from app.database import AsyncSessionLocal, engine, Base
    print("BMM-POS: importing routers...", file=sys.stderr, flush=True)
    from app.routers import auth, vendors, items, sales, pos, assistant, storefront, storefront_assistant, rent, admin, reports, settings, studio, bulk_import, notifications, booth_showcase, data_sync, ai_writer, security_deposits
    from app.routers.diagnose import router as diagnose_router
    from app.routers.inventory_verify import router as inventory_verify_router
    print("BMM-POS: all imports OK", file=sys.stderr, flush=True)
except Exception as _import_err:
    print(f"BMM-POS FATAL IMPORT ERROR: {type(_import_err).__name__}: {_import_err}", file=sys.stderr, flush=True)
    traceback.print_exc(file=sys.stderr)
    raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    _startup_checks.clear()

    import app.models  # noqa: F401

    # ── Light schema check (create_all is idempotent, only creates missing tables) ──
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("BMM-POS: database schema OK", file=sys.stderr, flush=True)
        _record_startup_ok("database_schema")
    except Exception as e:
        print(f"BMM-POS: schema create_all FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("database_schema", e, critical=True)

    # ── DB connectivity check ──
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        print("BMM-POS: database connection OK", file=sys.stderr, flush=True)
        _record_startup_ok("database_connection")
    except Exception as e:
        print(f"BMM-POS: DATABASE CONNECTION FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("database_connection", e, critical=True)

    # ── Vendor balances backfill ──
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("""
                INSERT INTO vendor_balances (vendor_id, balance, rent_balance)
                SELECT v.id, 0.00, 0.00
                FROM vendors v
                LEFT JOIN vendor_balances vb ON vb.vendor_id = v.id
                WHERE vb.id IS NULL
            """))
            await session.commit()
            count = result.rowcount or 0
            if count > 0:
                print(
                    f"BMM-POS: created missing vendor_balances rows for {count} vendors",
                    file=sys.stderr,
                    flush=True,
                )
        _record_startup_ok("vendor_balances_backfill")
    except Exception as e:
        print(f"BMM-POS: vendor_balances backfill FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("vendor_balances_backfill", e)

    try:
        from app.models.vendor import Vendor
        import bcrypt
        import secrets as _secrets

        def make_hash(pw: str) -> str:
            return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

        admin_pw = os.environ.get("ADMIN_PASSWORD") or _secrets.token_urlsafe(16)
        cashier_pw = os.environ.get("CASHIER_PASSWORD") or _secrets.token_urlsafe(16)
        vendor_pw = _secrets.token_urlsafe(16)

        seed_accounts = [
            dict(name="Admin", email="admin@bowenstreetmarket.com", phone="920-555-0001",
                 booth_number=None, monthly_rent=0, password=admin_pw,
                 role="admin", is_vendor=False, is_active=True, commission_rate=0),
            dict(name="Cashier", email="cashier@bowenstreetmarket.com", phone="920-555-0005",
                 booth_number=None, monthly_rent=0, password=cashier_pw,
                 role="cashier", is_vendor=False, is_active=True, commission_rate=0),
            dict(name="Sarah Johnson", email="sarah@email.com", phone="920-555-0002",
                 booth_number="A-12", monthly_rent=250, password=vendor_pw,
                 role="vendor", is_vendor=True, is_active=True, commission_rate=0),
            dict(name="Mike Chen", email="mike@email.com", phone="920-555-0003",
                 booth_number="B-07", monthly_rent=300, password=vendor_pw,
                 role="vendor", is_vendor=True, is_active=True, commission_rate=0),
            dict(name="Linda Martinez", email="linda@email.com", phone="920-555-0004",
                 booth_number="C-22", monthly_rent=200, password=vendor_pw,
                 role="vendor", is_vendor=True, is_active=True, commission_rate=0),
            dict(name="Nora Williams", email="nora@email.com", phone="920-555-0006",
                 booth_number="D-01", monthly_rent=275, password=vendor_pw,
                 role="vendor", is_vendor=True, is_active=True, commission_rate=0),
            dict(name="Sammy Davis", email="sammy@email.com", phone="920-555-0007",
                 booth_number="D-05", monthly_rent=250, password=vendor_pw,
                 role="vendor", is_vendor=True, is_active=True, commission_rate=0),
            dict(name="Ashley Brown", email="ashley@email.com", phone="920-555-0008",
                 booth_number="E-02", monthly_rent=300, password=vendor_pw,
                 role="vendor", is_vendor=True, is_active=True, commission_rate=0),
            dict(name="Anne Taylor", email="anne@email.com", phone="920-555-0009",
                 booth_number="E-10", monthly_rent=225, password=vendor_pw,
                 role="vendor", is_vendor=True, is_active=True, commission_rate=0),
            dict(name="Paula Garcia", email="paula@email.com", phone="920-555-0010",
                 booth_number="F-03", monthly_rent=200, password=vendor_pw,
                 role="vendor", is_vendor=True, is_active=True, commission_rate=0),
        ]

        async with AsyncSessionLocal() as session:
            vendor_count_result = await session.execute(text("SELECT COUNT(*) FROM vendors"))
            vendor_count = int(vendor_count_result.scalar() or 0)

            if vendor_count == 0:
                for acct in seed_accounts:
                    password = acct.pop("password")
                    session.add(Vendor(**acct, password_hash=make_hash(password)))
                await session.commit()
                print(
                    f"BMM-POS: seeded {len(seed_accounts)} default vendor accounts",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                print(
                    f"BMM-POS: auto-seed skipped — {vendor_count} existing vendors detected",
                    file=sys.stderr,
                    flush=True,
                )
        _record_startup_ok("auto_seed_accounts")
    except Exception as e:
        print(f"BMM-POS: auto-seed FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("auto_seed_accounts", e)

    # ── Fix leftover admin+vendor hybrid accounts ──
    try:
        async with AsyncSessionLocal() as session:
            # Anyone with role=admin/cashier AND is_vendor=True should be role=vendor
            result = await session.execute(
                text("SELECT id, name, role FROM vendors WHERE role IN ('admin','cashier') AND is_vendor = true")
            )
            hybrids = result.fetchall()
            if hybrids:
                ids = [row[0] for row in hybrids]
                names = [f"{row[1]} (was {row[2]})" for row in hybrids]
                await session.execute(
                    text("UPDATE vendors SET role = 'vendor' WHERE id = ANY(:ids)"),
                    {"ids": ids},
                )
                await session.commit()
                print(
                    f"BMM-POS: fixed {len(ids)} hybrid accounts to vendor-only: {', '.join(names)}",
                    file=sys.stderr, flush=True,
                )
        _record_startup_ok("fix_hybrid_accounts")
    except Exception as e:
        print(f"BMM-POS: fix hybrid accounts FAILED — {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _record_startup_failure("fix_hybrid_accounts", e)

    startup_summary = _startup_health_payload()
    if startup_summary["startup_failure_count"]:
        print(
            "BMM-POS: startup completed with warnings — failed tasks: "
            + ", ".join(startup_summary["startup_failed_tasks"]),
            file=sys.stderr,
            flush=True,
        )
    else:
        print("BMM-POS: startup checks all passed", file=sys.stderr, flush=True)

    yield


app = FastAPI(
    title="BMM-POS",
    description="Bowenstreet Market POS System",
    version="1.0.0",
    lifespan=lifespan,
)

def _normalize_origin(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if "://" in value:
        return value.rstrip("/")
    return f"https://{value}".rstrip("/")


def _build_allowed_origins() -> list[str]:
    origins: list[str] = []

    for raw_value in (
        os.environ.get("REPLIT_DEV_DOMAIN", ""),
        *os.environ.get("REPLIT_DOMAINS", "").split(","),
        *os.environ.get("CORS_ALLOWED_ORIGINS", "").split(","),
        os.environ.get("PUBLIC_APP_ORIGIN", ""),
        os.environ.get("RAILWAY_PUBLIC_DOMAIN", ""),
    ):
        origin = _normalize_origin(raw_value)
        if origin and origin not in origins:
            origins.append(origin)

    # Same-origin requests do not need CORS, but localhost dev often does.
    for localhost_origin in (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5000",
        "http://127.0.0.1:5000",
    ):
        if localhost_origin not in origins:
            origins.append(localhost_origin)

    return origins


_allowed_origins = _build_allowed_origins()

app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)


@app.middleware("http")
async def static_cache_headers(request: Request, call_next):
    """Add Cache-Control to static assets (CSS, JS, images, fonts)."""
    response = await call_next(request)
    path = request.url.path.lower()
    if (path.endswith(".css") or path.endswith(".js") or path.endswith(".webp") or
            path.endswith(".png") or path.endswith(".jpg") or path.endswith(".jpeg") or
            path.endswith(".gif") or path.endswith(".svg") or path.endswith(".woff") or
            path.endswith(".woff2") or path.endswith(".ttf") or path.endswith(".ico")):
        response.headers["Cache-Control"] = "public, max-age=604800, immutable"
    return response


@app.middleware("http")
async def subdomain_landing_redirect(request: Request, call_next):
    """Route *.bowenstreetmarket.com subdomains to /{slug}."""
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    for domain in ("bowenstreetmarket.com", "www.bowenstreetmarket.com"):
        if host == domain or host == f"www.{domain}":
            break
    else:
        slug = host.split(".")[0]
        if slug and slug not in ("www", "api", "admin", "pos", "shop", "vendor"):
            if request.url.path in ("/", ""):
                from starlette.datastructures import URL
                scope = request.scope.copy()
                new_path = f"/{slug}"
                scope["path"] = new_path
                scope["path"] = new_path
                scope["raw_path"] = new_path.encode()
                request = Request(scope, request.receive)
    return await call_next(request)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    from fastapi.exceptions import HTTPException as FastAPIHTTPException
    from starlette.exceptions import HTTPException as StarletteHTTPException
    if isinstance(exc, (FastAPIHTTPException, StarletteHTTPException)):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    print(f"BMM-POS EXCEPTION on {request.method} {request.url.path}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    traceback.print_exc(file=sys.stderr)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/health")
async def health():
    return _startup_health_payload()


app.include_router(auth.router, prefix="/api/v1")
app.include_router(vendors.router, prefix="/api/v1")
app.include_router(items.router, prefix="/api/v1")
app.include_router(sales.router, prefix="/api/v1")
app.include_router(pos.router, prefix="/api/v1")
app.include_router(assistant.router, prefix="/api/v1")
app.include_router(storefront.router, prefix="/api/v1")
app.include_router(storefront_assistant.router, prefix="/api/v1")
app.include_router(rent.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(settings.router, prefix="/api/v1")
app.include_router(studio.router, prefix="/api/v1")
app.include_router(bulk_import.router, prefix="/api/v1")
app.include_router(inventory_verify_router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(booth_showcase.router, prefix="/api/v1")
app.include_router(security_deposits.router, prefix="/api/v1")
app.include_router(data_sync.router, prefix="/api/v1")
app.include_router(ai_writer.router, prefix="/api/v1")
app.include_router(diagnose_router, prefix="/api/v1")

@app.get("/llms.txt", response_class=PlainTextResponse)
async def llms_txt():
    path = Path("frontend/static/llms.txt")
    return PlainTextResponse(path.read_text())


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    path = Path("frontend/static/robots.txt")
    return PlainTextResponse(path.read_text())


@app.get("/sitemap.xml", response_class=Response)
async def sitemap_xml():
    """Dynamic sitemap: market home, /vendors hub, every published vendor
    landing page, and every specialty category page. Includes <lastmod>
    from BoothShowcase.updated_at when available.
    """
    import re as _sm_re
    from datetime import datetime, timezone as _tz
    from app.database import get_db as _get_db
    from app.models.booth_showcase import BoothShowcase

    BASE = "https://www.bowenstreetmarket.com"

    def _slug(s: str) -> str:
        s = _sm_re.sub(r"[^\w\s-]", "", (s or "").lower()).strip()
        return _sm_re.sub(r"[-\s]+", "-", s) or "misc"

    urls: list[tuple[str, str | None, str, str]] = []
    # (loc, lastmod, changefreq, priority)

    today = datetime.now(_tz.utc).date().isoformat()

    urls.append((f"{BASE}/", today, "daily", "1.0"))
    urls.append((f"{BASE}/shop/index.html", today, "daily", "0.9"))
    urls.append((f"{BASE}/shop/booths.html", today, "weekly", "0.8"))
    urls.append((f"{BASE}/vendors", today, "weekly", "0.8"))

    try:
        async for db in _get_db():
            result = await db.execute(
                select(BoothShowcase)
                .where(BoothShowcase.is_published == True)
            )
            showcases = result.scalars().all()

            specialty_latest: dict = {}  # slug -> (display_name, latest_updated_at)

            for sc in showcases:
                lastmod = sc.updated_at.date().isoformat() if sc.updated_at else today

                if sc.landing_page_enabled and sc.landing_slug:
                    urls.append((f"{BASE}/{sc.landing_slug}", lastmod, "weekly", "0.7"))

                for spec in (sc.landing_specialties or []):
                    # If landing_page_enabled is not explicitly set, assume True for backward compat
                    enabled = sc.landing_page_enabled if sc.landing_page_enabled is not None else True
                    if not enabled:
                        continue
                    name = str(spec or "").strip()
                    if not name:
                        continue
                    slug = _slug(name)
                    prev = specialty_latest.get(slug)
                    if prev is None or (sc.updated_at and (prev[1] is None or sc.updated_at > prev[1])):
                        specialty_latest[slug] = (name[:60], sc.updated_at)

            for slug, (_name, updated) in specialty_latest.items():
                lastmod = updated.date().isoformat() if updated else today
                urls.append((f"{BASE}/specialty/{slug}", lastmod, "weekly", "0.6"))
            break
    except Exception as exc:
        logging.getLogger(__name__).warning("sitemap generation fell back: %s", exc)

    # Deduplicate by loc (preserving first occurrence / priority)
    seen = set()
    unique = []
    for u in urls:
        if u[0] in seen:
            continue
        seen.add(u[0])
        unique.append(u)

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, lastmod, cf, pr in unique:
        parts.append("  <url>")
        parts.append(f"    <loc>{loc}</loc>")
        if lastmod:
            parts.append(f"    <lastmod>{lastmod}</lastmod>")
        parts.append(f"    <changefreq>{cf}</changefreq>")
        parts.append(f"    <priority>{pr}</priority>")
        parts.append("  </url>")
    parts.append('</urlset>')

    return Response(content="\n".join(parts), media_type="application/xml")


def _mix_hex(fg: str, bg: str, opacity: float) -> str:
    """Mix two hex colors, returning a hex string."""
    try:
        fg = fg.lstrip("#")
        bg = bg.lstrip("#")
        if len(fg) == 3:
            fg = fg[0] * 2 + fg[1] * 2 + fg[2] * 2
        if len(bg) == 3:
            bg = bg[0] * 2 + bg[1] * 2 + bg[2] * 2
        fn, bn = int(fg, 16), int(bg, 16)
        r = round(((fn >> 16) & 255) * opacity + ((bn >> 16) & 255) * (1 - opacity))
        g = round(((fn >> 8) & 255) * opacity + ((bn >> 8) & 255) * (1 - opacity))
        b = round((fn & 255) * opacity + (bn & 255) * (1 - opacity))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return fg


# ── Phase 3: SEO hub + specialty category pages ──────────────────────
@app.get("/vendors", response_class=HTMLResponse)
async def vendors_hub_page(request: Request):
    """Server-rendered A–Z vendor directory with JSON-LD CollectionPage/ItemList.
    Client JS fetches /api/v1/booth-showcase/public + /api/v1/storefront/specialties
    and renders the full filterable grid. Server renders meta + JSON-LD for SEO.
    """
    from html import escape as _html_esc
    page = Path("frontend/shop/vendors.html")
    if not page.exists():
        return HTMLResponse("<h1>Page not found</h1>", status_code=404)
    html = page.read_text(encoding="utf-8")

    page_url = "https://www.bowenstreetmarket.com/vendors"
    try:
        from app.database import get_db as _get_db
        from app.models.booth_showcase import BoothShowcase
        async for db in _get_db():
            result = await db.execute(
                select(BoothShowcase)
                .where(BoothShowcase.is_published == True)
                .where(BoothShowcase.landing_page_enabled == True)
            )
            showcases = result.scalars().all()
            vendor_count = len(showcases)

            list_items = []
            for idx, sc in enumerate(showcases[:50], start=1):
                if not sc.vendor or not sc.landing_slug:
                    continue
                list_items.append({
                    "@type": "ListItem",
                    "position": idx,
                    "url": f"https://www.bowenstreetmarket.com/{sc.landing_slug}",
                    "name": sc.vendor.name,
                })

            ld = {
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "CollectionPage",
                        "@id": f"{page_url}#page",
                        "url": page_url,
                        "name": "All Vendors — Bowenstreet Market",
                        "description": f"Browse all {vendor_count} vendors at Bowenstreet Market in Oshkosh, WI.",
                        "isPartOf": {"@type": "WebSite", "name": "Bowenstreet Market", "url": "https://www.bowenstreetmarket.com"},
                    },
                    {
                        "@type": "BreadcrumbList",
                        "itemListElement": [
                            {"@type": "ListItem", "position": 1, "name": "Bowenstreet Market", "item": "https://www.bowenstreetmarket.com/"},
                            {"@type": "ListItem", "position": 2, "name": "Vendors", "item": page_url},
                        ],
                    },
                    {
                        "@type": "ItemList",
                        "name": "All Vendors",
                        "numberOfItems": vendor_count,
                        "itemListElement": list_items,
                    },
                ],
            }
            jsonld_esc = _html_esc(json.dumps(ld, ensure_ascii=False), quote=False)
            html = html.replace(
                '<script type="application/ld+json" id="hub-jsonld"></script>',
                f'<script type="application/ld+json" id="hub-jsonld">{jsonld_esc}</script>',
            )
            html = html.replace(
                '<!--VENDOR_COUNT-->',
                _html_esc(str(vendor_count)),
            )
            break
    except Exception as exc:
        logging.getLogger(__name__).warning("/vendors server-render fell back: %s", exc)

    return HTMLResponse(html)


@app.get("/specialty/{slug}", response_class=HTMLResponse)
async def specialty_page(slug: str, request: Request):
    """Server-rendered specialty category page (e.g. /specialty/vintage-books).
    Validates the slug against published showcases; 404 otherwise. Injects
    title, canonical, OG, and JSON-LD ItemList. Client JS does fetch-to-render.
    """
    import re as _sp_re
    from html import escape as _html_esc

    if "." in slug or "/" in slug or not _sp_re.fullmatch(r"[a-z0-9-]{1,80}", slug):
        raise HTTPException(status_code=404)

    page = Path("frontend/shop/specialty.html")
    if not page.exists():
        return HTMLResponse("<h1>Page not found</h1>", status_code=404)
    html = page.read_text(encoding="utf-8")

    def _slug(s: str) -> str:
        s = _sp_re.sub(r"[^\w\s-]", "", (s or "").lower()).strip()
        return _sp_re.sub(r"[-\s]+", "-", s) or "misc"

    try:
        from app.database import get_db as _get_db
        from app.models.booth_showcase import BoothShowcase
        async for db in _get_db():

                raise HTTPException(status_code=404, detail="Specialty not found")

            page_url = f"https://www.bowenstreetmarket.com/specialty/{slug}"
            title = f"{display_name} Vendors — Bowenstreet Market"
            desc = (
                f"Browse {len(matching)} vendors specializing in {display_name.lower()} "
                f"at Bowenstreet Market in Oshkosh, WI. See their booths, stories, and inventory."
            )
            if len(desc) > 160:
                desc = desc[:157] + "…"

            list_items = []
            for idx, sc in enumerate(matching[:50], start=1):
                if not sc.vendor or not sc.landing_slug:
                    continue
                list_items.append({
                    "@type": "ListItem",
                    "position": idx,
                    "url": f"https://www.bowenstreetmarket.com/{sc.landing_slug}",
                    "name": sc.vendor.name,
                })

            ld = {
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "CollectionPage",
                        "@id": f"{page_url}#page",
                        "url": page_url,
                        "name": title,
                        "description": desc,
                        "isPartOf": {"@type": "WebSite", "name": "Bowenstreet Market", "url": "https://www.bowenstreetmarket.com"},
                    },
                    {
                        "@type": "BreadcrumbList",
                        "itemListElement": [
                            {"@type": "ListItem", "position": 1, "name": "Bowenstreet Market", "item": "https://www.bowenstreetmarket.com/"},
                            {"@type": "ListItem", "position": 2, "name": "Vendors", "item": "https://www.bowenstreetmarket.com/vendors"},
                            {"@type": "ListItem", "position": 3, "name": display_name, "item": page_url},
                        ],
                    },
                    {
                        "@type": "ItemList",
                        "name": f"Vendors — {display_name}",
                        "numberOfItems": len(matching),
                        "itemListElement": list_items,
                    },
                ],
            }

            title_esc = _html_esc(title, quote=True)
            desc_esc = _html_esc(desc, quote=True)
            name_esc = _html_esc(display_name, quote=False)
            slug_esc = _html_esc(slug, quote=True)
            jsonld_esc = _html_esc(json.dumps(ld, ensure_ascii=False), quote=False)

            html = html.replace('<!--SPECIALTY_TITLE-->', title_esc)
            html = html.replace('<!--SPECIALTY_DESC-->', desc_esc)
            html = html.replace('<!--SPECIALTY_NAME-->', name_esc)
            html = html.replace('<!--SPECIALTY_SLUG-->', slug_esc)
            html = html.replace('<!--SPECIALTY_URL-->', page_url)
            html = html.replace(
                '<script type="application/ld+json" id="specialty-jsonld"></script>',
                f'<script type="application/ld+json" id="specialty-jsonld">{jsonld_esc}</script>',
            )
            break
    except HTTPException:
        raise
    except Exception as exc:
        logging.getLogger(__name__).warning("/specialty/%s server-render fell back: %s", slug, exc)

    return HTMLResponse(html)


@app.get("/og/{filename}")
async def og_image_root(filename: str):
    """Serve OG image at /og/{slug}.png by delegating to the booth-showcase
    router. This lets the vendor landing page reference a clean,
    top-level og:image URL.
    """
    from fastapi import HTTPException as _HTTPException
    if not filename.endswith(".png") and not filename.endswith(".jpg"):
        raise _HTTPException(status_code=404)
    slug = filename.rsplit(".", 1)[0]
    if not slug:
        raise _HTTPException(status_code=404)
    from app.database import get_db as _get_db
    from app.routers.booth_showcase import get_og_image as _get_og_image
    async for db in _get_db():
        return await _get_og_image(slug=slug, db=db)
    raise _HTTPException(status_code=500)


@app.get("/{slug}")
async def vendor_landing_page(slug: str, request: Request):
    # Root-level vendor landing pages: bowenstreetmarket.com/{vendor-name}
    # Only match simple slugs — no dots, no slashes, not a known directory
    if "." in slug or "/" in slug:
        raise HTTPException(status_code=404)
    _reserved = ("shop", "admin", "pos", "vendor", "vendors", "specialty",
                 "static", "api", "health", "favicon", "manifest", "robots",
                 "llms", "sitemaps", "sitemap", "docs", "og")
    if slug in _reserved:
        raise HTTPException(status_code=404)
    page = Path("frontend/shop/vendor-page.html")
    if not page.exists():
        return HTMLResponse("<h1>Page not found</h1>", status_code=404)

    html = page.read_text(encoding="utf-8")

    debug_mode = request.query_params.get("debug") == "1"

    # ── Server-side theme pre-render ──
    # Fetch showcase + vendor in one shot to avoid extra queries
    try:
        from app.database import get_db as _get_db
        from app.models.booth_showcase import BoothShowcase
        from html import escape as _html_esc

        async for db in _get_db():
            result = await db.execute(
                select(BoothShowcase)
                .where(
                    BoothShowcase.landing_slug == slug,
                    BoothShowcase.landing_page_enabled == True,
                )
            )
            sc = result.scalar_one_or_none()

            if debug_mode:
                debug_payload = {
                    "slug": slug,
                    "record_found": bool(sc),
                    "landing_page_enabled": bool(sc.landing_page_enabled) if sc else False,
                    "landing_template": (sc.landing_template or "classic") if sc else None,
                    "landing_theme": sc.landing_theme if sc else None,
                    "updated_at": sc.updated_at.isoformat() if (sc and sc.updated_at) else None,
                }
                debug_json = _html_esc(json.dumps(debug_payload, indent=2), quote=False)
                html = html.replace(
                    '<div id="admin-debug-banner" class="admin-debug-banner" aria-live="polite"></div>',
                    '<div id="admin-debug-banner" class="admin-debug-banner" aria-live="polite" style="display:block">'
                    '<div class="debug-title">Debug Query: server-side landing payload snapshot</div>'
                    f'<div>Source: <code>/api/v1/booth-showcase/landing/{_html_esc(slug)}</code></div>'
                    f'<div class="debug-values"><code>{debug_json}</code></div>'
                    '</div>',
                )

            if sc and sc.landing_theme:
                theme = sc.landing_theme
                template = sc.landing_template or "classic"
                c = theme.get("colors", {})
                f = theme.get("fonts", {})
                text_c = c.get("text", "#111827")
                bg_c = c.get("background", "#F9FAFB")
                primary = c.get("primary", "#2563EB")
                secondary = c.get("secondary", "#64748B")
                card_bg = c.get("card_background", "#FFFFFF")
                accent = c.get("accent", primary)

                border_c = _mix_hex(text_c, bg_c, 0.15)

                css_vars = (
                    f"--landing-primary: {primary};"
                    f"--landing-secondary: {secondary};"
                    f"--landing-background: {bg_c};"
                    f"--landing-text: {text_c};"
                    f"--landing-accent: {accent};"
                    f"--landing-card-bg: {card_bg};"
                    f"--landing-bg-dark: {bg_c};"
                    f"--landing-border: {border_c};"
                    f"--landing-heading-font: '{f.get('heading', 'Inter')}', serif;"
                    f"--landing-heading-weight: {f.get('heading_weight', '600')};"
                    f"--landing-heading-style: {f.get('heading_style', 'normal')};"
                    f"--landing-body-font: '{f.get('body', 'Inter')}', sans-serif;"
                    f"--landing-body-weight: {f.get('body_weight', '400')};"
                )

                # 1. Swap body class
                html = html.replace('class="no-theme"', 'class="themed"')

                # 2. Swap template CSS link
                html = html.replace(
                    'href="/static/css/landing-classic.css"',
                    f'href="/static/css/landing-{template}.css"',
                )

                # 3. Inject CSS variables
                html = html.replace(
                    '<style id="theme-vars"></style>',
                    f'<style id="theme-vars">:root {{ {css_vars} }}'
                    'body.themed, body.themed * { background-image: none !important; background-attachment: scroll !important; }'
                    '</style>',
                )

                # 4. Add inline styles on body to guarantee no FOUC
                html = html.replace(
                    '<body class="themed">',
                    f'<body class="themed" style="background:{bg_c};color:{text_c}">',
                )

                # 5. Pre-render SEO meta tags
                vendor_name = sc.vendor.name if sc.vendor else "Vendor"
                title = sc.landing_meta_title or f"{vendor_name} — Bowenstreet Market"

                # Phase 2: if no explicit meta_desc, fall back to the first populated story
                # block — this gives every vendor a unique SERP snippet instead of the same
                # "Shop {name} at Bowenstreet Market" filler across every page.
                fallback_desc = None
                story_blocks = sc.landing_story_blocks or {}
                if isinstance(story_blocks, dict):
                    for _key in ("specialty", "origin", "process", "values", "whats_new"):
                        _val = (story_blocks.get(_key) or "").strip()
                        if _val:
                            # Condense to a clean single-line ≤160 chars for meta description
                            _clean = " ".join(_val.split())
                            fallback_desc = _clean[:157] + "…" if len(_clean) > 160 else _clean
                            break
                if not fallback_desc and (sc.landing_about or "").strip():
                    _clean = " ".join(sc.landing_about.split())
                    fallback_desc = _clean[:157] + "…" if len(_clean) > 160 else _clean
                desc = (
                    sc.landing_meta_desc
                    or fallback_desc
                    or f"Shop {vendor_name} at Bowenstreet Market in Oshkosh, WI."
                )
                photos = sc.photo_urls or []

                title_esc = _html_esc(title, quote=True)
                desc_esc = _html_esc(desc, quote=True)

                html = html.replace(
                    '<title id="page-title">Vendor — Bowenstreet Market</title>',
                    f'<title id="page-title">{title_esc}</title>',
                )
                html = html.replace(
                    'name="description" content="Visit this vendor\'s booth at Bowenstreet Market — handcrafted, vintage, and antique goods in Oshkosh, Wisconsin."',
                    f'name="description" content="{desc_esc}"',
                )
                html = html.replace(
                    'property="og:title" content="Vendor — Bowenstreet Market"',
                    f'property="og:title" content="{title_esc}"',
                )
                html = html.replace(
                    'property="og:description" content="Visit this vendor\'s booth at Bowenstreet Market."',
                    f'property="og:description" content="{desc_esc}"',
                )
                html = html.replace(
                    'property="og:url" content=""',
                    f'property="og:url" content="https://www.bowenstreetmarket.com/{slug}"',
                )
                # Prefer the dynamic OG image route over the raw cover photo
                # so we always get a branded, 1200×630, text-overlaid card.
                og_image_url = f"https://www.bowenstreetmarket.com/og/{slug}.png"
                html = html.replace(
                    'property="og:image" content=""',
                    f'property="og:image" content="{og_image_url}"',
                )
                # Also add twitter:image if the template lacks it
                if 'name="twitter:image"' not in html:
                    html = html.replace(
                        f'property="og:image" content="{og_image_url}"',
                        f'property="og:image" content="{og_image_url}">\n    <meta name="twitter:image" content="{og_image_url}"',
                    )
                html = html.replace(
                    '<link rel="canonical" href="">',
                    f'<link rel="canonical" href="https://www.bowenstreetmarket.com/{slug}">',
                )

                # ── JSON-LD (LocalBusiness + FAQPage + BreadcrumbList) ──
                try:
                    page_url = f"https://www.bowenstreetmarket.com/{slug}"
                    specialties = list(sc.landing_specialties or [])
                    ld_nodes = []

                    # LocalBusiness (vendor-scoped, parented to the market)
                    business_node = {
                        "@context": "https://schema.org",
                        "@type": "LocalBusiness",
                        "@id": f"{page_url}#vendor",
                        "name": vendor_name,
                        "url": page_url,
                        "description": desc,
                        "parentOrganization": {
                            "@type": "Organization",
                            "name": "Bowenstreet Market",
                            "url": "https://www.bowenstreetmarket.com",
                        },
                        "address": {
                            "@type": "PostalAddress",
                            "streetAddress": "437 Bowen St",
                            "addressLocality": "Oshkosh",
                            "addressRegion": "WI",
                            "postalCode": "54901",
                            "addressCountry": "US",
                        },
                    }
                    if photos:
                        business_node["image"] = photos[:5]
                    if specialties:
                        business_node["makesOffer"] = [
                            {"@type": "Offer", "itemOffered": {"@type": "Product", "name": s}}
                            for s in specialties[:6]
                        ]
                        business_node["keywords"] = ", ".join(specialties[:8])
                    if sc.landing_year_started:
                        business_node["foundingDate"] = str(sc.landing_year_started)
                    ld_nodes.append(business_node)

                    # BreadcrumbList
                    ld_nodes.append({
                        "@context": "https://schema.org",
                        "@type": "BreadcrumbList",
                        "itemListElement": [
                            {"@type": "ListItem", "position": 1, "name": "Bowenstreet Market", "item": "https://www.bowenstreetmarket.com/"},
                            {"@type": "ListItem", "position": 2, "name": "Vendors", "item": "https://www.bowenstreetmarket.com/vendors"},
                            {"@type": "ListItem", "position": 3, "name": vendor_name, "item": page_url},
                        ],
                    })

                    # FAQPage (parses simple Q:/A: or line-pair format from landing_faq)
                    if sc.landing_faq:
                        faq_entities = []
                        raw_lines = [ln.strip() for ln in (sc.landing_faq or "").splitlines() if ln.strip()]
                        pending_q = None
                        for ln in raw_lines:
                            lower = ln.lower()
                            if lower.startswith("q:") or lower.startswith("q.") or lower.endswith("?"):
                                pending_q = ln.lstrip("QqQ:.").strip() if ln.lower().startswith("q") else ln
                                # normalize Q prefixes
                                if pending_q.lower().startswith("q:"): pending_q = pending_q[2:].strip()
                            elif pending_q and (lower.startswith("a:") or lower.startswith("a.") or True):
                                ans = ln
                                if ans.lower().startswith("a:"): ans = ans[2:].strip()
                                faq_entities.append({
                                    "@type": "Question",
                                    "name": pending_q,
                                    "acceptedAnswer": {"@type": "Answer", "text": ans},
                                })
                                pending_q = None
                        if faq_entities:
                            ld_nodes.append({
                                "@context": "https://schema.org",
                                "@type": "FAQPage",
                                "mainEntity": faq_entities[:20],
                            })

                    ld_script = "\n".join(
                        f'<script type="application/ld+json">{json.dumps(n, ensure_ascii=False)}</script>'
                        for n in ld_nodes
                    )
                    html = html.replace("</head>", ld_script + "\n</head>", 1)
                except Exception:
                    logger.exception("vendor_landing_page: JSON-LD injection failed")

            break  # only need one db session
    except Exception:
        logger.exception("vendor_landing_page: pre-render failed, serving unmodified")

    return HTMLResponse(
        html,
        media_type="text/html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/shop/vendor/{vendor_id:int}")
async def vendor_inventory_page(vendor_id: int):
    page = Path("frontend/shop/vendor-inventory.html")
    if page.exists():
        return FileResponse(page, media_type="text/html")
    return HTMLResponse("<h1>Page not found</h1>", status_code=404)


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
