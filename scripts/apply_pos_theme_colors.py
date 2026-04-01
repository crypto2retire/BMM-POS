#!/usr/bin/env python3
"""Bulk-replace hardcoded colors in POS HTML with CSS variables (task-theme-5)."""
from __future__ import annotations

import re
import sys

# Longest / most specific first within groups
RGBA_REPLACEMENTS: list[tuple[str, str]] = [
    ("rgba(201,169,110,0.8)", "color-mix(in srgb, var(--gold) 80%, transparent)"),
    ("rgba(201,169,110,0.5)", "color-mix(in srgb, var(--gold) 50%, transparent)"),
    ("rgba(201,169,110,0.4)", "color-mix(in srgb, var(--gold) 40%, transparent)"),
    ("rgba(201,169,110,0.35)", "color-mix(in srgb, var(--gold) 35%, transparent)"),
    ("rgba(201,169,110,0.3)", "color-mix(in srgb, var(--gold) 30%, transparent)"),
    ("rgba(201,169,110,0.25)", "color-mix(in srgb, var(--gold) 25%, transparent)"),
    ("rgba(201,169,110,0.2)", "color-mix(in srgb, var(--gold) 20%, transparent)"),
    ("rgba(201,169,110,0.15)", "color-mix(in srgb, var(--gold) 15%, transparent)"),
    ("rgba(201,169,110,0.12)", "var(--gold-glow)"),
    ("rgba(201,169,110,0.1)", "color-mix(in srgb, var(--gold) 10%, transparent)"),
    ("rgba(201,169,110,0.08)", "color-mix(in srgb, var(--gold) 8%, transparent)"),
    ("rgba(201,169,110,0.06)", "color-mix(in srgb, var(--gold) 6%, transparent)"),
    ("rgba(201,169,110,0.05)", "color-mix(in srgb, var(--gold) 5%, transparent)"),
    ("rgba(201,169,110,0.04)", "color-mix(in srgb, var(--gold) 4%, transparent)"),
    ("rgba(201,169,110,0.03)", "color-mix(in srgb, var(--gold) 3%, transparent)"),
    ("rgba(240,237,232,0.6)", "color-mix(in srgb, var(--text) 60%, transparent)"),
    ("rgba(255,255,255,0.15)", "color-mix(in srgb, var(--white) 15%, transparent)"),
    ("rgba(255,255,255,0.1)", "color-mix(in srgb, var(--white) 10%, transparent)"),
    ("rgba(255,255,255,0.08)", "color-mix(in srgb, var(--white) 8%, transparent)"),
    ("rgba(255,255,255,0.06)", "color-mix(in srgb, var(--white) 6%, transparent)"),
    ("rgba(255,255,255,0.05)", "color-mix(in srgb, var(--white) 5%, transparent)"),
    ("rgba(255,255,255,0.04)", "color-mix(in srgb, var(--white) 4%, transparent)"),
    ("rgba(255,255,255,0.6)", "color-mix(in srgb, var(--white) 60%, transparent)"),
    ("rgba(168,166,161,0.1)", "color-mix(in srgb, var(--text-light) 10%, transparent)"),
    ("rgba(168,166,161,0.07)", "color-mix(in srgb, var(--text-light) 7%, transparent)"),
    ("rgba(168,166,161,0.03)", "color-mix(in srgb, var(--text-light) 3%, transparent)"),
    ("rgba(200,112,112,0.3)", "color-mix(in srgb, var(--danger) 30%, transparent)"),
    ("rgba(200,112,112,0.2)", "color-mix(in srgb, var(--danger) 20%, transparent)"),
    ("rgba(200,112,112,0.12)", "color-mix(in srgb, var(--danger) 12%, transparent)"),
    ("rgba(200,112,112,0.1)", "color-mix(in srgb, var(--danger) 10%, transparent)"),
    ("rgba(123,196,160,0.3)", "color-mix(in srgb, var(--success-light) 30%, transparent)"),
    ("rgba(123,196,160,0.2)", "color-mix(in srgb, var(--success-light) 20%, transparent)"),
    ("rgba(20,122,84,0.15)", "color-mix(in srgb, var(--success) 15%, transparent)"),
    ("rgba(0,0,0,0.88)", "color-mix(in srgb, black 88%, transparent)"),
    ("rgba(0,0,0,0.78)", "color-mix(in srgb, black 78%, transparent)"),
    ("rgba(0,0,0,0.6)", "color-mix(in srgb, black 60%, transparent)"),
    ("rgba(0,0,0,0.5)", "color-mix(in srgb, black 50%, transparent)"),
    ("rgba(0,0,0,0.35)", "color-mix(in srgb, black 35%, transparent)"),
    ("rgba(0,0,0,0.3)", "color-mix(in srgb, black 30%, transparent)"),
    ("rgba(0,0,0,0.2)", "color-mix(in srgb, black 20%, transparent)"),
]

