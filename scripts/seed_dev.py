import asyncio
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select
from passlib.context import CryptContext

from app.config import settings
from app.models.vendor import Vendor
from app.models.item import Item

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_async_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    params.pop("sslmode", None)
    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))


engine = create_async_engine(get_async_url(settings.database_url))
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


VENDORS_DATA = [
    {
        "name": "Admin User",
        "email": "admin@bowenstreetmarket.com",
        "password": "admin123",
        "role": "admin",
        "booth_number": None,
        "monthly_rent": 0,
        "payout_method": "zelle",
        "zelle_handle": None,
        "phone": None,
    },
    {
        "name": "Jane Doe",
        "email": "cashier@bowenstreetmarket.com",
        "password": "cashier123",
        "role": "cashier",
        "booth_number": None,
        "monthly_rent": 0,
        "payout_method": "cash",
        "zelle_handle": None,
        "phone": None,
    },
    {
        "name": "Sarah Johnson",
        "email": "sarah@email.com",
        "password": "vendor123",
        "role": "vendor",
        "booth_number": "A-12",
        "monthly_rent": 175,
        "payout_method": "zelle",
        "zelle_handle": "920-555-0101",
        "phone": "920-555-0101",
    },
    {
        "name": "Mike Chen",
        "email": "mike@email.com",
        "password": "vendor123",
        "role": "vendor",
        "booth_number": "B-07",
        "monthly_rent": 200,
        "payout_method": "zelle",
        "zelle_handle": "920-555-0102",
        "phone": "920-555-0102",
    },
    {
        "name": "Linda Kowalski",
        "email": "linda@email.com",
        "password": "vendor123",
        "role": "vendor",
        "booth_number": "C-22",
        "monthly_rent": 150,
        "payout_method": "zelle",
        "zelle_handle": "920-555-0103",
        "phone": "920-555-0103",
    },
]

