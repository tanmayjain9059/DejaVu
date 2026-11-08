# DejaVu / LostLink — UI Design Specification (`UI-SPEC.md`)

**Product:** DejaVu / LostLink Campus Lost-and-Found System  
**Design Paradigm:** Apple Fluid Interfaces (WWDC) + UI/UX Pro Max Design Intelligence  
**Target Platform:** Modern Web (Desktop & Mobile, Progressive Web Standards)  
**Specification Version:** 1.0.0 (GSD UI-Phase)  

---

## 1. Vision & Core Philosophy

DejaVu / LostLink is a secure, campus-grade custody and return system. Unlike public classifieds, it safeguards student privacy, enforces physical chain of custody through campus staff, and leverages AI solely for discovery candidate ranking.

The user interface embodies **Apple's Fluid Interface principles**:
1. **Response — Zero Perceived Latency:** Feedback begins on pointer-down (`scale(0.97)` instant compression, active surface shift), not on click release.
2. **Physicality & Depth:** Multi-layered translucent materials (`backdrop-filter: blur(20px) saturate(180%)`), subtle specular rims (`1px solid rgba(255, 255, 255, 0.7)`), and delicate directional illumination simulating natural ambient light.
3. **Interruptibility & Motion:** Transitions driven by critically damped spring physics (`damping: 1.0` default settle, snappier `0.8` for momentum gestures). All sheets and dialogs are interruptible and dismissable with natural gestures.
4. **Restraint & Editorial Craft:** High-contrast, humanist geometric typography (Google Fonts **Plus Jakarta Sans**), strictly no AI-slop neon glows or monospace cyber gimmicks, and pure vector SVG iconography (Lucide design style).

---

## 2. Design Tokens & Styling Architecture

### 2.1 Color System
All colors adhere to WCAG AAA contrast ratios against light backgrounds:

```css
:root {
  /* Canvas & Base Materials */
  --canvas-bg: #f5f7fb;
  --surface-glass: rgba(255, 255, 255, 0.78);
  --surface-glass-heavy: rgba(255, 255, 255, 0.92);
  --surface-glass-subtle: rgba(255, 255, 255, 0.55);
  --surface-card: #ffffff;
  --surface-sunken: #eef2f8;

  /* Specular Highlight & Borders */
  --glass-border: rgba(255, 255, 255, 0.8);
  --glass-border-subtle: rgba(226, 232, 240, 0.7);
  --glass-border-dark: rgba(203, 213, 225, 0.9);

  /* Typography / Inks (Contrast > 10:1) */
  --text-primary: #0f172a;       /* Slate 900 */
  --text-secondary: #334155;     /* Slate 700 */
  --text-muted: #64748b;         /* Slate 500 */
  --text-subtle: #94a3b8;        /* Slate 400 */

  /* Apple Royal Cobalt Brand Accent */
  --brand-primary: #2563eb;      /* Blue 600 */
  --brand-hover: #1d4ed8;        /* Blue 700 */
  --brand-subtle: #eff6ff;       /* Blue 50 */
  --brand-gradient: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
  --brand-focus-ring: 0 0 0 3px rgba(37, 99, 235, 0.25);

  /* Semantic Status Tokens (Pastel chips with high-contrast text) */
  --status-available-bg: #ecfdf5;
  --status-available-fg: #065f46;
  --status-available-bd: #a7f3d0;

  --status-pending-bg: #fffbeb;
  --status-pending-fg: #92400e;
  --status-pending-bd: #fde68a;

  --status-verified-bg: #eff6ff;
  --status-verified-fg: #1e40af;
  --status-verified-bd: #bfdbfe;

  --status-rejected-bg: #fef2f2;
  --status-rejected-fg: #991b1b;
  --status-rejected-bd: #fecaca;

  /* Shadows & Depth */
  --shadow-sm: 0 2px 6px rgba(15, 23, 42, 0.04), 0 1px 2px rgba(15, 23, 42, 0.02);
  --shadow-md: 0 8px 24px rgba(15, 23, 42, 0.06), 0 2px 6px rgba(15, 23, 42, 0.03);
  --shadow-lg: 0 20px 48px rgba(15, 23, 42, 0.09), 0 4px 12px rgba(15, 23, 42, 0.04);
  --shadow-modal: 0 25px 60px -12px rgba(15, 23, 42, 0.18), 0 0 0 1px rgba(255, 255, 255, 0.8) inset;

  /* Corner Radii */
  --radius-xs: 6px;
  --radius-sm: 10px;
  --radius-md: 14px;
  --radius-lg: 20px;
  --radius-xl: 28px;
  --radius-pill: 9999px;

  /* Physics Transitions */
  --spring-snappy: cubic-bezier(0.2, 0.9, 0.3, 1);
  --spring-bounce: cubic-bezier(0.34, 1.56, 0.64, 1);
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
}
```

### 2.2 Typography
- **Primary Typeface:** `Plus Jakarta Sans`, `-apple-system`, `BlinkMacSystemFont`, `sans-serif`
- **Headings (H1, H2, H3):**
  - Font Weight: 700 / 800
  - Tracking: `-0.035em` to `-0.045em`
  - Line Height: 1.15 to 1.2
- **Body & Captions:**
  - Font Weight: 400 (Regular), 500 (Medium), 600 (SemiBold)
  - Line Height: 1.55 to 1.6
  - Size Scale: 11px (Micro / Badges), 13px (Muted meta), 14px (Secondary), 15px (Body), 17px (Subheading), 20px (Card Title), 26px (Section Title), 36px–48px (Hero Display).

---

## 3. Component Architecture & Interactions

