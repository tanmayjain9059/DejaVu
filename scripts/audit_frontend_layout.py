#!/usr/bin/env python3
"""Responsive browser audit for the public LostLink entry and reporting flows."""
from __future__ import annotations

import os
import struct
import sys
from datetime import datetime
from urllib.parse import parse_qs, urlparse
import zlib
from playwright.sync_api import sync_playwright

BASE_URL = os.getenv("LOSTLINK_AUDIT_URL", "http://127.0.0.1:8000").rstrip("/")

AUDIT = r"""
() => {
  const width = document.documentElement.clientWidth;
  const scrollWidth = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
  const overflow = scrollWidth > width + 1 ? {
    width, scrollWidth,
    offenders: [...document.querySelectorAll('body *')].map(el => ({el, rect:el.getBoundingClientRect(), style:getComputedStyle(el)}))
      .filter(x => x.style.display !== 'none' && x.style.visibility !== 'hidden' && x.rect.width > 1 && x.rect.right > width + 1)
      .slice(0, 12).map(x => ({tag:x.el.tagName,id:x.el.id,cls:typeof x.el.className === 'string' ? x.el.className.slice(0,90) : '',x:x.rect.x,right:x.rect.right,width:x.rect.width,scrollWidth:x.el.scrollWidth}))
  } : null;
  const selector = 'button, a[href], input:not([type="hidden"]), select, textarea';
  const modal = document.querySelector('#officeLoginPanel:not(.hidden)');
  const nodes = [...document.querySelectorAll(selector)].filter((el) => {
    if (modal && !modal.contains(el)) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' &&
      Number(style.opacity) > 0 && rect.width > 1 && rect.height > 1 &&
      el.getClientRects().length > 0;
  });
  const boxes = nodes.map((el) => ({ el, rect: el.getBoundingClientRect() }));
  const overlaps = [];
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j];
      if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
      const w = Math.max(0, Math.min(a.rect.right, b.rect.right) - Math.max(a.rect.left, b.rect.left));
      const h = Math.max(0, Math.min(a.rect.bottom, b.rect.bottom) - Math.max(a.rect.top, b.rect.top));
      const area = w * h;
      const minArea = Math.min(a.rect.width * a.rect.height, b.rect.width * b.rect.height);
      if (area > 4 && area / Math.max(1, minArea) > 0.08) {
        overlaps.push({
          first: a.el.id || a.el.getAttribute('aria-label') || a.el.textContent.trim().slice(0, 45) || a.el.tagName,
          second: b.el.id || b.el.getAttribute('aria-label') || b.el.textContent.trim().slice(0, 45) || b.el.tagName,
          overlapRatio: Number((area / Math.max(1, minArea)).toFixed(2)),
          firstRect: {x:a.rect.x,y:a.rect.y,width:a.rect.width,height:a.rect.height},
          secondRect: {x:b.rect.x,y:b.rect.y,width:b.rect.width,height:b.rect.height}
        });
      }
    }
  }
  return { overflow, overlaps };
}
"""

def audit(page, label: str) -> None:
    result = page.evaluate(AUDIT)
    if result["overflow"] or result["overlaps"]:
        raise AssertionError(f"{label}: layout issues: {result}")

def return_home(page) -> None:
    back = page.locator("[data-public-home]:visible").first
    if back.is_visible():
        back.click()
        page.locator("#publicHomeContent").wait_for(state="visible")

def exercise_public_category_ai(page, page_id: str, suffix: str = "") -> None:
    page.locator("#" + page_id + " #publicTitle" + suffix).fill("Blue campus backpack")
    page.locator("#" + page_id + " #publicDescription" + suffix).fill(
        "A blue backpack with two front pockets and a zip closure."
    )
    page.locator("#" + page_id + " [data-public-ai-category]").click()
    page.locator("#" + page_id + " .ai-alternative-button").first.wait_for(state="visible", timeout=10000)
    page.locator("#" + page_id + " .ai-alternative-button").first.click()
    selected = page.locator("#" + page_id + " #publicCategory" + suffix).input_value()
    if selected != "bags_wallets":
        raise AssertionError(f"{page_id}: AI category selection mismatch: {selected!r}")

