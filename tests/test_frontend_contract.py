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
        self.assertIn('id="lostReportGuidance"', self.html)
        self.assertIn('id="foundReportGuidance"', self.html)
        self.assertIn("LOST ITEM · HELP US RETRACE IT", self.html)
        self.assertIn("FOUND ITEM · HELP RETURN IT SAFELY", self.html)
        self.assertIn("last time you remember having the item", self.js)
        self.assertIn("actual discovery place", self.js)
        self.assertIn("Keep one or two unique ownership clues private", self.js)

    def test_report_reset_is_safe_when_form_is_not_mounted(self):
        self.assertIn('const form = $("#reportForm");', self.js)
        self.assertIn('if (!form || !chooser)', self.js)
        self.assertIn('form.reset();', self.js)
        self.assertIn('const form = event.currentTarget;', self.js)
        self.assertIn('if (reportFormElement) reportFormElement.addEventListener("submit", submitReport);', self.js)



    def test_every_form_has_a_submit_handler(self):
        direct = set(re.findall(
            r"""\$\(["']#([A-Za-z0-9_-]+)["']\)\.addEventListener\(["']submit["']""",
            self.js,
        ))
        self.assertIn('if (reportFormElement) reportFormElement.addEventListener("submit", submitReport);', self.js)
        direct.add("reportForm")
        missing = sorted(set(self.form_ids) - direct)
        self.assertEqual(missing, [], f"Forms without submit handlers: {missing}")

    def test_each_report_form_reset_is_preceded_by_a_null_guard(self):
        for function_name in ("setReportMode", "resetReportMode"):
            start = self.js.index(f"function {function_name}(")
            next_function = self.js.find("\nfunction ", start + 1)
            block = self.js[start:next_function if next_function >= 0 else len(self.js)]
            guard = re.search(r"if \(!form \\|\\| !chooser\) \\{[\\s\\S]*?return;\\s*\\}", block)
            self.assertIsNotNone(guard, f"{function_name} must return when the form or chooser is absent")
            reset_at = block.find("form.reset();")
            self.assertGreater(reset_at, guard.end(), f"{function_name} resets before its null guard")

    def test_report_submission_uses_the_submitted_form_and_guards_its_button(self):
        start = self.js.index("async function submitReport(event)")
        end = self.js.find("\nasync function ", start + 1)
        block = self.js[start:end if end >= 0 else len(self.js)]
        self.assertIn("const form = event.currentTarget;", block)
        self.assertRegex(block, r"if \(!form \\|\\| !errorNode\) \\{[\\s\\S]*?return;")
        self.assertRegex(block, r"if \(!submitButton\) \\{[\\s\\S]*?return;")



if __name__ == "__main__":
    unittest.main()