### 3.1 Segmented Fluid Navigation Bar
- A floating frosted-glass capsule positioned with balanced top/bottom margin.
- Sunken track background (`rgba(226, 232, 240, 0.65)` with fine inner border).
- Active item uses an Apple-style convex ceramic pill that smoothly glides into place.
- Each item contains an inline SVG icon (`stroke-width: 2`) + label + optional count badge pill.
- Min touch target: 44px height per item.

### 3.2 Apple-Grade Cards
- High-vibrancy background (`rgba(255, 255, 255, 0.88)`), blur `18px`.
- Crisp top/left specular rim (`1px solid rgba(255, 255, 255, 0.85)`).
- Instant active compression: `:active { transform: scale(0.98); }`.
- Hover lift: `transform: translateY(-2px); box-shadow: var(--shadow-md);`.

### 3.3 Tactile Form Inputs & Buttons
- **Inputs & Selects:**
  - Minimum 44px height, 14px horizontal padding.
  - Recessed look (`background: #ffffff`, subtle border `rgba(203, 213, 225, 0.8)`).
  - Focus state: `border-color: var(--brand-primary); box-shadow: var(--brand-focus-ring);`.
- **Buttons:**
  - Primary: Cobalt gradient with soft specular reflection and subtle drop shadow.
  - Secondary/Quiet: High-clarity frosted glass with dark slate text and fine border.
  - Active: `:active { transform: scale(0.96); }`.

### 3.4 Modal Dialogs & Bottom Sheets
- Native `<dialog>` element styled with Apple spring entry (`opacity: 0; transform: scale(0.95)` to `opacity: 1; transform: scale(1)`).
- Desktop: Centered floating card with blur backdrop (`backdrop-filter: blur(16px)`).
- Mobile (≤640px): Smooth bottom sheet anchored to the lower viewport with drag handle.

---

## 4. Screen-by-Screen Redesign Specifications

### Screen 1: Login & Campus Onboarding (`#loginView`)
- Two-column hero split:
  - **Left Story Pillar:** Brand lockup `LL` with cobalt gradient, inspirational headline, and 3 translucent card tiles ("01 Report clearly", "02 Find likely matches", "03 Verify before release").
  - **Right Access Card:** Frosted ceramic container, email & password inputs, quick 1-click Demo Account pills (Alex Chen - Student, Campus Office Staff, etc.), Supabase sign-up toggle, and clear security assurance note.

### Screen 2: Student Browse Hub (`#browseView`)
- Clean search & filter bar with instant query feedback, category dropdown, building & room selector, and date filters.
- Item Grid: Rich cards featuring item photograph (with fallback SVG illustration), public reference badge (`LL-F-1024`), status pill (`Available at office`), category indicator, location details, timestamp, and "Submit claim" action.
- Keyset pagination / "Load more" button with spinner.

### Screen 3: Guided Reporting Flow (`#reportView`)
- Dynamic report-type selector cards ("I lost something" vs "I found something").
- 4-step progressive disclosure:
  - Step 01: Item title, Category with AI category suggestion trigger + reassurance copy, Description with character counter.
  - Step 02: Additional details (Brand, Main color, Visible features, Approximate date/time).
  - Step 03: Location (Block, Floor, Room, Nearby landmark).
  - Step 04: Photo dropzone with drag-over highlight, instant image preview thumbnail, clear action, and privacy advisory.

### Screen 4: My Reports & AI Match Exploration (`#myReportsView`)
- Active lost & found cards submitted by the student.
- Allowed lifecycle actions: "Find possible matches", "Close search", "Withdraw report".
- **Match Drawer / Sheet:** Compares candidate found items side-by-side with match strength chip (`strong match`, `possible match`) and transparent signal explanations.

### Screen 5: My Claims & Evidence Management (`#myClaimsView`)
- Status cards with visual timeline (`pending` → `approved_for_collection` → `returned`).
- Secure evidence management: View submitted evidence, attach private evidence photograph, respond to office evidence requests, or submit an appeal request if rejected.

### Screen 6: Notifications Hub (`#notificationsView`)
- Apple-style notification feed with unread indicators, entity deep links, and "Mark all read" button.

### Screen 7: Activity, Certificates & Leaderboard (`#activityView`)
- Cobalt verified contribution points card with metallic emblem accent.
- Animated progress bar toward next achievement tier.
- Downloadable milestone certificates (PDF export integration).
- Campus community leaderboard with 1st, 2nd, 3rd podium badges and personal highlight.
- Verified points ledger table.

### Screen 8: Campus Office Console (`#officeView`)
- 6 sculpted metric cards: `Awaiting intake`, `Items available`, `Active claims`, `Disputed claims`, `Ready for handover`, `Items returned`.
- Sub-views:
  - **Intake Queue:** Incoming found items awaiting physical custody.
  - **Storage Inventory:** Physical item register with storage location update sheet.
  - **Claim Review Workbench:** Claimant identity, private evidence, verification checklist (`distinctive_features`, `physical_inspection`, `claimant_identity`), and decision buttons (`Approve`, `Reject`, `Request Evidence`, `Mark Disputed`).
  - **Handover Counter:** Physical Tag ID verification scanner, policy confirmation checkboxes, and release authorization.
  - **AI Diagnostics:** Health status of MiniLM, CLIP, and BLIP services.

---

## 5. Accessibility & Performance Verification (WCAG AAA)
- All interactive elements meet 44×44px minimum touch size.
- Visible `:focus-visible` ring on keyboard navigation (`box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.4)`).
- Complete `@media (prefers-reduced-motion: reduce)` rules disabling non-essential motion.
- Semantic HTML tags (`<nav>`, `<main>`, `<dialog>`, `<section>`, `<article>`) and descriptive `aria-label`, `aria-expanded`, and `role="status"` attributes.
