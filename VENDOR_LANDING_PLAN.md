# Vendor Landing Page Improvement Plan
## Bowenstreet Market — Premium Boutique Experience

### Current State Analysis
The vendor landing page system already has a solid foundation:
- **6 templates**: classic, modern, boutique, minimal, editorial-warm, editorial-modern
- **Theme system**: Colors, fonts, accent colors, branding (logo)
- **7 hero variants**: classic, split, editorial, collage, story, carousel, portrait
- **Section system**: Hero, about, specialties, story blocks, gallery, items, FAQ, social feeds, related vendors
- **E-commerce**: Cart, checkout, tax calculation
- **SEO**: Schema.org, OG tags, meta descriptions, canonical URLs
- **AI assistant**: LLM-powered design recommendations

### Goals
1. **Premium boutique aesthetic** — Make pages feel like high-end retail (Anthropologie, CB2, local boutique)
2. **Brand personalization** — Give vendors more control over their visual identity
3. **Better product showcase** — Items should be the star, not an afterthought
4. **Mobile-first** — Most shoppers browse on phones
5. **Faster loading** — Image optimization, lazy loading, code splitting

---

## Phase 1: Visual Foundation (Core Improvements)

### 1.1 Typography System Overhaul
**Problem**: Current typography is functional but generic. No type hierarchy.
**Solution**:
- Add 3-4 curated font pairings (serif + sans-serif combinations)
- Implement proper type scale: display (hero), heading (H1-H4), body, caption, label
- Add letter-spacing controls for headings
- Add line-height options (tight, normal, relaxed)
- Support for accent/display fonts (script, decorative) for brand names

**New vendor controls**:
- Font pairing selector (dropdown with preview)
- Heading weight slider (300-700)
- Body text size (14px-18px)
- Letter spacing for headings (-0.02em to 0.1em)

### 1.2 Color System Enhancement
**Problem**: Basic 5-color palette. No nuance.
**Solution**:
- Expand to 8-color system: primary, secondary, accent, background, surface, text, text-muted, border
- Add opacity variants automatically (hover states, overlays, borders)
- Support for gradients (subtle background gradients)
- Dark/light mode toggle per vendor
- Color contrast checker (accessibility)

**New vendor controls**:
- Color picker with preset palettes (12 curated palettes)
- "Palette from logo" — extract colors from uploaded logo
- Gradient toggle (subtle, none, strong)
- Dark/light mode selector

### 1.3 Spacing & Layout Grid
**Problem**: Sections feel cramped. No breathing room.
**Solution**:
- Implement 8px grid system
- Section padding options: compact (2rem), comfortable (4rem), spacious (6rem)
- Max-width options: narrow (800px), medium (1000px), wide (1200px), full
- Add vertical rhythm (consistent spacing between elements)
- Container padding options for mobile

**New vendor controls**:
- Section spacing slider
- Content width selector
- Border radius toggle (0px for sharp, 8px for soft, 16px for round)

---

## Phase 2: Hero Section Improvements

### 2.1 Hero Height & Impact
**Problem**: Hero is too short (420px). Doesn't feel premium.
**Solution**:
- Increase default hero height to 70vh (minimum 500px)
- Add parallax scroll effect (subtle, 0.3 speed)
- Support for video backgrounds (muted, looping)
- Full-bleed hero option (edge-to-edge)

### 2.2 Hero Content Positioning
**Problem**: Content always at bottom. No flexibility.
**Solution**:
- Content alignment: left, center, right
- Content vertical position: top, center, bottom
- Text shadow controls (none, subtle, strong)
- Background overlay opacity slider (0.3-0.8)

### 2.3 Hero Variants Refinement
**Current**: 7 variants but some feel similar
**New variants**:
- **Fullscreen**: Full viewport height, minimal text, dramatic
- **Split**: 50/50 image and text side by side
- **Editorial**: Magazine-style with byline, issue number, ornaments
- **Carousel**: Full-width image carousel with auto-play
- **Video**: Background video with overlay
- **Minimal**: Clean, lots of whitespace, elegant typography

---

## Phase 3: Product Grid & Item Cards

### 3.1 Grid Layout Options
**Problem**: Only auto-fill grid. No masonry or list view.
**Solution**:
- Masonry layout (Pinterest-style) for visual products
- List view (for detailed browsing)
- Featured item spotlight (first item is large, rest are grid)
- Grid density: compact (3-4 per row), comfortable (2-3), spacious (1-2)

### 3.2 Item Card Design
**Problem**: Cards are basic. No hover states, no visual interest.
**Solution**:
- **Image**: Aspect ratio options (1:1, 3:4, 4:3, 16:9)
- **Hover effect**: Image zoom (1.05 scale), shadow lift, quick-view button
- **Badge system**: Sale badge, new arrival, limited quantity, handmade
- **Price styling**: Original price with strikethrough, sale price highlighted
- **Quick actions**: "Add to cart" button on hover (desktop), always visible (mobile)
- **Variant swatches**: Color/size dots if item has variants

### 3.3 Product Detail Lightbox
**Problem**: No way to see larger images or details without going to checkout.
**Solution**:
- Click item card → opens lightbox modal
- Large image carousel
- Full description
- Variant selector (if applicable)
- "Add to cart" directly from lightbox
- Close button and backdrop click to dismiss

---

## Phase 4: Section Improvements

### 4.1 About Section
**Problem**: Plain text block. Boring.
**Solution**:
- Support for rich text (bold, italic, links)
- Two-column layout: text + image
- Quote/callout styling
- Vendor portrait photo (circular or rounded)
- "Established year" badge
- Social links as icon buttons (not just text)

