#!/usr/bin/env python3
"""Responsive browser audit for the public LostLink entry and reporting flows."""
from __future__ import annotations

import os
import sys
from playwright.sync_api import sync_playwright

BASE_URL = os.getenv("LOSTLINK_AUDIT_URL", "http://127.0.0.1:8000").rstrip("/")

AUDIT = r"""
() => {
  const width = document.documentElement.clientWidth;
  const scrollWidth = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
  const overflow = scrollWidth > width + 1 ? { width, scrollWidth } : null;
  const selector = 'button, a[href], input:not([type="hidden"]), select, textarea';
  const nodes = [...document.querySelectorAll(selector)].filter((el) => {
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
    back = page.locator("[data-public-home]").first
    if back.is_visible():
        back.click()
        page.locator("#publicHomeContent").wait_for(state="visible")

def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for width, height in [(320, 740), (375, 812), (768, 1024), (1440, 900)]:
                page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
                page.goto(BASE_URL, wait_until="networkidle")
                page.locator("#publicHomeContent").wait_for(state="visible")
                audit(page, f"landing {width}x{height}")

                page.locator('[data-public-report="lost"]').click()
                page.locator("#publicLostPage").wait_for(state="visible")
                audit(page, f"lost report {width}x{height}")
                return_home(page)
                audit(page, f"landing after lost {width}x{height}")

                page.locator('[data-public-report="found"]').click()
                page.locator("#publicLostPage").wait_for(state="visible")
                assert page.locator("#publicReportType").input_value() == "found"
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

                page.locator("#publicOfficeButton").click()
                page.locator("#officeLoginPanel").wait_for(state="visible")
                audit(page, f"office sign-in {width}x{height}")
                page.locator("#loginEmail").fill("layout-audit@lostlink.test")
                page.locator("#loginPassword").fill("layout-audit-password")
                page.locator("#loginForm button[type=submit]").click()
                page.locator("#appView").wait_for(state="visible")
                page.locator("#officeView").wait_for(state="visible")
                audit(page, f"office dashboard {width}x{height}")
                for view, view_id in [("notifications", "notificationsView"), ("browse", "browseView"), ("start", "startView"), ("office", "officeView")]:
                    page.locator(f'button[data-view="{view}"]:visible').first.click()
                    page.locator("#" + view_id).wait_for(state="visible")
                    audit(page, f"office {view} {width}x{height}")
                page.close()
            print("Responsive browser layout audit passed at 320, 375, 768 and 1440 CSS pixels.")
            return 0
        finally:
            browser.close()

if __name__ == "__main__":
    sys.exit(main())