# 10 items per vendor. is_online=True for roughly half.
ITEMS_DATA = {
    "sarah@email.com": [
        {
            "name": "Sterling Silver Filigree Brooch",
            "category": "Jewelry",
            "price": 45.00,
            "quantity": 2,
            "is_online": True,
            "description": (
                "Delicate sterling silver brooch with intricate filigree scrollwork, circa 1940s. "
                "Measures 2 inches across with a secure C-clasp in good working order. "
                "A lovely accent for a coat lapel or wool scarf. "
                "Located in booth A-12. In-store pickup only."
            ),
        },
        {
            "name": "Hand-Quilted Lap Blanket",
            "category": "Handcrafted",
            "price": 85.00,
            "quantity": 1,
            "is_online": False,
            "description": (
                "Hand-quilted cotton lap blanket in a log cabin pattern using 100% cotton fabric. "
                "Measures 48x60 inches and is machine washable. "
                "Warm tones of burgundy, gold, and cream look at home on any sofa. "
                "Located in booth A-12. In-store pickup only."
            ),
        },
        {
            "name": "Antique Glass Inkwell",
            "category": "Vintage",
            "price": 28.00,
            "quantity": 1,
            "is_online": True,
            "description": (
                "Clear glass inkwell with a brass collar, early 1900s manufacture. "
                "Square-cut base with the glass stopper still intact and fitting snugly. "
                "A charming piece for a writing desk or display shelf. "
                "Located in booth A-12. In-store pickup only."
            ),
        },
        {
            "name": "Beeswax Pillar Candles Set of 3",
            "category": "Handcrafted",
            "price": 22.00,
            "quantity": 6,
            "is_online": False,
            "description": (
                "Hand-poured pure beeswax pillar candles in three heights — 3, 5, and 7 inches. "
                "Natural honey fragrance with a clean, slow burn and no synthetic additives. "
                "Burns cleaner than paraffin and drips minimally. "
                "Located in booth A-12. In-store pickup only."
            ),
        },
        {
            "name": "Pressed Flower Framed Art",
            "category": "Art",
            "price": 35.00,
            "quantity": 3,
            "is_online": True,
            "description": (
                "Original pressed botanical arrangement under glass in a 5x7 antique gold frame. "
                "Wildflowers and ferns gathered locally and preserved in a naturalist style. "
                "Each piece is one of a kind — colors and composition vary. "
                "Located in booth A-12. In-store pickup only."
            ),
        },
        {
            "name": "Vintage Hobnail Milk Glass Vase",
            "category": "Vintage",
            "price": 18.00,
            "quantity": 2,
            "is_online": False,
            "description": (
                "Hobnail milk glass vase in classic white, mid-century manufacture. "
                "Stands 8 inches tall with a ruffled top edge and no chips or cracks. "
                "Perfect for dried flowers or a windowsill display. "
                "Located in booth A-12. In-store pickup only."
            ),
        },
        {
            "name": "Crocheted Cotton Market Bag",
            "category": "Handcrafted",
            "price": 20.00,
            "quantity": 4,
            "is_online": True,
            "description": (
                "Hand-crocheted 100% cotton market bag in natural cream with an open weave that stretches to hold a full grocery run. "
                "Sturdy double-loop handles and a flat bottom when loaded. "
                "Folds to pocket size when empty. "
                "Located in booth A-12. In-store pickup only."
            ),
        },
        {
            "name": "Copper Enamel Drop Earrings",
            "category": "Jewelry",
            "price": 38.00,
            "quantity": 3,
            "is_online": False,
            "description": (
                "Hand-formed copper earrings with teal and rust enamel inlay, kiln-fired for durability. "
                "Approximately 1.5 inches long with hypoallergenic sterling silver ear wires. "
                "Each pair is hand-finished, so color variation is part of the charm. "
                "Located in booth A-12. In-store pickup only."
            ),
        },
        {
            "name": "Wooden Recipe Card Box",
            "category": "Handcrafted",
            "price": 32.00,
            "quantity": 2,
            "is_online": True,
            "description": (
                "Dovetail-jointed pine recipe box finished with beeswax, sized to hold standard 4x6 cards. "
                "Includes a set of 10 hand-lettered category dividers. "
                "The lid fits snugly and slides open with one hand. "
                "Located in booth A-12. In-store pickup only."
            ),
        },
        {
            "name": "1950s McCoy Pottery Planter",
            "category": "Vintage",
            "price": 55.00,
            "quantity": 1,
            "is_online": False,
            "description": (
                "Genuine McCoy pottery planter in matte green glaze with the McCoy mark on the base. "
                "Classic mid-century kidney shape, 10 inches long and 5 inches deep. "
                "No chips or cracks — exceptional condition for its age. "
                "Located in booth A-12. In-store pickup only."
            ),
        },
    ],

    "mike@email.com": [
        {
            "name": "Refinished Oak End Table",
            "category": "Furniture",
            "price": 95.00,
            "quantity": 1,
            "is_online": True,
            "description": (
                "Solid oak end table from the 1960s, fully stripped and refinished in a warm walnut stain with a satin polyurethane topcoat. "
                "Single lower shelf for storage, 24 inches tall and 18 inches square. "
                "Sturdy, level, and ready for your living room. "
                "Located in booth B-07. In-store pickup only."
            ),
        },
        {
            "name": "Pyrex Early American Nesting Bowls Set of 4",
            "category": "Vintage",
            "price": 65.00,
            "quantity": 1,
            "is_online": False,
            "description": (
                "Complete set of four Pyrex nesting bowls in the Early American pattern — brown and white with colonial motifs. "
                "Sizes 401 through 404, all present and in excellent condition with vibrant, unfaded color. "
                "A sought-after pattern for Pyrex collectors. "
                "Located in booth B-07. In-store pickup only."
            ),
        },
        {
            "name": "Hand-Thrown Stoneware Mug",
            "category": "Handcrafted",
            "price": 18.00,
            "quantity": 8,
            "is_online": True,
            "description": (
                "Wheel-thrown stoneware mug in a speckled grey glaze with a comfortable pulled handle. "
                "Holds 14 oz and is both microwave and dishwasher safe. "
                "Sturdy enough for daily use, distinctive enough to be your favorite. "
                "Located in booth B-07. In-store pickup only."
            ),
        },
        {
            "name": "1960s Western Electric Rotary Phone",
            "category": "Vintage",
            "price": 75.00,
            "quantity": 1,
            "is_online": False,
            "description": (
                "Vintage Western Electric rotary telephone in original harvest gold finish with intact dial and handset. "
                "Cord included; non-functional as a working phone but a striking mid-century display piece. "
                "All original parts — no replacement plastic. "
                "Located in booth B-07. In-store pickup only."
            ),
        },
        {
            "name": "Carved Walnut Charcuterie Board",
            "category": "Handcrafted",
            "price": 48.00,
            "quantity": 3,
            "is_online": True,
            "description": (
                "Edge-grain walnut charcuterie board with a juice groove along the perimeter and a carved finger grip on one end. "
                "Finished with food-safe mineral oil and measures 12x18 inches. "
                "Gets better looking with use and re-oiling. "
                "Located in booth B-07. In-store pickup only."
            ),
        },
        {
            "name": "Antique Brass Lion Door Knocker",
            "category": "Vintage",
            "price": 35.00,
            "quantity": 2,
            "is_online": False,
            "description": (
                "Cast brass lion's head door knocker with original patina, early 20th century. "
                "Heavy and solid with mounting screws still present on the backplate. "
                "Makes a bold statement on any front door. "
                "Located in booth B-07. In-store pickup only."
            ),
        },
        {
            "name": "Original Watercolor Botanical Study",
            "category": "Art",
            "price": 42.00,
            "quantity": 4,
            "is_online": True,
            "description": (
                "Original watercolor study of a wild bergamot plant painted on 140 lb cold press paper. "
                "Unframed, 9x12 inches, signed on the front and backed with a stiff board in a clear sleeve. "
                "Accurate enough for a botanist, warm enough for your kitchen wall. "
                "Located in booth B-07. In-store pickup only."
            ),
        },
        {
            "name": "Reclaimed Barn Wood Floating Shelf",
            "category": "Handcrafted",
            "price": 55.00,
            "quantity": 2,
            "is_online": False,
            "description": (
                "Floating shelf made from reclaimed barn wood with visible saw marks and natural weathering intact. "
                "Measures 36 inches long and 7 inches deep, with concealed keyhole hardware and wall anchors included. "
                "Holds up to 40 lbs when properly anchored. "
                "Located in booth B-07. In-store pickup only."
            ),
        },
        {
            "name": "1950s Dairy Tin Advertising Sign",
            "category": "Vintage",
            "price": 45.00,
            "quantity": 1,
            "is_online": True,
            "description": (
                "Embossed tin sign advertising a Wisconsin dairy brand, circa 1950s. "
                "Measures 12x16 inches with rolled edges and original hanging holes at the top. "
                "Minor surface patina adds to its authentic character. "
                "Located in booth B-07. In-store pickup only."
            ),
        },
        {
            "name": "Hand-Poured Cedarwood Soy Candle",
            "category": "Handcrafted",
            "price": 16.00,
            "quantity": 10,
            "is_online": False,
            "description": (
                "8 oz soy wax candle in a reusable amber glass jar with a cotton wick. "
                "Scented with cedarwood and vanilla — warm and grounding without being heavy. "
                "Burns approximately 45 hours. "
                "Located in booth B-07. In-store pickup only."
            ),
        },
    ],

    "linda@email.com": [
        {
            "name": "Hand-Knotted Freshwater Pearl Bracelet",
            "category": "Jewelry",
            "price": 72.00,
            "quantity": 2,
            "is_online": True,
            "description": (
                "Strand of freshwater pearls hand-knotted on silk with a sterling silver toggle clasp. "
                "Each pearl is individually knotted for security and proper spacing. "
                "Approximately 7.5 inches in length with a soft, natural luster. "
                "Located in booth C-22. In-store pickup only."
            ),
        },
        {
            "name": "Vintage Fiestaware Cobalt Dinner Plate",
            "category": "Vintage",
            "price": 25.00,
            "quantity": 4,
            "is_online": False,
            "description": (
                "Original Fiesta dinnerware dinner plate in cobalt blue, pre-1986 manufacture. "
                "10.5 inches across with the raised band design and original backstamp on the reverse. "
                "No chips, cracks, or crazing — a clean example of an iconic American pattern. "
                "Located in booth C-22. In-store pickup only."
            ),
        },
        {
            "name": "Needlepoint Floral Wall Hanging",
            "category": "Art",
            "price": 40.00,
            "quantity": 1,
            "is_online": True,
            "description": (
                "Framed needlepoint panel depicting a bouquet of roses worked in wool thread on linen canvas. "
                "Professionally framed under glass in a 12x16 maple frame. "
                "Rich jewel tones of red, pink, and green that suit any vintage interior. "
                "Located in booth C-22. In-store pickup only."
            ),
        },
        {
            "name": "Art Deco Gilt Powder Compact",
            "category": "Vintage",
            "price": 55.00,
            "quantity": 1,
            "is_online": False,
            "description": (
                "Gilt brass Art Deco powder compact with an engine-turned sunburst lid and original beveled mirror inside. "
                "Circa 1930s, in excellent condition with the original interior still present. "
                "The lid clicks shut cleanly and the hinge is tight. "
                "Located in booth C-22. In-store pickup only."
            ),
        },
        {
            "name": "Hand-Dyed Ice-Dye Silk Scarf",
            "category": "Handcrafted",
            "price": 60.00,
            "quantity": 3,
            "is_online": True,
            "description": (
                "Hand-dyed silk habotai scarf using an ice-dye technique for a fluid, watercolor-like effect. "
                "Measures 14x72 inches with hand-rolled edges and fiber-reactive dyes that won't fade. "
                "Each scarf is one of a kind — color runs in the listing photo are representative. "
                "Located in booth C-22. In-store pickup only."
            ),
        },
        {
            "name": "Faceted Garnet Drop Necklace",
            "category": "Jewelry",
            "price": 88.00,
            "quantity": 1,
            "is_online": False,
            "description": (
                "Natural faceted garnet beads hand-strung on silk with a sterling silver lobster clasp and extender chain. "
                "18 inches with a 2-inch drop pendant of clustered stones. "
                "Rich deep red color that shows in both natural and artificial light. "
                "Located in booth C-22. In-store pickup only."
            ),
        },
        {
            "name": "1940s Depression Glass Compote",
            "category": "Vintage",
            "price": 32.00,
            "quantity": 2,
            "is_online": True,
            "description": (
                "Pink Depression glass compote in the Sharon Cabbage Rose pattern, circa 1940s. "
                "Stands 6 inches tall on a pedestal base with no chips or cracks. "
                "The pale pink glass catches light in a way modern glass simply cannot replicate. "
                "Located in booth C-22. In-store pickup only."
            ),
        },
        {
            "name": "Linocut Print — Great Lakes Map",
            "category": "Art",
            "price": 30.00,
            "quantity": 5,
            "is_online": False,
            "description": (
                "Hand-carved and hand-printed linocut map of the Great Lakes region on cream Stonehenge paper. "
                "Edition of 25, each signed and numbered by the artist. "
                "Unframed, 8x10 inches — ready to mat or hang as-is. "
                "Located in booth C-22. In-store pickup only."
            ),
        },
        {
            "name": "Vegetable-Tanned Leather Journal",
            "category": "Handcrafted",
            "price": 24.00,
            "quantity": 6,
            "is_online": True,
            "description": (
                "Hand-sewn journal with a vegetable-tanned leather wrap cover and 200 pages of cream laid paper. "
                "Secured with a wrap-around leather cord that softens with use. "
                "Measures 5x7 inches and fits in most bags and coat pockets. "
                "Located in booth C-22. In-store pickup only."
            ),
        },
        {
            "name": "Natural Turquoise Chip Stretch Bracelet",
            "category": "Jewelry",
            "price": 15.00,
            "quantity": 8,
            "is_online": False,
            "description": (
                "Natural turquoise chip bracelet on strong stretch cord, one size fits most wrists comfortably. "
                "Chips are irregular and natural with visible matrix veining — no dye or enhancement. "
                "Pairs well with silver, copper, or other natural stone jewelry. "
                "Located in booth C-22. In-store pickup only."
            ),
        },
    ],
}

