"""End-to-end regression tests for the no-login public student workflow."""
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from io import BytesIO

from PIL import Image
from pathlib import Path

from fastapi.testclient import TestClient

from app.core import config as app_config
from app.core import database as app_database

TEST_WITH_POSTGRES = os.getenv("TEST_WITH_POSTGRES", "").lower() == "true"
if not TEST_WITH_POSTGRES:
    app_config.DATABASE_URL = ""
    app_database.DATABASE_URL = ""
import app.main as main
from app.api.routes import public_workflow as public_routes
from app.services import object_storage, reports as report_service


class PublicWorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        if TEST_WITH_POSTGRES:
            app_database.close_database_pool()
            with app_database.connect_db() as conn:
                conn.execute("DROP SCHEMA public CASCADE")
                conn.execute("CREATE SCHEMA public")
        modules = (main, app_config, app_database, public_routes, object_storage)
        for module in modules:
            for name, value in {
                "DATA_DIR": root,
                "DB_PATH": root / "public-workflow.sqlite",
                "UPLOAD_DIR": root / "uploads",
                "DATABASE_URL": app_config.DATABASE_URL if TEST_WITH_POSTGRES else "",
                "DEMO_MODE": False,
            }.items():
                if hasattr(module, name):
                    setattr(module, name, value)
        main.app.dependency_overrides.clear()
        main.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        main.initialise_db()
        public_routes.ensure_public_schema()
        with main.connect_db() as conn:
            conn.execute(
                "INSERT INTO users(email,display_name,role,password_hash,created_at) VALUES (?,?,?,?,?)",
                ("office@test.invalid","Campus Office","office",main.hash_password("office-password"),main.now_iso()),
            )
            conn.execute(
                "INSERT INTO users(email,display_name,role,password_hash,created_at) VALUES (?,?,?,?,?)",
                ("student@test.invalid","Legacy Student","student",main.hash_password("student-password"),main.now_iso()),
            )
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.clear()
        self.client.close()
        self.temp.cleanup()

    def office_login(self):
        response = self.client.post("/api/login",json={
            "email":"office@test.invalid","password":"office-password"
        })
        self.assertEqual(response.status_code,200,response.text)

    def create_public_report(self, report_type="lost", roll="25B81A66J8", title="Black calculator"):
        return self.client.post("/api/public/reports",json={
            "report_type":report_type,
            "roll_number":roll,
            "title":title,
            "description":"Black scientific calculator with a cracked protective cover.",
            "category":"electronics",
            "brand":"Casio",
            "primary_color":"Black",
            "visible_features":"Small blue sticker below the display.",
            "location_block":"Block A",
            "location_area":"Library",
        })

    def intake(self, reference, roll="25B81A66J8"):
        return self.client.post("/api/reports/"+reference+"/intake",json={
            "confirmed_physical_receipt":True,
            "identity_verified_in_person":True,
            "verified_roll_number":roll,
            "storage_location":"Lost & Found room / Cabinet A / Shelf 2",
            "private_detail":"Blue sticker below the battery cover.",
            "value_band":"low",
            "sensitivity_level":1,
        })

    def test_public_config_uses_cvr_campus_inventory_and_keeps_floors_optional(self):
        response = self.client.get("/api/config")
        self.assertEqual(response.status_code, 200, response.text)
        locations = response.json()["locations"]
        self.assertIn("Main Block", locations["blocks"])
        self.assertIn("Computer Block", locations["blocks"])
        self.assertIn("CM Block", locations["blocks"])
        self.assertIn("Central Ground", locations["blocks"])
        self.assertIn("CVR Canteen", locations["blocks"])
        self.assertIn("CSE Building", locations["aliases"]["Computer Block"])
        self.assertIn("Freshers Block", locations["aliases"]["First Year Block"])
        self.assertIn("pending_verification", locations)
        self.assertIn("Buildings", locations["groups"])
        self.assertIn("Outdoor areas & sports", locations["groups"])
        self.assertIn("Campus facilities", locations["groups"])
        self.assertNotIn("Security Room", locations["blocks"])
        self.assertIn("Other / Not listed", locations["blocks"])

    def test_public_report_context_fields_persist_and_private_details_stay_private(self):
        lost_response = self.client.post("/api/public/reports", json={
            "report_type": "lost",
            "roll_number": "25B81A66J8",
            "title": "Lost black calculator",
            "description": "Black scientific calculator with a cracked protective cover.",
            "category": "electronics",
            "location_block": "Computer Block",
            "location_floor": "First Floor",
            "location_room": "CSE Lab",
            "location_area": "Near the lab entrance",
            "private_detail": "A tiny scratch under the battery cover known only to me.",
            "contact_phone": "+91 98765 43210",
            "contact_email": "lost.student@cvr.ac.in",
        })
        self.assertEqual(lost_response.status_code, 201, lost_response.text)
        lost_ref = lost_response.json()["case"]["reference"]
        with main.connect_db() as conn:
            lost_row = conn.execute("SELECT * FROM reports WHERE public_ref=?", (lost_ref,)).fetchone()
        public_lost = report_service.serialise_report(lost_row, internal=False)
        internal_lost = report_service.serialise_report(lost_row, internal=True)
        self.assertIsNone(public_lost["location_floor"])
        self.assertIsNone(public_lost["location_block"])
        self.assertIsNone(public_lost["location_area"])
        self.assertIsNone(public_lost["occurred_at"])
        self.assertEqual(public_lost["location"], "CVR campus")
        self.assertEqual(internal_lost["location_floor"], "First Floor")
        self.assertEqual(internal_lost["location_block"], "Computer Block")
        self.assertIsNone(public_lost["location_room"])
        self.assertNotIn("private_verification_detail", public_lost)
        self.assertEqual(internal_lost["private_verification_detail"], "A tiny scratch under the battery cover known only to me.")
        self.assertEqual(internal_lost["location_room"], "CSE Lab")
        self.assertEqual(internal_lost["contact_phone"], "+91 98765 43210")
        self.assertEqual(internal_lost["contact_email"], "lost.student@cvr.ac.in")
        self.assertNotIn("contact_phone", public_lost)
        self.assertNotIn("contact_email", public_lost)

        found_response = self.client.post("/api/public/reports", json={
            "report_type": "found",
            "roll_number": "25B81A66J8",
            "title": "Found silver bottle",
            "description": "Silver bottle with a black lid and visible dent.",
            "category": "accessories",
            "location_block": "Library",
            "location_floor": "Ground Floor",
            "location_room": "Reading Hall",
            "item_condition": "partially_damaged",
            "handover_at": "2026-11-09T14:30",
            "handover_recipient": "Campus office desk",
            "handover_note": "Left with the staff member at the office counter.",
            "contact_phone": "9876543210",
            "contact_email": "finder@cvr.ac.in",
        })
        self.assertEqual(found_response.status_code, 201, found_response.text)
        found_ref = found_response.json()["case"]["reference"]
        with main.connect_db() as conn:
            found_row = conn.execute("SELECT * FROM reports WHERE public_ref=?", (found_ref,)).fetchone()
        public_found = report_service.serialise_report(found_row, internal=False)
        internal_found = report_service.serialise_report(found_row, internal=True)
        self.assertEqual(public_found["item_condition"], "partially_damaged")
        self.assertNotIn("handover_note", public_found)
        self.assertEqual(internal_found["handover_recipient"], "Campus office desk")
        self.assertEqual(internal_found["handover_note"], "Left with the staff member at the office counter.")
        self.assertEqual(internal_found["contact_phone"], "9876543210")
        self.assertEqual(internal_found["contact_email"], "finder@cvr.ac.in")
        self.assertNotIn("contact_phone", public_found)
        self.assertNotIn("contact_email", public_found)
        self.assertEqual(found_row["status"], "awaiting_intake")

    def test_public_search_redacts_lost_block_floor_room_and_time(self):
        created = self.client.post("/api/public/reports", json={
            "report_type": "lost", "roll_number": "25B81A66J8",
            "title": "Lost black calculator",
            "description": "A black calculator with a distinctive blue sticker.",
            "category": "electronics", "location_block": "Computer Block",
            "location_floor": "Third Floor", "location_room": "Lab 309",
            "location_area": "Near the lab", "occurred_at": "2026-11-09T14:30",
        })
        self.assertEqual(created.status_code, 201, created.text)
        response = self.client.get("/api/public/search?report_type=lost")
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["reports"][0]
        self.assertEqual(item["location"], "CVR campus")
        for key in ("location_block", "location_floor", "location_area", "occurred_at"):
            self.assertIsNone(item[key], key)
        self.assertNotIn("location_room", item)
        with main.connect_db() as conn:
            row = conn.execute("SELECT * FROM reports WHERE public_ref=?",
                               (created.json()["case"]["reference"],)).fetchone()
        internal = report_service.serialise_report(row, internal=True)
        self.assertEqual(internal["location_block"], "Computer Block")
        self.assertEqual(internal["location_floor"], "Third Floor")
        self.assertEqual(internal["location_room"], "Lab 309")

    def test_public_report_rejects_invalid_contact_details(self):
        payload = {
            "report_type": "lost",
            "roll_number": "25B81A66J8",
            "title": "Lost black calculator",
            "description": "Black scientific calculator with a cracked protective cover.",
            "category": "electronics",
            "location_block": "Computer Block",
            "contact_phone": "123",
            "contact_email": "not-an-email",
        }
        response = self.client.post("/api/public/reports", json=payload)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("phone number", response.json()["detail"].lower())

    def test_unlisted_campus_location_requires_a_free_text_detail(self):
        response = self.client.post("/api/public/reports", json={
            "report_type": "lost",
            "roll_number": "25B81A66J8",
            "title": "Lost black calculator",
            "description": "Black scientific calculator with a cracked protective cover.",
            "category": "electronics",
            "location_block": "Other / Not listed",
        })
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("location detail", response.json()["detail"].lower())

    def test_public_category_suggestion_is_rate_limited_and_advisory(self):
        payload = {
            "title": "Navy backpack",
            "description": "A dark blue backpack with two front pockets and a zipper.",
            "brand": None, "primary_color": "Navy", "visible_features": "Two front pockets",
        }
        response = self.client.post("/api/public/category-suggestion", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        suggestion = response.json()["suggestion"]
        self.assertEqual(suggestion["status"], "suggested")
        self.assertEqual(suggestion["category"], "bags_wallets")
        self.assertTrue(suggestion["requires_confirmation"])
        self.assertEqual(suggestion["engine"], "keyword_fallback")

    def test_readiness_reports_database_backend_and_canonical_schema(self):
        response = self.client.get("/health/ready")
        self.assertEqual(response.status_code,200,response.text)
        payload = response.json()
        self.assertEqual(payload["status"],"ready")
        self.assertEqual(payload["database"],"postgresql" if TEST_WITH_POSTGRES else "sqlite")
        self.assertEqual(payload["canonical_tables"],"ready")
        self.assertIn(payload["storage"],{"local","s3"})
        self.assertGreaterEqual(payload["schema_version"],12)

    def test_student_login_is_rejected_and_public_reports_need_no_account(self):
        signed_in = self.client.post("/api/login",json={
            "email":"student@test.invalid","password":"student-password"
        })
        self.assertEqual(signed_in.status_code,401,signed_in.text)
        profile = self.client.get("/api/me")
        self.assertEqual(profile.status_code,401,profile.text)
        created = self.create_public_report()
        self.assertEqual(created.status_code,201,created.text)
        payload = created.json()
        self.assertTrue(payload["tracking_secret"])
        with main.connect_db() as conn:
            row = conn.execute("SELECT * FROM reports WHERE public_ref=?",(payload["case"]["reference"],)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["submission_channel"],"public")
            self.assertEqual(row["roll_number"],"25B81A66J8")
            self.assertFalse(main.table_columns(conn,"public_cases"))

    def test_public_report_photo_requires_case_secret_and_is_stored_privately(self):
        created = self.create_public_report("lost", title="Photo test wallet").json()
        reference = created["case"]["reference"]
        image = BytesIO()
        Image.new("RGB", (64, 64), (120, 80, 40)).save(image, format="PNG")
        upload = image.getvalue()
        denied = self.client.post(
            "/api/public/reports/" + reference + "/image",
            headers={"X-LostLink-Roll-Number": "25B81A66J8", "X-LostLink-Tracking-Secret": "wrong-secret"},
            files={"file": ("wallet.png", b"not-an-image", "image/png")},
        )
        self.assertEqual(denied.status_code, 404)
        accepted = self.client.post(
            "/api/public/reports/" + reference + "/image",
            headers={"X-LostLink-Roll-Number": "25B81A66J8", "X-LostLink-Tracking-Secret": created["tracking_secret"]},
            files={"file": ("wallet.png", upload, "image/png")},
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        with main.connect_db() as conn:
            row = conn.execute("SELECT image_path,image_sha256,image_phash FROM reports WHERE public_ref=?", (reference,)).fetchone()
        self.assertTrue(row["image_path"])
        self.assertTrue(row["image_sha256"])
        self.assertTrue(row["image_phash"])
        self.assertTrue(object_storage.read_upload(row["image_path"]))

    def test_simultaneous_report_images_leave_only_current_object(self):
        created = self.create_public_report("lost", title="Two photo uploads").json()
        reference = created["case"]["reference"]
        with main.connect_db() as conn:
            row = conn.execute(
                "SELECT id,created_by FROM reports WHERE public_ref=?", (reference,)
            ).fetchone()
            case_id, actor_id = row["id"], int(row["created_by"])
        original_save = public_routes.save_upload
        both_saved = Barrier(2)

        def save_together(key, content):
            original_save(key, content)
            both_saved.wait(timeout=10)

        def upload(color):
            image = BytesIO()
            Image.new("RGB", (64, 64), color).save(image, format="PNG")
            public_routes._persist_public_report_image(
                reference, case_id, actor_id, image.getvalue()
            )

        with patch.object(public_routes, "save_upload", side_effect=save_together):
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs = [pool.submit(upload, color) for color in (
                    (120, 80, 40), (40, 120, 80)
                )]
                for job in jobs:
                    job.result(timeout=25)

        with main.connect_db() as conn:
            row = conn.execute(
                "SELECT image_path FROM reports WHERE id=?", (case_id,)
            ).fetchone()
        stored = list(main.UPLOAD_DIR.glob("*.jpg"))
        self.assertEqual(len(stored), 1, stored)
        self.assertEqual(stored[0].name, row["image_path"])
        self.assertTrue(object_storage.read_upload(row["image_path"]))

    def test_public_search_returns_open_lost_and_available_found_without_private_fields(self):
        lost = self.create_public_report("lost",title="Blue calculator")
        found = self.create_public_report("found",title="Black calculator")
        self.office_login()
        report_id = found.json()["case"]["id"]
        self.assertEqual(self.intake(report_id).status_code,200)
        self.client.cookies.clear()
        response = self.client.get("/api/public/search")
        self.assertEqual(response.status_code,200,response.text)
        reports = response.json()["reports"]
        self.assertEqual({row["report_type"] for row in reports},{"lost","found"})
        for row in reports:
            self.assertNotIn("roll_number",row)
            self.assertNotIn("tag_id",row)
            self.assertNotIn("storage_location",row)
            for private_field in ("private_verification_detail","location_room","created_by","roll_number","tag_id","submission_channel","tracking_hash"):
                self.assertNotIn(private_field,row)
        self.assertEqual(self.client.get("/api/public/search?report_type=lost").json()["reports"][0]["report_type"],"lost")
        self.assertEqual(self.client.get("/api/public/search?report_type=found").json()["reports"][0]["report_type"],"found")
        by_reference = self.client.get("/api/public/search?q="+lost.json()["case"]["reference"])
        self.assertEqual(by_reference.status_code,200,by_reference.text)
        self.assertEqual(by_reference.json()["reports"][0]["public_ref"],lost.json()["case"]["reference"])

    def test_sensitive_lost_report_free_text_is_not_public(self):
        secret_title = "Passport belonging to Person Example"
        secret_detail = "Document number P12345678 and the private name Person Example."
        created = self.client.post("/api/public/reports", json={
            "report_type": "lost", "roll_number": "25B81A66J8",
            "title": secret_title, "description": secret_detail,
            "category": "identity_documents",
            "brand": "PRIVATE BRAND", "primary_color": "Secret blue",
            "visible_features": "Document number P12345678",
            "location_area": "Campus",
        })
        self.assertEqual(created.status_code, 201, created.text)
        ref = created.json()["case"]["reference"]
        listing = self.client.get("/api/public/search?report_type=lost")
        self.assertEqual(listing.status_code, 200, listing.text)
        item = next(row for row in listing.json()["reports"] if row["public_ref"] == ref)
        self.assertEqual(item["category"], "other")
        self.assertEqual(item["title"], "Personal item reported lost")
        self.assertIsNone(item["brand"])
        self.assertIsNone(item["visible_features"])
        self.assertIsNone(item["primary_color"])
        for sensitive_text in (secret_title, secret_detail, "P12345678", "PRIVATE BRAND"):
            self.assertNotIn(sensitive_text, listing.text)
        tracked = self.client.get("/api/public/track/" + ref, headers={
            "X-LostLink-Roll-Number": "25B81A66J8",
            "X-LostLink-Tracking-Secret": created.json()["tracking_secret"],
        })
        self.assertEqual(tracked.status_code, 200, tracked.text)
        self.assertEqual(tracked.json()["case"]["title"], "Personal item reported lost")
        with main.connect_db() as conn:
            row = conn.execute("SELECT title,description FROM reports WHERE public_ref=?", (ref,)).fetchone()
        self.assertEqual(row["title"], secret_title)
        self.assertEqual(row["description"], secret_detail)

    def test_tracking_secret_is_case_scoped_and_roll_number_alone_is_not_access(self):
        first = self.create_public_report(roll="25B81A66J8",title="Blue notebook").json()
        second = self.create_public_report(roll="25B81A66J8",title="Red notebook").json()
        reference = first["case"]["reference"]
        roll_only = self.client.get("/api/public/track/"+reference)
        self.assertNotEqual(roll_only.status_code,200)
        wrong_case = self.client.get(
            "/api/public/track/"+second["case"]["reference"],
            headers={"X-LostLink-Roll-Number":"25B81A66J8","X-LostLink-Tracking-Secret":first["tracking_secret"]},
        )
        self.assertEqual(wrong_case.status_code,404)
        allowed = self.client.get(
            "/api/public/track/"+reference,
            headers={"X-LostLink-Roll-Number":"25B81A66J8","X-LostLink-Tracking-Secret":first["tracking_secret"]},
        )
        self.assertEqual(allowed.status_code,200,allowed.text)
        self.assertNotIn("roll_number",allowed.json()["case"])

    def test_found_items_are_hidden_until_office_physically_verifies_intake(self):
        created = self.create_public_report("found")
        self.assertEqual(created.status_code,201,created.text)
        report_id = created.json()["case"]["id"]
        self.assertEqual(self.client.get("/api/public/found").json()["reports"],[])
        self.office_login()
        wrong_identity = self.intake(report_id,roll="25B81A66J9")
        self.assertEqual(wrong_identity.status_code,422,wrong_identity.text)
        accepted = self.intake(report_id)
        self.assertEqual(accepted.status_code,200,accepted.text)
        public = self.client.get("/api/public/found")
        self.assertEqual(public.status_code,200,public.text)
        self.assertEqual(len(public.json()["reports"]),1)
        item = public.json()["reports"][0]
        self.assertNotIn("roll_number",item)
        self.assertNotIn("tag_id",item)
        self.assertNotIn("storage_location",item)

    def test_public_claim_flows_through_canonical_review_and_physical_handover(self):
        found = self.create_public_report("found")
        self.assertEqual(found.status_code,201,found.text)
        report_id = found.json()["case"]["id"]
        lost = self.client.post("/api/public/reports", json={
            "report_type": "lost",
            "roll_number": "25B81A66J9",
            "title": "Lost matching calculator",
            "description": "Black scientific calculator with a cracked protective cover.",
            "category": "electronics",
            "location_block": "Computer Block",
            "private_detail": "A unique scratch beneath the battery cover known only to the owner.",
        })
        self.assertEqual(lost.status_code,201,lost.text)
        self.office_login()
        intake = self.intake(report_id)
        self.assertEqual(intake.status_code,200,intake.text)
        report_id = intake.json()["report"]["id"]

        # Claim submission must work without a student or office session.
        self.client.cookies.clear()
        claim_payload = {
            "roll_number":"25B81A66J9",
            "evidence":"I can identify a blue sticker below the battery cover and a small scratch on the right edge.",
            "evidence_types":["distinctive_features","other"],
            "lost_report_reference":lost.json()["case"]["reference"],
        }
        claim_url = "/api/public/found/"+report_id+"/claims"
        self.assertEqual(self.client.post(claim_url,json={k:v for k,v in claim_payload.items()
            if k != "lost_report_reference"}).status_code,422)
        self.assertEqual(self.client.post(claim_url,json=claim_payload,
            headers={"X-LostLink-Tracking-Secret":"wrong-token"}).status_code,404)
        claim_response = self.client.post(claim_url,json=claim_payload,
            headers={"X-LostLink-Tracking-Secret":lost.json()["tracking_secret"]})
        self.assertEqual(claim_response.status_code,201,claim_response.text)
        claim = claim_response.json()["claim"]
        tracking_secret = claim_response.json()["tracking_secret"]
        self.assertTrue(claim["reference"])
        self.assertTrue(tracking_secret)
        tracked = self.client.get("/api/public/track/"+claim["reference"],headers={
            "X-LostLink-Roll-Number":"25B81A66J9",
            "X-LostLink-Tracking-Secret":tracking_secret,
        })
        self.assertEqual(tracked.status_code,200,tracked.text)
        self.assertEqual(tracked.json()["claim"]["status"],"pending")
        self.assertEqual(tracked.json()["item"]["status"],"available")
        denied_tracking = self.client.get("/api/public/track/"+claim["reference"],headers={
            "X-LostLink-Roll-Number":"25B81A66J9",
            "X-LostLink-Tracking-Secret":"incorrect-secret",
        })
        self.assertEqual(denied_tracking.status_code,404)
        with main.connect_db() as conn:
            stored = conn.execute("SELECT * FROM claims WHERE public_ref=?",(claim["reference"],)).fetchone()
            self.assertIsNotNone(stored)
            self.assertEqual(stored["submission_channel"],"public")
            self.assertEqual(stored["claimant_roll_number"],"25B81A66J9")
            self.assertFalse(main.table_columns(conn,"public_claims"))

        duplicate = self.client.post("/api/public/found/"+report_id+"/claims",json={
            "roll_number":"25B81A66J9",
            "evidence":"I can identify a blue sticker below the battery cover and a small scratch on the right edge.",
            "evidence_types":["distinctive_features"],
            "lost_report_reference":lost.json()["case"]["reference"],
        },headers={"X-LostLink-Tracking-Secret":lost.json()["tracking_secret"]})
        self.assertEqual(duplicate.status_code,409,duplicate.text)

        self.office_login()
        office_queue = self.client.get("/api/claims?queue=active")
        self.assertEqual(office_queue.status_code,200,office_queue.text)
        self.assertEqual(office_queue.json()["claims"][0]["claimant_roll_number"],"25B81A66J9")
        self.assertEqual(office_queue.json()["claims"][0]["evidence_types"],["distinctive_features","other"])
        self.assertEqual(
            office_queue.json()["claims"][0]["linked_lost_report"]["private_verification_detail"],
            "A unique scratch beneath the battery cover known only to the owner.",
        )
        claim_id = claim["id"]
        checks = ["distinctive_features","date_location","physical_inspection","claimant_identity"]
        denied = self.client.post("/api/claims/"+claim_id+"/decision",json={
            "action":"approve","verification_checks":checks,
            "identity_verified_in_person":True,"verified_roll_number":"25B81A66J8",
        })
        self.assertEqual(denied.status_code,422,denied.text)
        approved = self.client.post("/api/claims/"+claim_id+"/decision",json={
            "action":"approve","verification_checks":checks,
            "identity_verified_in_person":True,"verified_roll_number":"25B81A66J9",
        })
        self.assertEqual(approved.status_code,200,approved.text)
        tag_id = intake.json()["report"]["tag_id"]
        bad_handover = self.client.post("/api/claims/"+claim_id+"/handover",json={
            "tag_id":tag_id,"confirmed_physical_handover":True,
            "claimant_identity_checked":True,"verified_roll_number":"25B81A66J8",
        })
        self.assertEqual(bad_handover.status_code,422,bad_handover.text)
        handover = self.client.post("/api/claims/"+claim_id+"/handover",json={
            "tag_id":tag_id,"confirmed_physical_handover":True,
            "claimant_identity_checked":True,"verified_roll_number":"25B81A66J9",
        })
        self.assertEqual(handover.status_code,200,handover.text)
        with main.connect_db() as conn:
            report = conn.execute("SELECT status FROM reports WHERE id=?",(report_id,)).fetchone()
            claim_row = conn.execute("SELECT status FROM claims WHERE id=?",(claim_id,)).fetchone()
            self.assertEqual(report["status"],"returned")
            self.assertEqual(claim_row["status"],"returned")

    def test_public_lost_report_uses_existing_ai_match_route(self):
        found = self.create_public_report("found")
        self.office_login()
        accepted = self.intake(found.json()["case"]["id"])
        self.assertEqual(accepted.status_code,200,accepted.text)
        lost = self.create_public_report("lost",roll="25B81A66J9",title="Black calculator")
        self.assertEqual(lost.status_code,201,lost.text)
        response = self.client.get(
            "/api/public/reports/"+lost.json()["case"]["reference"]+"/matches",
            headers={"X-LostLink-Roll-Number":"25B81A66J9","X-LostLink-Tracking-Secret":lost.json()["tracking_secret"]},
        )
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn("matches",response.json())


if __name__ == "__main__":
    unittest.main()