### 4.2 Photo Gallery
**Problem**: Horizontal scroll only. Limited.
**Solution**:
- Grid gallery (2-4 columns)
- Masonry gallery
- Lightbox on click (full-screen image viewer)
- Caption support
- "View all photos" button if more than 6

### 4.3 Story Blocks
**Problem**: Basic text sections.
**Solution**:
- Timeline layout (for origin story)
- Image + text alternating layout
- Process steps (numbered, with icons)
- Values/beliefs (icon grid)

### 4.4 Specialties
**Problem**: Just text chips.
**Solution**:
- Icon + text chips (if we can map specialties to icons)
- Category cards (with background colors)
- Tag cloud sizing (more items = larger text)

### 4.5 Related Vendors
**Problem**: Basic grid at bottom.
**Solution**:
- Horizontal scroll carousel
- "You might also like" with curated connections
- Show vendor thumbnail, name, booth number, specialty count

---

## Phase 5: Personalization Features

### 5.1 Brand Logo
**Current**: Small logo in nav bar
**Improvement**:
- Hero logo placement (centered above name)
- Logo size options
- Logo background shape (none, circle, square, rounded)

### 5.2 Custom CSS (Advanced)
**For power users**:
- Custom CSS textarea in editor
- Live preview with safety checks
- Common snippets (hide elements, change colors, add borders)

### 5.3 Background Patterns/Textures
**Options**:
- Subtle patterns (dots, lines, geometric)
- Texture overlays (paper, fabric, wood)
- Gradient backgrounds (linear, radial)
- Full-width background images (fixed or scrolling)

### 5.4 Animation Preferences
**Controls**:
- Entrance animations (fade up, fade in, slide in)
- Animation speed (slow, normal, fast)
- Hover transitions (subtle, medium, pronounced)
- Disable animations (accessibility)

---

## Phase 6: Mobile Experience

### 6.1 Mobile Navigation
**Problem**: Nav is desktop-first.
**Solution**:
- Hamburger menu with vendor sections
- Sticky bottom bar (home, items, about, cart)
- Swipe gestures for gallery

### 6.2 Mobile Product Grid
**Problem**: Too many columns on small screens.
**Solution**:
- 2-column grid default on mobile
- 1-column option for large product images
- Full-width cards
- Touch-friendly add-to-cart buttons

### 6.3 Mobile Hero
**Problem**: Hero text too small on mobile.
**Solution**:
- Larger font sizes on mobile hero
- Stacked layout (image top, text bottom)
- Portrait image crop for mobile

---

## Phase 7: Performance & Polish

### 7.1 Image Optimization
**Current**: Images loaded at full size.
**Improvement**:
- Automatic WebP conversion
- Responsive images (srcset)
- Lazy loading (intersection observer)
- Image placeholders (blur-up or color)
- CDN integration (if available)

### 7.2 Loading States
**Problem**: No loading indicators.
**Solution**:
- Skeleton screens for items
- Shimmer effect for images
- Progress indicators for cart/checkout

### 7.3 Smooth Scrolling
**Problem**: Jerky scrolling.
**Solution**:
- Smooth scroll for anchor links
- Scroll-triggered animations (fade in as user scrolls)
- Back-to-top button

### 7.4 Micro-interactions
**Additions**:
- Button hover states (scale, color change)
- Cart add animation (item flies to cart icon)
- Toast notifications (item added, error messages)
- Heart/favorite button (if we add wishlist later)

---

## Phase 8: Vendor Editing Experience

### 8.1 Live Preview
**Current**: Preview exists but could be better.
**Improvement**:
- Split-screen editor (left: controls, right: preview)
- Device toggle (desktop, tablet, mobile)
- Instant preview (no save required)
- Highlight edited section

### 8.2 Template Gallery
**New feature**:
- Grid of 12+ templates with screenshots
- Filter by style (minimal, bold, editorial, modern)
- "Use this template" button
- Template presets (all settings applied at once)

### 8.3 Content Wizard
**New feature**:
- Step-by-step setup: brand → colors → items → about → publish
- Progress indicator
- Required vs optional fields
- Tips and examples

### 8.4 Photo Upload Enhancement
**Current**: Basic upload.
**Improvement**:
- Drag-and-drop upload
- Multiple file select
- Auto-crop to square/rectangle options
- Reorder photos (drag and drop)
- AI photo quality check (blur detection, brightness)

---

## Implementation Priority

### Week 1: Foundation
1. Typography system (font pairings, type scale)
2. Color system expansion (8 colors, presets, gradient)
3. Spacing controls (section padding, content width)
4. Border radius options

### Week 2: Hero & Product Cards
1. Hero height increase + parallax
2. Hero content positioning controls
3. Item card redesign (hover effects, badges, aspect ratio)
4. Product lightbox modal

### Week 3: Sections & Gallery
1. About section rich text + two-column
2. Photo gallery grid + lightbox
3. Story block layouts
4. Specialty styling improvements

### Week 4: Mobile & Performance
1. Mobile navigation (hamburger + bottom bar)
2. Mobile grid optimization
3. Image lazy loading + WebP
4. Loading skeletons

### Week 5: Polish & Editor
1. Micro-interactions (cart animation, toasts)
2. Smooth scrolling
3. Template gallery
4. Live preview improvements

---

## Success Metrics
- **Engagement**: Time on page, pages per session
- **Conversion**: Cart additions, checkout completions
- **Vendor adoption**: % of vendors customizing their pages
- **Performance**: Page load time < 2s, Lighthouse score > 80
- **Mobile**: > 60% of traffic should be mobile

## Notes
- All changes must be backward-compatible (existing pages don't break)
- Changes should be opt-in (vendors can keep current look)
- Accessibility: WCAG 2.1 AA compliance for color contrast, keyboard navigation
- Performance: No layout shift, images properly sized