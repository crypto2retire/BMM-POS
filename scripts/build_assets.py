#!/usr/bin/env python3
"""Build script to minify CSS and JS assets for production.

Run this before deploying to production:
    python scripts/build_assets.py

This creates .min.css and .min.js versions alongside the originals.
The app should be configured to serve minified versions in production.
"""
import re
import os
from pathlib import Path


def minify_css(content: str) -> str:
    """Simple CSS minification."""
    # Remove comments
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    # Remove extra whitespace
    content = re.sub(r'\s+', ' ', content)
    # Remove whitespace around specific characters
    content = re.sub(r'\s*([{}:;,])>\s*', r'\1', content)
    content = re.sub(r';\s*}', '}', content)
    return content.strip()


def minify_js(content: str) -> str:
    """Simple JS minification."""
    # Remove single-line comments (but not in strings)
    lines = []
    in_string = None
    i = 0
    while i < len(content):
        char = content[i]
        
        if in_string:
            if char == in_string and content[i-1] != '\\':
                in_string = None
            lines.append(char)
            i += 1
            continue
        
        if char in '"\'`':
            in_string = char
            lines.append(char)
            i += 1
            continue
        
        if char == '/' and i + 1 < len(content):
            if content[i + 1] == '/':
                # Skip to end of line
                while i < len(content) and content[i] != '\n':
                    i += 1
                continue
            elif content[i + 1] == '*':
                # Skip block comment
                i += 2
                while i < len(content) - 1:
                    if content[i] == '*' and content[i + 1] == '/':
                        i += 2
                        break
                    i += 1
                continue
        
        lines.append(char)
        i += 1
    
    content = ''.join(lines)
    # Remove extra whitespace
    content = re.sub(r'\n\s*\n', '\n', content)
    content = re.sub(r'[ \t]+', ' ', content)
    content = re.sub(r'\n ', '\n', content)
    content = re.sub(r' \n', '\n', content)
    return content.strip()


def process_file(src_path: Path, minifier) -> bool:
    """Minify a single file and write .min version."""
    try:
        content = src_path.read_text(encoding='utf-8')
        minified = minifier(content)
        
        # Only write if it actually reduces size
        if len(minified) >= len(content) * 0.95:
            return False
        
        dest_path = src_path.with_suffix('.min' + src_path.suffix)
        dest_path.write_text(minified, encoding='utf-8')
        
        savings = len(content) - len(minified)
        pct = (savings / len(content)) * 100
        print(f"  {src_path.name} → {dest_path.name} ({pct:.1f}% smaller, -{savings:,} bytes)")
        return True
    except Exception as e:
        print(f"  ERROR processing {src_path}: {e}")
        return False


def main():
    static_dir = Path("frontend/static")
    
    css_files = [
        "css/main.css",
        "css/landing-editorial-modern.css",
        "css/landing-editorial-warm.css",
    ]
    
    js_files = [
        "js/admin-vendor-dashboard.js",
        "js/assistant-panel.js",
        "js/assistant.js",
        "js/theme-loader.js",
        "js/api.js",
        "js/auth-bootstrap.js",
    ]
    
    print("Minifying CSS files...")
    css_count = 0
    for rel_path in css_files:
        src = static_dir / rel_path
        if src.exists():
            if process_file(src, minify_css):
                css_count += 1
        else:
            print(f"  SKIP (not found): {rel_path}")
    
    print(f"\nMinifying JS files...")
    js_count = 0
    for rel_path in js_files:
        src = static_dir / rel_path
        if src.exists():
            if process_file(src, minify_js):
                js_count += 1
        else:
            print(f"  SKIP (not found): {rel_path}")
    
    print(f"\nDone! Minified {css_count} CSS and {js_count} JS files.")
    print("Note: Update HTML files to use .min.css/.min.js in production.")


if __name__ == "__main__":
    main()