# 6-digit hex -> var(...)  (apply case-insensitive; skip #1a1a1d per task-theme-5)
HEX_REPLACEMENTS: list[tuple[str, str]] = [
    ("#c9a96e", "var(--gold)"),
    ("#c9a84c", "var(--gold)"),
    ("#b8954f", "var(--gold-dim)"),
    ("#38383b", "var(--bg)"),
    ("#2a2825", "var(--bg)"),
    ("#1e1e20", "var(--bg)"),
    ("#44444a", "var(--surface)"),
    ("#353230", "var(--surface)"),
    ("#4e4e54", "var(--surface-2)"),
    ("#3e3b38", "var(--surface-2)"),
    ("#3a3a3d", "var(--surface-2)"),
    ("#2d2d30", "var(--surface-2)"),
    ("#2e2e31", "var(--surface-2)"),
    ("#2a2a2d", "var(--surface-2)"),
    ("#3d3d40", "var(--surface-2)"),
    ("#555558", "var(--border)"),
    ("#555555", "var(--border)"),
    ("#4a4643", "var(--border)"),
    ("#5a5a62", "var(--surface-2)"),
    ("#f0ede8", "var(--text)"),
    ("#f5f0e8", "var(--text)"),
    ("#a8a6a1", "var(--text-light)"),
    ("#b5afa5", "var(--text-light)"),
    ("#d8d4cc", "var(--text-light)"),
    ("#8a847a", "var(--text-muted)"),
    ("#999999", "var(--text-muted)"),
    ("#666666", "var(--text-muted)"),
    ("#777777", "var(--text-muted)"),
    ("#8e8c87", "var(--text-muted)"),
    ("#6b7280", "var(--text-muted)"),
    ("#374151", "var(--text-light)"),
    ("#4b5563", "var(--text-muted)"),
    ("#333333", "var(--text)"),
    ("#cccccc", "var(--border)"),
    ("#d1d5db", "var(--border)"),
    ("#ffffff", "var(--white)"),
    ("#f87171", "var(--danger)"),
    ("#c87070", "color-mix(in srgb, var(--danger) 72%, var(--surface))"),
    ("#ef4444", "var(--danger)"),
    ("#fee2e2", "color-mix(in srgb, var(--danger) 10%, var(--surface))"),
    ("#991b1b", "var(--danger-dark)"),
    ("#7f1d1d", "var(--danger-dark)"),
    ("#fca5a5", "color-mix(in srgb, var(--danger) 42%, var(--white))"),
    ("#065f46", "var(--success)"),
    ("#0f6043", "var(--success)"),
    ("#147a54", "var(--success)"),
    ("#137547", "var(--success)"),
    ("#2a6e3f", "var(--success)"),
    ("#6ee7b7", "var(--success-light)"),
    ("#7bc4a0", "var(--success-light)"),
    ("#86efac", "var(--success-light)"),
    ("#f59e0b", "var(--warning)"),
    ("#92400e", "color-mix(in srgb, var(--warning) 58%, var(--bg))"),
    ("#fde68a", "color-mix(in srgb, var(--warning) 38%, var(--white))"),
    ("#e8a060", "color-mix(in srgb, var(--warning) 72%, var(--gold))"),
    ("#0e7490", "var(--info)"),
    ("#6495ed", "var(--info)"),
    ("#1e3a5f", "color-mix(in srgb, var(--info) 42%, var(--bg))"),
    ("#93c5fd", "color-mix(in srgb, var(--info) 48%, var(--white))"),
    ("#1a52a8", "color-mix(in srgb, var(--info) 62%, var(--bg))"),
    ("#1a4b8c", "color-mix(in srgb, var(--info) 54%, var(--bg))"),
    ("#153f85", "color-mix(in srgb, var(--info) 50%, var(--bg))"),
    ("#c4b5fd", "color-mix(in srgb, var(--pos-payment-gift) 48%, var(--white))"),
    ("#000000", "black"),
    ("#f9fafb", "var(--surface-2)"),
    ("#1a1a2e", "color-mix(in srgb, var(--info) 14%, var(--bg))"),
    ("#1a2e1a", "color-mix(in srgb, var(--success) 12%, var(--bg))"),
    ("#22c55e", "var(--success-light)"),
    ("#1a1a1a", "var(--text)"),
    ("#888888", "var(--text-muted)"),
    ("#34d399", "var(--success-light)"),
    ("#60a5fa", "var(--info)"),
    ("#cc3333", "var(--danger)"),
]