# Items seeded for TEST_ACCOUNTS vendors that have a booth
TEST_ITEMS_DATA = {
    "paula@email.com": [
        {
            "name": "Vintage Cast Iron Skillet 8-Inch",
            "category": "Kitchen",
            "price": 35.00,
            "quantity": 1,
            "is_online": True,
            "description": (
                "8-inch cast iron skillet with a near-black seasoned patina built up over decades of use. "
                "Cleaned, re-seasoned, and ready to cook on. Maker's mark visible on the handle stub. "
                "Cooks more evenly than anything new you can buy. "
                "Located in booth TEST-5. In-store pickup only."
            ),
        },
        {
            "name": "Quilted Potholder Set of 2",
            "category": "Handcrafted",
            "price": 12.00,
            "quantity": 5,
            "is_online": False,
            "description": (
                "Hand-sewn cotton potholders made from quilting fabric scraps in a nine-patch pattern. "
                "Double-layered with cotton batting for real heat protection. "
                "Each set has two matching 8x8 inch squares — bright, cheerful prints vary. "
                "Located in booth TEST-5. In-store pickup only."
            ),
        },
        {
            "name": "Mid-Century Teak Table Lamp",
            "category": "Furniture",
            "price": 110.00,
            "quantity": 1,
            "is_online": True,
            "description": (
                "1960s table lamp with a solid teak base and original brass fittings, rewired with a new grounded cord and inline switch. "
                "Stands 24 inches to the harp; takes a standard medium-base bulb. "
                "Shade not included — the base alone is a strong sculptural object. "
                "Located in booth TEST-5. In-store pickup only."
            ),
        },
        {
            "name": "Antique Roll-Top Bread Box",
            "category": "Vintage",
            "price": 65.00,
            "quantity": 1,
            "is_online": False,
            "description": (
                "Painted wood bread box with a roll-top lid, circa 1930s farmhouse. "
                "Original cream paint with a faint stenciled fruit motif on the front panel. "
                "The lid rolls smoothly and closes flush — a genuine piece of working Americana. "
                "Located in booth TEST-5. In-store pickup only."
            ),
        },
        {
            "name": "Hand-Painted Cardinal Ceramic Mug",
            "category": "Handcrafted",
            "price": 22.00,
            "quantity": 6,
            "is_online": True,
            "description": (
                "Wheel-thrown ceramic mug with a hand-painted cardinal motif in red and black underglaze beneath a food-safe clear glaze. "
                "Holds 12 oz and is microwave and dishwasher safe. "
                "A cheerful mug that brightens up a grey Wisconsin morning. "
                "Located in booth TEST-5. In-store pickup only."
            ),
        },
        {
            "name": "1970s Natural Cotton Macramé Wall Hanging",
            "category": "Vintage",
            "price": 48.00,
            "quantity": 1,
            "is_online": False,
            "description": (
                "Large macramé wall hanging in natural cotton cord with a driftwood dowel at the top. "
                "Measures approximately 24 inches wide by 36 inches long including fringe. "
                "Original 1970s piece — not a reproduction — with the warm patina of age. "
                "Located in booth TEST-5. In-store pickup only."
            ),
        },
        {
            "name": "Seed Bead Tassel Earrings",
            "category": "Jewelry",
            "price": 18.00,
            "quantity": 4,
            "is_online": True,
            "description": (
                "Hand-beaded tassel earrings with glass seed beads in turquoise, cream, and copper tones. "
                "Approximately 2.5 inches long with gold-filled ear wires. "
                "Lightweight despite their layered look — comfortable for all-day wear. "
                "Located in booth TEST-5. In-store pickup only."
            ),
        },
        {
            "name": "Wicker Hinged-Lid Picnic Basket",
            "category": "Vintage",
            "price": 28.00,
            "quantity": 1,
            "is_online": False,
            "description": (
                "Woven wicker basket with a hinged lid and leather strap closure, sized comfortably for two. "
                "Interior lining is intact and clean; no broken weave. "
                "A classic warm-weather carry that doubles as attractive kitchen storage. "
                "Located in booth TEST-5. In-store pickup only."
            ),
        },
        {
            "name": "Embroidered Linen Tea Towels Set of 2",
            "category": "Handcrafted",
            "price": 20.00,
            "quantity": 4,
            "is_online": True,
            "description": (
                "Pair of 18x28 inch pure linen tea towels with hand-embroidered herb motifs — one rosemary, one thyme. "
                "Hemstitched edges that won't fray, made from pre-washed linen that softens further with each wash. "
                "A practical gift that actually gets used. "
                "Located in booth TEST-5. In-store pickup only."
            ),
        },
        {
            "name": "Antique Brass Owl Bookends",
            "category": "Vintage",
            "price": 55.00,
            "quantity": 1,
            "is_online": False,
            "description": (
                "Matched pair of solid cast brass bookends in a stylized owl design, likely 1920s manufacture. "
                "Weighted with felt pads on the bases; each stands about 5 inches tall. "
                "Heavy enough to hold a full shelf of hardcovers without sliding. "
                "Located in booth TEST-5. In-store pickup only."
            ),
        },
    ],
}

