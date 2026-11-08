"""Regression tests for the anonymous roll-attributed public workflow."""
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


class PublicWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        for module in (main, app_config, app_database, public_routes):
            for name, value in {
                "DATA_DIR": root, "DB_PATH": root / "public.sqlite",
                "UPLOAD_DIR": root / "uploads", "DATABASE_URL": "",
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
                ("office@test.invalid","Office","office",main.hash_password("office-password"),main.now_iso()),
            )
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_report_is_public_and_tracking_secret_is_required(self):
        response = self.client.post("/api/public/reports", json={
            "report_type":"lost","roll_number":"25B81A66J8",
            "title":"Black calculator","description":"Black scientific calculator with a cracked cover.",
            "category":"electronics","location_block":"Block A",
        })
        self.assertEqual(response.status_code,201,response.text)
        payload=response.json()
        reference=payload["case"]["reference"]
        token=payload["tracking_secret"]
        self.assertTrue(token)
        self.assertEqual(self.client.get("/api/public/track/"+reference,
                         params={"roll_number":"25B81A66J8"}).status_code,422)
        self.assertEqual(self.client.get("/api/public/track/"+reference,
                         params={"roll_number":"25B81A66J8"},
                         headers={"X-LostLink-Tracking-Secret":"wrong"}).status_code,404)
        allowed=self.client.get("/api/public/track/"+reference,
                    params={"roll_number":"25B81A66J8"},
                    headers={"X-LostLink-Tracking-Secret":token})
        self.assertEqual(allowed.status_code,200,allowed.text)
        self.assertEqual(allowed.json()["case"]["roll_number"],"25B81A66J8")

    def test_roll_number_alone_does_not_unlock_another_case(self):
        created=[]
        for title in ("Blue notebook","Red notebook"):
            r=self.client.post("/api/public/reports",json={
                "report_type":"lost","roll_number":"25B81A66J8","title":title,
                "description":"Notebook with identifying handwritten notes inside.",
                "category":"books_stationery","location_block":"Block B",
            })
            self.assertEqual(r.status_code,201,r.text)
            created.append(r.json())
        token=created[0]["tracking_secret"]
        other=created[1]["case"]["reference"]
        denied=self.client.get("/api/public/track/"+other,
                    params={"roll_number":"25B81A66J8"},
                    headers={"X-LostLink-Tracking-Secret":token})
        self.assertEqual(denied.status_code,404)

    def test_found_item_hidden_until_staff_confirms_intake(self):
        report=self.client.post("/api/public/reports",json={
            "report_type":"found","roll_number":"25B81A66J8",
            "title":"Steel bottle","description":"Silver steel bottle with a black lid and dented base.",
            "category":"accessories","location_block":"Block C",
        })
        self.assertEqual(report.status_code,201,report.text)
        self.assertEqual(self.client.get("/api/public/found").json()["reports"],[])
        login=self.client.post("/api/login",json={
            "email":"office@test.invalid","password":"office-password"})
        self.assertEqual(login.status_code,200,login.text)
        intake=self.client.post("/api/public/office/"+report.json()["case"]["reference"]+"/intake",
            json={"confirmed_physical_receipt":True,"storage_location":"Cabinet A / Shelf 2",
                  "tag_id":"LL-CVR-2026-0001","private_detail":"Small dent underneath."})
        # Intake endpoint currently uses the internal UUID, not the public reference.
        if intake.status_code == 404:
            with main.connect_db() as conn:
                case_id=conn.execute("SELECT id FROM public_cases WHERE public_ref=?",
                    (report.json()["case"]["reference"],)).fetchone()["id"]
            intake=self.client.post("/api/public/office/"+case_id+"/intake",
                json={"confirmed_physical_receipt":True,"storage_location":"Cabinet A / Shelf 2",
                      "tag_id":"LL-CVR-2026-0001","private_detail":"Small dent underneath."})
        self.assertEqual(intake.status_code,200,intake.text)
        public=self.client.get("/api/public/found")
        self.assertEqual(len(public.json()["reports"]),1)
        self.assertNotIn("tag_id",public.json()["reports"][0])
        self.assertNotIn("storage_location",public.json()["reports"][0])


if __name__ == "__main__":
    unittest.main()
