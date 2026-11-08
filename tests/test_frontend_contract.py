"""Static frontend contract tests for selectors, views and listener targets."""
from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "app" / "static" / "index.html"
JS_PATH = ROOT / "app" / "static" / "app.js"


class MarkupInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.view_names: list[str] = []
        self.form_ids: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"])
        if values.get("data-view"):
            self.view_names.append(values["data-view"])
        if tag == "form" and values.get("id"):
            self.form_ids.append(values["id"])


class FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML_PATH.read_text(encoding="utf-8")
        cls.js = JS_PATH.read_text(encoding="utf-8")
        parser = MarkupInventory()
        parser.feed(cls.html)
        cls.ids = parser.ids
        cls.id_set = set(parser.ids)
        cls.views = set(parser.view_names)
        cls.form_ids = parser.form_ids

    def test_html_ids_are_unique(self):
        duplicates = sorted({item for item in self.ids if self.ids.count(item) > 1})
        self.assertEqual(duplicates, [], f"Duplicate HTML IDs: {duplicates}")

    def test_direct_javascript_id_selectors_exist(self):
        referenced = set(re.findall(r"""\$\(["']#([A-Za-z0-9_-]+)["']\)""", self.js))
        missing = sorted(referenced - self.id_set)
        self.assertEqual(missing, [], f"Selectors reference missing IDs: {missing}")

    def test_event_listener_targets_exist(self):
        targets = set(re.findall(r"""\$\(["']#([A-Za-z0-9_-]+)["']\)\.addEventListener""", self.js))
        missing = sorted(targets - self.id_set)
        self.assertEqual(missing, [], f"Event listeners target missing IDs: {missing}")

    def test_collection_methods_use_multi_element_selector(self):
        # $() is querySelector; $$() is querySelectorAll. Calling .forEach/.map
        # on a single Element aborts startup or a feature action at runtime.
        bad = re.findall(
            r"""(?<!\$)\$\([^;\n]*?\)\.(?:forEach|map|filter|some|every|reduce)\s*\(""",
            self.js,
        )
        self.assertEqual(bad, [], f"Single-element selector used as a collection: {bad}")

    def test_navigation_views_have_matching_sections(self):
        expected = {
            "browse": "browseView",
            "report": "reportView",
            "my-reports": "myReportsView",
            "my-claims": "myClaimsView",
            "notifications": "notificationsView",
            "activity": "activityView",
            "office": "officeView",
        }
        missing = [view for view in self.views if expected.get(view) not in self.id_set]
        self.assertEqual(missing, [], f"Navigation views missing their section: {missing}")
        self.assertTrue(set(expected).issubset(self.views))

    def test_mobile_viewport_and_touch_navigation_contract(self):
        self.assertIn("viewport-fit=cover", self.html)
        styles = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 700px)", styles)
        self.assertRegex(styles, r"\.tab-button\s*\{[^}]*min-height:\s*44px")
        self.assertRegex(styles, r"input,\s*select,\s*textarea\s*\{[^}]*font-size:\s*16px")

    def test_pagination_controls_are_connected_to_keyset_loaders(self):
        controls = {
            "browseLoadMore": "loadBrowse(true)",
            "myReportsLoadMore": "loadMyReports(true)",
            "myClaimsLoadMore": "loadMyClaims(true)",
            "intakeLoadMore": 'loadOffice("intake")',
            "inventoryLoadMore": 'loadOffice("inventory")',
            "officeClaimsLoadMore": 'loadOffice("officeClaims")',
            "handoverLoadMore": 'loadOffice("handovers")',
        }
        for control_id, action in controls.items():
            self.assertIn(control_id, self.id_set, f"Missing pagination control: {control_id}")
            self.assertIn(action, self.js, f"Pagination control is not wired: {control_id}")
        self.assertIn("function pageUrl(path, cursor)", self.js)
        self.assertIn("next_cursor", self.js)
        self.assertIn("has_more", self.js)

    def test_live_notification_polling_is_enabled(self):
        self.assertIn("startNotificationPolling();", self.js)
        self.assertIn("}, 10000);", self.js)
        self.assertIn("stopNotificationPolling();", self.js)


    def test_lost_and_found_reports_have_distinct_student_guidance(self):
        lost_start = self.html.index('<form id="lostReportForm"')
        lost_end = self.html.index("</form>", lost_start)
        found_start = self.html.index('<form id="foundReportForm"')
        found_end = self.html.index("</form>", found_start)
        lost_form = self.html[lost_start:lost_end]
        found_form = self.html[found_start:found_end]
        self.assertIn('id="lostReportGuidance"', lost_form)
        self.assertNotIn('id="foundReportGuidance"', lost_form)
        self.assertIn('id="foundReportGuidanceFound"', found_form)
        self.assertNotIn('id="lostReportGuidanceFound"', found_form)
        self.assertIn("LOST ITEM · HELP US RETRACE IT", lost_form)
        self.assertIn("FOUND ITEM · HELP RETURN IT SAFELY", found_form)
        self.assertIn("Where did you last have it?", self.js)
        self.assertIn("actual discovery place", self.js)
        self.assertIn("Keep one or two unique ownership clues private", self.js)
        self.assertIn("Submit found report", found_form)
        self.assertNotIn("Submit lost report", found_form)
        self.assertIn("What does the item look like?", found_form)
        self.assertIn("Where exactly did you find it?", found_form)
        self.assertIn("Suggest found-item category with AI", self.js)
        self.assertIn("Help us return this item safely.", self.js)

    def test_report_reset_is_safe_when_forms_are_not_mounted(self):
        self.assertIn("function activeReportForm()", self.js)
        self.assertIn('document.querySelectorAll("#lostReportForm, #foundReportForm")', self.js)
        self.assertIn("function resetReportMode()", self.js)
        self.assertIn('if (chooser) chooser.classList.remove("hidden");', self.js)
        self.assertIn("const form = event.currentTarget;", self.js)
        self.assertIn('form.addEventListener("submit", submitReport);', self.js)

    def test_every_form_has_a_submit_handler(self):
        self.assertIn("lostReportForm", self.form_ids)
        self.assertIn("foundReportForm", self.form_ids)
        self.assertIn(
            'document.querySelectorAll("#lostReportForm, #foundReportForm").forEach((form) => {',
            self.js,
        )
        self.assertIn('form.addEventListener("submit", submitReport);', self.js)
        self.assertIn('$("#loginForm").addEventListener("submit"', self.js)

    def test_each_report_form_reset_is_scoped_and_guarded(self):
        start = self.js.index("function setReportMode(")
        end = self.js.index("\nfunction resetReportMode()", start)
        block = self.js[start:end]
        guard = block.index("if (!form || !chooser)")
        reset_at = block.index("previousForm.reset();")
        self.assertGreater(reset_at, guard, "setReportMode must guard the active form before clearing the prior draft")
        reset_start = self.js.index("function resetReportMode()")
        reset_end = self.js.index("\nfunction evidenceTypeLabel", reset_start)
        reset_block = self.js[reset_start:reset_end]
        self.assertIn('document.querySelectorAll("#lostReportForm, #foundReportForm").forEach((form) => {', reset_block)
        self.assertIn("form.reset();", reset_block)
        self.assertIn('if (chooser) chooser.classList.remove("hidden");', reset_block)

    def test_report_submission_uses_the_submitted_form_and_guards_its_button(self):
        start = self.js.index("async function submitReport(event)")
        end = self.js.find("\nasync function ", start + 1)
        block = self.js[start:end if end >= 0 else len(self.js)]
        self.assertIn("const form = event.currentTarget;", block)
        self.assertRegex(block, r"if \(!form \|\| !errorNode\) \{[\s\S]*?return;")
        self.assertRegex(block, r"if \(!submitButton\) \{[\s\S]*?return;")


if __name__ == "__main__":
    unittest.main()