TEST_ACCOUNTS = [
    {"name": "Nora",   "email": "nora@email.com",   "password": "vendor123", "role": "admin",  "booth_number": "TEST-1", "monthly_rent": 175},
    {"name": "Sammy",  "email": "sammy@email.com",  "password": "vendor123", "role": "admin",  "booth_number": "TEST-2", "monthly_rent": 200},
    {"name": "Ashley", "email": "ashley@email.com", "password": "vendor123", "role": "admin",  "booth_number": "TEST-3", "monthly_rent": 150},
    {"name": "Anne",   "email": "anne@email.com",   "password": "vendor123", "role": "admin",  "booth_number": "TEST-4", "monthly_rent": 175},
    {"name": "Paula",  "email": "paula@email.com",  "password": "vendor123", "role": "vendor", "booth_number": "TEST-5", "monthly_rent": 125},
]


async def _seed_items(db: AsyncSession, vendor: Vendor, items_list: list) -> int:
    seq = 1
    for idata in items_list:
        sku = f"BSM-{vendor.id:04d}-{seq:06d}"
        barcode_val = f"{vendor.id:04d}{seq:08d}"
        item = Item(
            vendor_id=vendor.id,
            sku=sku,
            barcode=barcode_val,
            name=idata["name"],
            category=idata["category"],
            price=idata["price"],
            description=idata.get("description"),
            quantity=idata.get("quantity", 1),
            is_online=idata.get("is_online", False),
            status="active",
        )
        db.add(item)
        seq += 1
    return len(items_list)