# Short hex (word boundary: not followed by more hex digits)
SHORT_HEX: list[tuple[str, str]] = [
    ("#777", "var(--text-muted)"),
    ("#fff", "var(--white)"),
    ("#000", "black"),
    ("#555", "var(--border)"),
    ("#999", "var(--text-muted)"),
    ("#666", "var(--text-muted)"),
    ("#333", "var(--text)"),
    ("#ccc", "var(--border)"),
    ("#888", "var(--text-muted)"),
    ("#c33", "var(--danger)"),
]


def inject_pos_root(s: str) -> str:
    if "--pos-payment-gift:" in s:
        return s
    if "var(--pos-payment-gift)" not in s:
        return s
    block = """        :root {
            --pos-payment-gift: #7C3AED;
        }

"""
    return s.replace("<style>", "<style>\n" + block, 1)


GIFT_LITERAL = "__POS_GIFT_LITERAL__"


def apply_hex(text: str) -> str:
    # Keep one literal #7C3AED for --pos-payment-gift (avoid var() recursion on re-runs)
    text = re.sub(
        r"(?i)(--pos-payment-gift:\s*)#7c3aed(\s*;)",
        r"\1" + GIFT_LITERAL + r"\2",
        text,
        count=1,
    )
    for hex_lower, rep in HEX_REPLACEMENTS:
        pattern = re.compile(re.escape(hex_lower), re.IGNORECASE)
        text = pattern.sub(rep, text)
    text = re.sub(r"(?i)#7c3aed\b", "var(--pos-payment-gift)", text)
    text = text.replace(GIFT_LITERAL, "#7C3AED")
    for short, rep in SHORT_HEX:
        pat = re.compile(short + r"(?![0-9a-fA-F])", re.IGNORECASE)
        text = pat.sub(rep, text)
    return text


def apply_rgba(text: str) -> str:
    for old, new in RGBA_REPLACEMENTS:
        text = text.replace(old, new)
    return text


def count_colorish(text: str) -> tuple[int, int]:
    hex_n = len(re.findall(r"#[0-9a-fA-F]{3,8}\b", text))
    rgba_n = len(re.findall(r"rgba?\([^)]+\)", text))
    return hex_n, rgba_n


def main() -> None:
    paths = sys.argv[1:]
    if not paths:
        print("Usage: apply_pos_theme_colors.py <file.html> ...")
        sys.exit(1)
    for path in paths:
        raw = open(path, encoding="utf-8").read()
        before = count_colorish(raw)
        text = raw
        text = apply_rgba(text)
        text = apply_hex(text)
        text = inject_pos_root(text)
        after = count_colorish(text)
        open(path, "w", encoding="utf-8").write(text)
        print(path, "hex/rgba-ish:", before, "->", after)


if __name__ == "__main__":
    main()
