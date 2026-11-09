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
        cls.css = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")
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
            r"""(?<!\$)\$\(["\'][^"\']+["\']\)\s*\.(?:forEach|map|filter|some|every|reduce)\s*\(""",
            self.js,
        )
        self.assertEqual(bad, [], f"Single-element selector used as a collection: {bad}")

    def test_navigation_views_have_matching_sections(self):
        expected = {
            "start": "startView",
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
        self.assertTrue({"start", "browse", "report", "notifications", "office"}.issubset(self.views))
        self.assertTrue({"my-reports", "my-claims", "activity"}.isdisjoint(self.views))
        for section in expected.values():
            self.assertIn(section, self.id_set, f"View section {section} must remain available to its authorized workflow")

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


    def test_public_navigation_is_visible_before_authentication(self):
        self.assertIn('id="publicNav"', self.html)
        self.assertIn('class="public-topbar"', self.html)
        for destination in ("home", "browse", "lost", "found", "track", "office"):
            self.assertIn(f'data-public-destination="{destination}"', self.html)
        self.assertIn('document.addEventListener("click", event => {\n  const button = event.target.closest("[data-public-destination]");', self.js)
        self.assertIn("function setPublicNavActive(destination)", self.js)
        self.assertIn('nav.querySelectorAll("[data-public-destination]").forEach', self.js)
        self.assertNotIn('$("#publicNav [data-public-destination]").forEach', self.js)

    def test_public_browse_cards_do_not_expand_full_descriptions(self):
        start = self.js.index("async function loadPublicFound()")
        end = self.js.index("\nfunction openPublicOfficeSignIn()", start)
        browse_renderer = self.js[start:end]
        self.assertIn('escapeHTML(item.title)', browse_renderer)
        self.assertIn('escapeHTML(item.location_area || item.location_block || "Campus location")', browse_renderer)
        self.assertNotIn("escapeHTML(item.description)", browse_renderer)

    def test_public_search_loader_is_async(self):
        self.assertIn("async function loadPublicFound()", self.js)

    def test_public_navigation_is_centered_and_glass_styled(self):
        styles = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr)", styles)
        self.assertIn(".public-topbar .public-nav { justify-self: center; }", styles)
        self.assertIn("backdrop-filter: blur(18px)", styles)

    def test_obsolete_student_to_office_switch_is_not_rendered(self):
        # Public student accounts were intentionally removed. Office staff sign in
        # through the dedicated staff entry point, so this legacy control is invalid.
        self.assertNotIn('id="viewSwitchBtn"', self.html)
        self.assertNotIn('Switch to office', self.html)

    def test_public_and_office_action_delegates_are_present(self):
        # These controls are wired through delegated data attributes rather than
        # individual ID listeners; keep their dispatcher contracts explicit.
        for selector in (
            '[data-public-report]',
            '[data-public-home]',
            '[data-report-kind]',
            '[data-go]',
            '[data-view]',
            '[data-view-details]',
            '[data-matches]',
            '[data-add-evidence]',
            '[data-decision]',
            '[data-handover]',
            '[data-storage-update]',
            '[data-notification-read]',
            '[data-certificate-download]',
        ):
            self.assertIn(selector, self.js, f"Missing delegated action handler: {selector}")

    def test_public_navigation_selector_uses_a_collection(self):
        self.assertIn('nav.querySelectorAll("[data-public-destination]").forEach', self.js)
        self.assertNotIn('$("#publicNav [data-public-destination]").forEach', self.js)

    def test_liquid_glass_interactions_respect_reduced_motion(self):
        styles = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".nimbus-item::before", styles)
        self.assertIn(".nimbus-item:hover::before", styles)
        self.assertIn("@media (prefers-reduced-motion: reduce)", styles)


    def test_lost_and_found_report_forms_are_independent_and_contextual(self):
        self.assertIn("lostReportForm", self.form_ids)
        self.assertIn("foundReportForm", self.form_ids)
        self.assertIn('id="lostReportGuidance"', self.html)
        self.assertIn('id="foundReportGuidanceFound"', self.html)
        self.assertIn("FOUND ITEM · HELP RETURN IT SAFELY", self.html)
        self.assertIn("Where exactly did you find it?", self.html)
        self.assertIn("function activeReportForm()", self.js)
        self.assertIn("function reportField(id, form = activeReportForm())", self.js)
        self.assertIn('document.querySelectorAll("#lostReportForm, #foundReportForm").forEach((form) => {', self.js)
        self.assertIn("Suggest found-item category with AI", self.js)
        self.assertIn("actual discovery place", self.js)

    def test_each_report_form_has_scoped_submission_and_ai_controls(self):
        self.assertIn('form.addEventListener("submit", submitReport);', self.js)
        self.assertIn("const form = event.currentTarget;", self.js)
        self.assertIn('form.querySelector(\'button[type="submit"]\')', self.js)
        self.assertIn('const form = useCategory.closest("form");', self.js)
        self.assertIn('reportField("reportCategory", form).value', self.js)

    def test_public_lost_and_found_have_separate_report_pages_and_forms(self):
        self.assertIn('id="publicLostPage"', self.html)
        self.assertIn('id="publicFoundPage"', self.html)
        self.assertIn('id="publicReportForm"', self.html)
        self.assertIn('id="publicFoundReportForm"', self.html)
        self.assertIn('id="publicReportTypeFound" type="hidden" value="found"', self.html)
        self.assertIn("FOUND ITEM · HELP RETURN IT SAFELY", self.html)
        self.assertIn("Do not publish names, student IDs, serial numbers", self.html)
        self.assertIn('type === "found" ? "publicFoundPage" : "publicLostPage"', self.js)
        self.assertIn('document.querySelectorAll("#publicReportForm, #publicFoundReportForm").forEach((form) => {', self.js)
        self.assertIn('const field = (id) => publicReportField(form, id);', self.js)

    def test_public_found_navigation_shows_only_its_own_page(self):
        self.assertIn('["publicLostPage","publicFoundPage","publicBrowsePage","publicTrackPage"]', self.js)
        self.assertIn('type === "found" ? "publicFoundPage" : "publicLostPage"', self.js)
        self.assertIn('reportPage.querySelector("#publicDescriptionFound")', self.js)
        self.assertIn('form.id === "publicFoundReportForm"', self.js)

    def test_report_layout_matches_reference_with_bone_beige_theme(self):
        self.assertIn('class="form-card form-stack liquid-glass-panel hidden report-entry-form"', self.html)
        self.assertIn('class="form-card form-stack liquid-glass-panel hidden found-report-form report-entry-form"', self.html)
        self.assertIn('class="button button-quiet button-small ai-suggest-button"', self.html)
        self.assertIn('aria-live="polite"', self.html)
        self.assertIn("#reportView .form-layout", self.css)
        self.assertIn("#reportView .side-guidance", self.css)
        self.assertIn("#reportView .ai-assist-inline", self.css)
        self.assertIn("grid-template-columns: minmax(0,1fr)", self.css)

    def test_public_report_forms_expose_the_rate_limited_ai_category_helper(self):
        self.assertIn('data-public-ai-category', self.html)
        self.assertIn('id="publicCategorySuggestion"', self.html)
        self.assertIn('id="publicCategorySuggestionFound"', self.html)
        self.assertIn('async function requestPublicCategorySuggestion(button)', self.js)
        self.assertIn('/api/public/category-suggestion', self.js)
        self.assertIn('document.addEventListener("click", event => {', self.js)


    def test_student_navigation_has_four_destinations_and_no_office_panel(self):
        nav = re.search(r'<nav id="studentNav".*?</nav>', self.html, re.S)
        self.assertIsNotNone(nav)
        markup = nav.group(0)
        self.assertIn('data-view="start"', markup)
        self.assertIn('data-view="browse"', markup)
        self.assertIn('data-view="report"', markup)
        self.assertIn('>Reports</span>', markup)
        self.assertIn('data-view="notifications"', markup)
        self.assertNotIn('data-view="my-reports"', markup)
        self.assertNotIn('data-view="my-claims"', markup)
        self.assertNotIn('Office workspace', self.html)
        self.assertNotIn('officeWorkspaceButton', self.js)

    def test_report_navigation_opens_lost_found_picker(self):
        self.assertIn('report: "#reportView"', self.js)
        self.assertIn('id="reportTypeChooser"', self.html)
        self.assertIn('data-report-kind="lost"', self.html)
        self.assertIn('data-report-kind="found"', self.html)

    def test_reference_header_has_responsive_phone_layout(self):
        self.assertIn('class="brand-lockup compact"', self.html)
        self.assertIn('class="header-center"', self.html)
        self.assertIn('class="header-right"', self.html)
        self.assertIn("@media (max-width:680px)", self.css)
        self.assertIn("scroll-snap-type:x proximity", self.css)
        self.assertIn("overscroll-behavior-x:contain", self.css)

    def test_ai_category_controls_are_present_in_both_authenticated_report_forms(self):
        self.assertIn('id="suggestCategoryButton"', self.html)
        self.assertIn('id="suggestCategoryButtonFound"', self.html)
        self.assertIn('class="category-ai-control ai-assist-inline"', self.html)
        self.assertIn('ai-suggest-button', self.html)
        self.assertIn("#reportView .ai-suggest-button", self.css)
        self.assertIn("async function suggestReportCategory(event)", self.js)


    def test_public_ai_assistant_follows_the_description_it_uses(self):
        for description_id, status_id in [
            ("publicDescription", "publicCategorySuggestion"),
            ("publicDescriptionFound", "publicCategorySuggestionFound"),
        ]:
            description_pos = self.html.index(f'id="{description_id}"')
            status_pos = self.html.index(f'id="{status_id}"')
            self.assertGreater(status_pos, description_pos)
        self.assertIn('class="public-ai-panel"', self.html)
        self.assertIn(".public-ai-panel", self.css)

    def test_global_theme_uses_consistent_bone_beige_palette(self):
        self.assertIn("--ll-paper: #f2e9dc", self.css)
        self.assertIn("--ll-primary: #96552f", self.css)
        self.assertIn("--canvas-bg: var(--ll-paper)", self.css)
        self.assertIn("--water-blue: var(--ll-primary)", self.css)
        self.assertNotIn("#dcebf5", self.css.lower())
        self.assertNotIn("#0284c7", self.css.lower())
        self.assertNotIn("#2563eb", self.css.lower())
        self.assertNotIn("#00a2ff", self.css.lower())
        self.assertNotIn("rgba(37,99,235", self.css.lower())
        self.assertIn(".report-kind-guidance", self.css)
        self.assertIn(".button-primary", self.css)

    def test_navigation_destinations_are_oval_on_desktop_and_mobile(self):
        self.assertIn('#appView #studentNav .nimbus-item { border-radius:999px !important; }', self.css)
        self.assertIn('#appView #studentNav .nimbus-item { flex:1 0 auto;', self.css)

    def test_public_student_workflow_has_no_student_sign_in(self):
        self.assertNotIn('id="publicStudentButton"', self.html)
        self.assertNotIn('function openPublicStudentSignIn()', self.js)
        self.assertNotIn('loginMode', self.js)
        self.assertIn('function openPublicOfficeSignIn()', self.js)
        self.assertIn('role !== "office"', self.js)

    def test_start_report_cards_open_the_selected_form_and_secondary_views_remain_reachable(self):
        self.assertIn('if (reportKind) { navigate("report"); setReportMode(reportKind.dataset.reportKind); }', self.js)
        self.assertIn('data-go="my-reports"', self.html)
        self.assertIn('data-go="my-claims"', self.html)
        self.assertIn('data-go="activity"', self.html)

    def test_public_navigation_does_not_cover_scrolled_form_controls(self):
        public_topbar = re.search(r"\.public-topbar\s*\{([^}]*)\}", self.css)
        self.assertIsNotNone(public_topbar)
        self.assertRegex(public_topbar.group(1), r"position:\s*relative")
        self.assertNotRegex(public_topbar.group(1), r"position:\s*sticky")

    def test_tablet_browse_date_filters_stay_inside_their_grid_track(self):
        self.assertIn("@media (min-width: 601px) and (max-width: 960px)", self.css)
        self.assertIn(".search-secondary-row > .date-filter", self.css)
        self.assertIn("grid-column: 1 / -1;", self.css)
        self.assertIn(".date-filter input[type=\"date\"]", self.css)
        self.assertIn("min-width: 0;", self.css)

    def test_public_forms_use_cvr_location_hierarchy_and_approved_details(self):
        for element_id in (
            "publicBlock", "publicFloor", "publicRoom", "publicArea",
            "publicPrivateDetail", "publicBlockFound", "publicFloorFound",
            "publicRoomFound", "publicAreaFound", "publicItemConditionFound",
            "publicHandoverAtFound", "publicHandoverRecipientFound", "publicHandoverNoteFound",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('field("publicFloor").value', self.js)
        self.assertIn('field("publicRoom").value.trim()', self.js)
        self.assertIn('field("publicPrivateDetail").value.trim()', self.js)
        self.assertIn('field("publicItemCondition").value', self.js)
        self.assertIn('field("publicHandoverAt").value', self.js)
        self.assertNotIn('pending verification', self.js.lower())
        self.assertIn('locations.aliases', self.js)
        self.assertIn(".public-handover-fields", self.css)

    def test_all_claim_entry_points_use_the_no_login_public_claim_flow(self):
        self.assertIn('openPublicClaimById(button.dataset.publicClaim, button.dataset.publicRef)', self.js)
        self.assertIn('openPublicClaimById(button.dataset.claim', self.js)
        self.assertIn('if (report) openPublicClaimDialog(report)', self.js)
        self.assertIn('publicMatchClaimButton(item)', self.js)
        self.assertIn('publicMatchClaimButton(report)', self.js)
        self.assertIn('publicApi("/api/public/found/"', self.js)
        self.assertIn("publicClaimEvidenceType", self.js)

    def test_public_tracking_uses_private_receipt_link_without_manual_secret_field(self):
        self.assertIn('id="publicTrackLink"', self.html)
        self.assertNotIn('id="publicTrackSecret"', self.html)
        self.assertNotIn('id="publicTrackReference"', self.html)
        self.assertNotIn('id="publicTrackRoll"', self.html)
        self.assertIn('id="copyPublicTrackingLink"', self.html)
        self.assertIn("function buildPublicTrackingUrl(reference, roll, secret)", self.js)
        self.assertIn("function parsePublicTrackingUrl(value)", self.js)
        self.assertIn("function getPublicAccess(reference, roll, suppliedSecret)", self.js)
        self.assertIn("sessionStorage.setItem", self.js)
        self.assertIn("sessionStorage.getItem", self.js)
        self.assertIn("X-LostLink-Tracking-Secret", self.js)
        self.assertIn("url.hash", self.js)
        self.assertIn("params.has(\"track\")", self.js)
        self.assertIn('$("#copyPublicTrackingLink").addEventListener("click"', self.js)
        self.assertIn('$("#publicTrackForm").addEventListener("submit"', self.js)
        self.assertIn('$("#publicTrackResult").addEventListener("click"', self.js)
        self.assertIn('$("#publicEvidenceForm").addEventListener("submit"', self.js)
        self.assertIn('$("#publicClaimForm").addEventListener("submit"', self.js)
        self.assertIn("data-public-refresh-matches", self.js)
        self.assertIn("data-public-close-case", self.js)
        self.assertIn("data-public-add-evidence", self.js)
        self.assertIn("storePublicAccess(result.claim.reference, roll, result.tracking_secret)", self.js)
        self.assertIn("storePublicAccess(result.case.reference, body.roll_number, result.tracking_secret)", self.js)
        self.assertNotIn("publicTrackSecret", self.js)
        self.assertNotIn("tracking_secret=", self.js.lower())

    def test_campus_dropdowns_do_not_show_pending_verification_badges(self):
        self.assertNotIn("pending verification", self.js.lower())

    def test_office_claim_review_displays_linked_lost_report_owner_clues(self):
        start = self.js.index("function officeClaimCard(claim)")
        end = self.js.index("\nasync function submitIntake", start)
        renderer = self.js[start:end]
        self.assertIn("linked_lost_report.private_verification_detail", renderer)
        self.assertIn("OWNER-ONLY DETAILS · LOST REPORT", renderer)
        self.assertIn("escapeHTML(claim.linked_lost_report.private_verification_detail)", renderer)

    def test_office_intake_displays_found_item_condition_and_handover_context(self):
        start = self.js.index("function intakeCard(report)")
        end = self.js.index("\nfunction officeClaimCard", start)
        renderer = self.js[start:end]
        for field in ("item_condition", "handover_at", "handover_recipient", "handover_note"):
            self.assertIn(field, renderer)
        self.assertIn("handoverContext", renderer)
        self.assertIn("escapeHTML(value)", renderer)

if __name__ == "__main__":
    unittest.main()