async def seed():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Vendor).where(Vendor.email == "admin@bowenstreetmarket.com")
        )
        if result.scalar_one_or_none():
            print("Database already seeded. Skipping.")
            return

        created_vendors = []
        for vdata in VENDORS_DATA:
            vendor = Vendor(
                name=vdata["name"],
                email=vdata["email"],
                password_hash=pwd_context.hash(vdata["password"]),
                role=vdata["role"],
                booth_number=vdata["booth_number"],
                monthly_rent=vdata["monthly_rent"],
                payout_method=vdata["payout_method"],
                zelle_handle=vdata["zelle_handle"],
                phone=vdata["phone"],
            )
            db.add(vendor)
            await db.flush()
            created_vendors.append(vendor)

        await db.flush()

        total_items = 0
        for vendor in created_vendors:
            if vendor.email in ITEMS_DATA:
                total_items += await _seed_items(db, vendor, ITEMS_DATA[vendor.email])

        await db.commit()

        print("\n" + "=" * 60)
        print("  BMM-POS SEED DATA")
        print("=" * 60)
        print("\nCREDENTIALS:")
        print("  Admin:    admin@bowenstreetmarket.com / admin123")
        print("  Cashier:  cashier@bowenstreetmarket.com / cashier123")
        print("  Sarah:    sarah@email.com / vendor123  (A-12, $175/mo)")
        print("  Mike:     mike@email.com / vendor123   (B-07, $200/mo)")
        print("  Linda:    linda@email.com / vendor123  (C-22, $150/mo)")
        print(f"\nVENDORS CREATED: {len(created_vendors)}")
        print(f"ITEMS CREATED:   {total_items} (10 per vendor)")
        print("=" * 60 + "\n")