def tiny_png_bytes() -> bytes:
    """Build a small valid PNG without adding a test-only image dependency."""
    width = height = 32
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            shade = 190 if (x // 4 + y // 4) % 2 else 72
            row.extend((shade, 116, 48, 255))
        rows.append(bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def submit_public_report(page, kind: str) -> None:
    """Exercise Lost/Found submission and browser-managed private tracking."""
    found = kind == "found"
    suffix = "Found" if found else ""
    page_id = "publicFoundPage" if found else "publicLostPage"
    form_id = "publicFoundReportForm" if found else "publicReportForm"
    page.locator(f"#publicNav [data-public-destination='{kind}']").click()
    page.locator("#" + page_id).wait_for(state="visible")
    form = page.locator("#" + form_id)
    form.locator("#publicRollNumber" + suffix).fill("25B81A66J8")
    form.locator("#publicTitle" + suffix).fill(
        "Silver bottle I found" if found else "Black backpack I lost"
    )
    form.locator("#publicCategory" + suffix).select_option("bags_wallets")
    form.locator("#publicDescription" + suffix).fill(
        "A clearly described campus item with visible colour, material and condition details for the report."
    )
    form.locator("#publicBlock" + suffix).select_option("Library" if found else "Computer Block")
    form.locator("#publicFloor" + suffix).select_option("Ground Floor" if found else "First Floor")
    form.locator("#publicRoom" + suffix).fill("Reading Hall" if found else "CSE Lab")
    form.locator("#publicArea" + suffix).fill(
        "Outside the library entrance" if found else "Library reading room"
    )
    if found:
        form.locator("#publicItemCondition" + suffix).select_option("good")
        form.locator("#publicHandoverAt" + suffix).fill(datetime.now().strftime("%Y-%m-%dT%H:%M"))
        form.locator("#publicHandoverRecipient" + suffix).fill("Campus office desk")
        form.locator("#publicHandoverNote" + suffix).fill("Submitted at the office counter.")
    else:
        form.locator("#publicPrivateDetail").fill("Owner-only mark beneath the battery cover.")
    if not found:
        with page.expect_file_chooser() as chooser_info:
            form.locator('label:has(#publicImage)').click()
        chooser_info.value.set_files({
            "name": "lostlink-audit.png",
            "mimeType": "image/png",
            "buffer": tiny_png_bytes(),
        })
    previous_tracking_url = page.locator("#publicTrackLink").input_value()
    previous_secret = parse_qs(urlparse(previous_tracking_url).fragment).get("secret", [""])[0]
    form.locator('button[type="submit"]').click()
    page.locator("#publicTrackPage").wait_for(state="visible", timeout=15000)
    reference = page.locator("#publicTrackReference").input_value()
    if not reference.startswith("LL-"):
        raise AssertionError(f"{kind} report did not return a case reference")
    tracking_url = page.locator("#publicTrackLink").input_value()
    tracking_secret = parse_qs(urlparse(tracking_url).fragment).get("secret", [""])[0]
    if len(tracking_secret) < 20 or tracking_secret == previous_secret:
        raise AssertionError("The submitting user did not receive a fresh private tracking link with a case secret")
    if not found and "Your photo was saved privately for office review." not in page.locator("#publicTrackResult").inner_text():
        raise AssertionError("Lost report photo picker/upload did not complete successfully")
    if form.locator("#publicTitle" + suffix).input_value():
        raise AssertionError(f"{kind} report form did not reset after successful submission")
    page.locator("#publicTrackForm button[type=submit]").click()
    page.get_by_text("Status:", exact=False).wait_for(state="visible", timeout=10000)
    if "tracking secret" in page.locator("#publicTrackResult").inner_text().lower():
        raise AssertionError("Tracking result exposed credential wording")
    return_home(page)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for width, height in [(320, 740), (375, 812), (768, 1024), (1440, 900)]:
                page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
                page_errors = []
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.goto(BASE_URL, wait_until="networkidle")
                page.locator("#publicHomeContent").wait_for(state="visible")
                audit(page, f"landing {width}x{height}")

                page.locator("#publicNav [data-public-destination='browse']").click()
                page.locator("#publicBrowsePage").wait_for(state="visible")
                assert page.locator("#publicNav [aria-current='page']").get_attribute("data-public-destination") == "browse"
                audit(page, f"public nav browse {width}x{height}")
                return_home(page)

                page.locator("#publicNav [data-public-destination='lost']").click()
                page.locator("#publicLostPage").wait_for(state="visible")
                assert page.locator("#publicReportType").input_value() == "lost"
                exercise_public_category_ai(page, "publicLostPage")
                audit(page, f"public nav lost {width}x{height}")
                return_home(page)

                page.locator("#publicNav [data-public-destination='found']").click()
                page.locator("#publicFoundPage").wait_for(state="visible")
                assert page.locator("#publicReportTypeFound").input_value() == "found"
                exercise_public_category_ai(page, "publicFoundPage", "Found")
                audit(page, f"public nav found {width}x{height}")
                return_home(page)

                page.locator("#publicNav [data-public-destination='track']").click()
                page.locator("#publicTrackPage").wait_for(state="visible")
                audit(page, f"public nav track {width}x{height}")
                return_home(page)

                page.locator('[data-public-report="lost"]').click()
                page.locator("#publicLostPage").wait_for(state="visible")
                audit(page, f"lost report {width}x{height}")
                return_home(page)
                audit(page, f"landing after lost {width}x{height}")

                page.locator('[data-public-report="found"]').click()
                page.locator("#publicFoundPage").wait_for(state="visible")
                assert page.locator("#publicReportTypeFound").input_value() == "found"
                audit(page, f"found report {width}x{height}")
                return_home(page)

                page.locator("#publicBrowseButton").click()
                page.locator("#publicBrowsePage").wait_for(state="visible")
                audit(page, f"public browse {width}x{height}")
                return_home(page)

                page.locator("#publicTrackButton").click()
                page.locator("#publicTrackPage").wait_for(state="visible")
                audit(page, f"public tracking {width}x{height}")
                return_home(page)

                if width == 1440:
                    submit_public_report(page, "lost")
                    submit_public_report(page, "found")

                if (width == 1440):
                    # A newly submitted Lost report must be discoverable immediately.
                    page.locator("#publicNav [data-public-destination='browse']").click()
                    page.locator("#publicBrowsePage").wait_for(state="visible")
                    page.locator("#publicBrowseResults").get_by_text("Black backpack I lost", exact=True).wait_for(timeout=10000)
                    page.locator("#publicBrowseQuery").fill("Black backpack I lost")
                    page.locator("#publicBrowseForm").locator('button[type="submit"]').click()
                    page.locator("#publicBrowseResults").get_by_text("Black backpack I lost", exact=True).wait_for(timeout=10000)
                    page.locator("#publicBrowseQuery").fill("lostlink-no-such-campus-item-92841")
                    page.locator("#publicBrowseForm").locator('button[type="submit"]').click()
                    page.get_by_text("No public reports match that search yet.", exact=True).wait_for(timeout=10000)
                    # A Found report is intentionally hidden until office staff records physical intake.
                    page.locator("#publicBrowseQuery").fill("Silver bottle I found")
                    page.locator("#publicBrowseForm").locator('button[type="submit"]').click()
                    page.get_by_text("No public reports match that search yet.", exact=True).wait_for(timeout=10000)
                    return_home(page)


                page.locator("#publicNav [data-public-destination='office']").click()
                page.locator("#officeLoginPanel").wait_for(state="visible")
                assert page.locator("#publicNav [aria-current='page']").get_attribute("data-public-destination") == "office"
                audit(page, f"office sign-in {width}x{height}")
                page.locator("#loginEmail").fill("layout-audit@lostlink.test")
                page.locator("#loginPassword").fill("layout-audit-password")
                page.locator("#loginForm").evaluate("(form) => form.requestSubmit()")
                page.wait_for_timeout(500)
                if not page.locator("#appView").is_visible():
                    raise AssertionError("Office browser-audit login failed: " + page.locator("#loginError").inner_text())
                page.locator("#appView").wait_for(state="visible")
                page.locator("#officeView").wait_for(state="visible")
                assert page.locator("#officeWorkspaceButton").count() == 0
                assert page.locator("#studentNav [data-view='office']:visible").count() == 1
                audit(page, f"office dashboard {width}x{height}")
                for view, view_id in [("notifications", "notificationsView"), ("browse", "browseView")]:
                    page.locator(f'button[data-view="{view}"]:visible').first.click()
                    page.locator("#" + view_id).wait_for(state="visible")
                    audit(page, f"office {view} {width}x{height}")
                if page_errors:
                    raise AssertionError(f"Uncaught browser JavaScript errors at {width}px: {page_errors}")
                page.close()
            print("Responsive browser and Lost/Found submit audit passed at 320, 375, 768 and 1440 CSS pixels.")
            return 0
        finally:
            browser.close()

if __name__ == "__main__":
    sys.exit(main())
