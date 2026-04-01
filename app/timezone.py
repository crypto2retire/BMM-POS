"""
Store timezone — America/Chicago (CST/CDT).
Follows wall clock time in Oshkosh, WI.
Import this everywhere instead of using ZoneInfo("America/Chicago") directly.
"""
from zoneinfo import ZoneInfo

STORE_TZ = ZoneInfo("America/Chicago")