async def seed_test_accounts():
    results = []
    async with AsyncSessionLocal() as db:
        for acct in TEST_ACCOUNTS:
            existing = await db.execute(
                select(Vendor).where(Vendor.email == acct["email"])
            )
            vendor = existing.scalar_one_or_none()
            if vendor:
                results.append((acct["email"], acct["role"], "already exists", 0))
                continue

            vendor = Vendor(
                name=acct["name"],
                email=acct["email"],
                password_hash=pwd_context.hash(acct["password"]),
                role=acct["role"],
                booth_number=acct["booth_number"],
                monthly_rent=acct["monthly_rent"],
                payout_method="zelle",
                zelle_handle=None,
                phone=None,
                status="active",
            )
            db.add(vendor)
            await db.flush()

            item_count = 0
            if acct["email"] in TEST_ITEMS_DATA:
                item_count = await _seed_items(db, vendor, TEST_ITEMS_DATA[acct["email"]])

            results.append((acct["email"], acct["role"], "created", item_count))

        await db.commit()

    print("\n" + "=" * 62)
    print("  TEST ACCOUNTS")
    print("=" * 62)
    print(f"  {'Email':<30} {'Role':<8} {'Status':<14} {'Items'}")
    print("-" * 62)
    for email, role, status, items in results:
        item_label = str(items) if items else "-"
        print(f"  {email:<30} {role:<8} {status:<14} {item_label}")
    print("=" * 62 + "\n")


async def main():
    await seed()
    await seed_test_accounts()


if __name__ == "__main__":
    asyncio.run(main())
