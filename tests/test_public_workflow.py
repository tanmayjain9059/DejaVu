"""End-to-end regression tests for the no-login public student workflow."""
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.core import config as app_config
from app.core import database as app_database

app_config.DATABASE_URL = ""
app_database.DATABASE_URL = ""
import app.main as main
from app.api.routes import public_workflow as public_routes


class PublicWorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        modules = (main, app_config, app_database, public_routes)
        for module in modules:
            for name, value in {
                "DATA_DIR": root,
                "DB_PATH": root / "public-workflow.sqlite",
                "UPLOAD_DIR": root / "uploads",
                "DATABASE_URL": "",
                "DEMO_MODE": False,
            }.items():
                if hasattr(module, name):
                    setattr(module, name, value)
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

    def test_students_cannot_sign_in_but_can_submit_public_reports(self):
        denied = self.client.post("/api/login",json={
            "email":"student@test.invalid","password":"student-password"
        })
        self.assertEqual(denied.status_code,401,denied.text)
        created = self.create_public_report()
        self.assertEqual(created.status_code,201,created.text)
        payload = created.json()
        self.assertTrue(payload["tracking_secret"])
        with main.connect_db() as conn:
            row = conn.execute("SELECT * FROM reports WHERE public_ref=?",(payload["case"]["reference"],)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["submission_channel"],"public")
            self.assertEqual(row["roll_number"],"25B81A66J8")
            self.assertIsNone(conn.execute("SELECT 1 FROM public_cases").fetchone() if "public_cases" in main.table_columns(conn,"public_cases") else None)

    def test_tracking_secret_is_case_scoped_and_roll_number_alone_is_not_access(self):
        first = self.create_public_report(roll="25B81A66J8",title="Blue notebook").json()
        second = self.create_public_report(roll="25B81A66J8",title="Red notebook").json()
        reference = first["case"]["reference"]
        roll_only = self.client.get("/api/public/track/"+reference,params={"roll_number":"25B81A66J8"})
        self.assertNotEqual(roll_only.status_code,200)
        wrong_case = self.client.get(
            "/api/public/track/"+second["case"]["reference"],
            params={"roll_number":"25B81A66J8"},
            headers={"X-LostLink-Tracking-Secret":first["tracking_secret"]},
        )
        self.assertEqual(wrong_case.status_code,404)
        allowed = self.client.get(
            "/api/public/track/"+reference,
            params={"roll_number":"25B81A66J8"},
            headers={"X-LostLink-Tracking-Secret":first["tracking_secret"]},
        )
        self.assertEqual(allowed.status_code,200,allowed.text)
        self.assertNotIn("roll_number",allowed.json()["case"])

    def test_found_items_are_hidden_until_office_physically_verifies_intake(self):
        created = self.create_public_report("found")
        self.assertEqual(created.status_code,201,created.text)
        reference = created.json()["case"]["reference"]
        self.assertEqual(self.client.get("/api/public/found").json()["reports"],[])
        self.office_login()
        wrong_identity = self.intake(reference,roll="25B81A66J9")
        self.assertEqual(wrong_identity.status_code,422,wrong_identity.text)
        accepted = self.intake(reference)
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
        report_ref = found.json()["case"]["reference"]
        self.office_login()
        intake = self.intake(report_ref)
        self.assertEqual(intake.status_code,200,intake.text)
        report_id = intake.json()["report"]["id"]

        claim_response = self.client.post("/api/public/found/"+report_id+"/claims",json={
            "roll_number":"25B81A66J9",
            "evidence":"I can identify a blue sticker below the battery cover and a small scratch on the right edge.",
            "evidence_types":["distinctive_features","other"],
        })
        self.assertEqual(claim_response.status_code,201,claim_response.text)
        claim = claim_response.json()["claim"]
        self.assertTrue(claim["reference"])
        with main.connect_db() as conn:
            stored = conn.execute("SELECT * FROM claims WHERE public_ref=?",(claim["reference"],)).fetchone()
            self.assertIsNotNone(stored)
            self.assertEqual(stored["submission_channel"],"public")
            self.assertEqual(stored["claimant_roll_number"],"25B81A66J9")
            self.assertIsNone(conn.execute("SELECT 1 FROM public_claims").fetchone() if "public_claims" in main.table_columns(conn,"public_claims") else None)

        duplicate = self.client.post("/api/public/found/"+report_id+"/claims",json={
            "roll_number":"25B81A66J9",
            "evidence":"I can identify a blue sticker below the battery cover and a small scratch on the right edge.",
            "evidence_types":["distinctive_features"],
        })
        self.assertEqual(duplicate.status_code,409,duplicate.text)

        office_queue = self.client.get("/api/claims?queue=active")
        self.assertEqual(office_queue.status_code,200,office_queue.text)
        self.assertEqual(office_queue.json()["claims"][0]["claimant_roll_number"],"25B81A66J9")
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
        accepted = self.intake(found.json()["case"]["reference"])
        self.assertEqual(accepted.status_code,200,accepted.text)
        lost = self.create_public_report("lost",roll="25B81A66J9",title="Black calculator")
        self.assertEqual(lost.status_code,201,lost.text)
        response = self.client.get(
            "/api/public/reports/"+lost.json()["case"]["reference"]+"/matches",
            params={"roll_number":"25B81A66J9"},
            headers={"X-LostLink-Tracking-Secret":lost.json()["tracking_secret"]},
        )
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn("matches",response.json())


if __name__ == "__main__":
    unittest.main()
