"""Regression tests for the anonymous roll-attributed public workflow."""
import os
import tempfile
from io import BytesIO
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

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

    def test_public_lost_case_returns_ai_ranked_found_candidates(self):
        found = self.client.post("/api/public/reports", json={
            "report_type":"found","roll_number":"25B81A66J8",
            "title":"Black scientific calculator","description":"Black scientific calculator with a cracked protective cover.",
            "category":"electronics","location_block":"Block A","occurred_at":"2026-11-08T12:00:00",
        })
        self.assertEqual(found.status_code,201,found.text)
        found_ref = found.json()["case"]["reference"]
        login = self.client.post("/api/login", json={
            "email":"office@test.invalid","password":"office-password"})
        self.assertEqual(login.status_code,200,login.text)
        intake = self.client.post("/api/public/office/"+found_ref+"/intake", json={
            "confirmed_physical_receipt":True,"identity_verified_in_person":True,
            "verified_roll_number":"25B81A66J8","storage_location":"Cabinet A / Shelf 2",
            "tag_id":"LL-CVR-2026-0002","private_detail":"Small blue mark below the display.",
        })
        self.assertEqual(intake.status_code,200,intake.text)
        lost = self.client.post("/api/public/reports", json={
            "report_type":"lost","roll_number":"25B81A66J9",
            "title":"Black scientific calculator","description":"Lost a black scientific calculator with a cracked protective cover.",
            "category":"electronics","location_block":"Block A","occurred_at":"2026-11-08T12:15:00",
        })
        self.assertEqual(lost.status_code,201,lost.text)
        payload = lost.json()
        tracked = self.client.get("/api/public/track/"+payload["case"]["reference"],
            params={"roll_number":"25B81A66J9"},
            headers={"X-LostLink-Tracking-Secret":payload["tracking_secret"]})
        self.assertEqual(tracked.status_code,200,tracked.text)
        matches = tracked.json().get("matches", [])
        self.assertTrue(matches)
        self.assertEqual(matches[0]["report"]["reference"], found_ref)
        self.assertTrue(matches[0]["reasons"])
        self.assertIn("do not prove ownership", tracked.json()["matching_note"])

    def test_public_report_photo_uses_private_storage_and_duplicate_detection(self):
        report = self.client.post("/api/public/reports", json={
            "report_type":"lost","roll_number":"25B81A66J8",
            "title":"Blue water bottle","description":"Blue bottle with a small white scratch near the cap.",
            "category":"other","location_block":"Block A",
        })
        self.assertEqual(report.status_code,201,report.text)
        payload = report.json()
        image = Image.new("RGB",(64,64),(20,80,140))
        raw = BytesIO()
        image.save(raw,format="PNG")
        upload = self.client.post(
            "/api/public/cases/"+payload["case"]["reference"]+"/image",
            params={"roll_number":"25B81A66J8"},
            headers={"X-LostLink-Tracking-Secret":payload["tracking_secret"]},
            files={"file":("bottle.png",raw.getvalue(),"image/png")},
        )
        self.assertEqual(upload.status_code,201,upload.text)
        with main.connect_db() as conn:
            stored = conn.execute("SELECT image_path FROM public_cases WHERE public_ref=?",
                                  (payload["case"]["reference"],)).fetchone()
        self.assertTrue(stored["image_path"])
        self.assertTrue((main.UPLOAD_DIR / stored["image_path"]).is_file())

        other = self.client.post("/api/public/reports", json={
            "report_type":"lost","roll_number":"25B81A66J9",
            "title":"Another blue bottle","description":"Another blue bottle with a white scratch near the cap.",
            "category":"other","location_block":"Block B",
        }).json()
        duplicate = self.client.post(
            "/api/public/cases/"+other["case"]["reference"]+"/image",
            params={"roll_number":"25B81A66J9"},
            headers={"X-LostLink-Tracking-Secret":other["tracking_secret"]},
            files={"file":("duplicate.png",raw.getvalue(),"image/png")},
        )
        self.assertEqual(duplicate.status_code,409,duplicate.text)

    def test_found_photo_is_not_public_until_office_intake(self):
        report = self.client.post("/api/public/reports", json={
            "report_type":"found","roll_number":"25B81A66J8",
            "title":"Green notebook","description":"Green notebook with a torn lower-right corner.",
            "category":"stationery","location_block":"Block A",
        })
        self.assertEqual(report.status_code,201,report.text)
        payload = report.json()
        image = Image.new("RGB",(64,64),(10,120,60))
        raw = BytesIO()
        image.save(raw,format="PNG")
        upload = self.client.post(
            "/api/public/cases/"+payload["case"]["reference"]+"/image",
            params={"roll_number":"25B81A66J8"},
            headers={"X-LostLink-Tracking-Secret":payload["tracking_secret"]},
            files={"file":("notebook.png",raw.getvalue(),"image/png")},
        )
        self.assertEqual(upload.status_code,201,upload.text)
        self.assertEqual(self.client.get("/api/public/found/"+payload["case"]["reference"]+"/image").status_code,404)
        login = self.client.post("/api/login", json={
            "email":"office@test.invalid","password":"office-password"})
        self.assertEqual(login.status_code,200,login.text)
        intake = self.client.post("/api/public/office/"+payload["case"]["reference"]+"/intake",json={
            "confirmed_physical_receipt":True,"identity_verified_in_person":True,
            "verified_roll_number":"25B81A66J8","storage_location":"Cabinet A / Shelf 2",
            "tag_id":"LL-CVR-2026-0003","private_detail":"Torn lower-right corner.",
        })
        self.assertEqual(intake.status_code,200,intake.text)
        preview = self.client.get("/api/public/found/"+payload["case"]["reference"]+"/image")
        self.assertEqual(preview.status_code,200,preview.text)
        self.assertEqual(preview.headers.get("content-type"),"image/jpeg")

    def test_claim_approval_requires_matching_physical_id_and_verification_checks(self):
        report=self.client.post("/api/public/reports",json={
            "report_type":"found","roll_number":"25B81A66J8",
            "title":"Black calculator","description":"Black scientific calculator with a cracked protective cover.",
            "category":"electronics","location_block":"Block A",
        })
        self.assertEqual(report.status_code,201,report.text)
        reference=report.json()["case"]["reference"]
        intake=self.client.post("/api/public/office/"+reference+"/intake",json={
            "confirmed_physical_receipt":True,"identity_verified_in_person":True,
            "verified_roll_number":"25B81A66J8","storage_location":"Cabinet A / Shelf 2",
            "tag_id":"LL-CVR-2026-0002","private_detail":"Blue mark beneath the cover.",
        })
        self.assertEqual(intake.status_code,401,intake.text)

        login=self.client.post("/api/login",json={
            "email":"office@test.invalid","password":"office-password"})
        self.assertEqual(login.status_code,200,login.text)
        intake=self.client.post("/api/public/office/"+reference+"/intake",json={
            "confirmed_physical_receipt":True,"identity_verified_in_person":True,
            "verified_roll_number":"25B81A66J8","storage_location":"Cabinet A / Shelf 2",
            "tag_id":"LL-CVR-2026-0002","private_detail":"Blue mark beneath the cover.",
        })
        self.assertEqual(intake.status_code,200,intake.text)
        with main.connect_db() as conn:
            case=conn.execute("SELECT id FROM public_cases WHERE public_ref=?",(reference,)).fetchone()
        claim=self.client.post("/api/public/found/"+case["id"]+"/claims",json={
            "roll_number":"25B81A66J9",
            "evidence":"There is a small scratch on the lower-right corner that I can identify.",
            "evidence_types":["distinctive_features","date_location"],
        })
        self.assertEqual(claim.status_code,201,claim.text)
        duplicate=self.client.post("/api/public/found/"+case["id"]+"/claims",json={
            "roll_number":"25B81A66J9",
            "evidence":"There is a small scratch on the lower-right corner that I can identify.",
            "evidence_types":["distinctive_features","date_location"],
        })
        self.assertEqual(duplicate.status_code,409,duplicate.text)
        with main.connect_db() as conn:
            claim_row=conn.execute("SELECT id FROM public_claims WHERE public_ref=?",
                (claim.json()["claim"]["reference"],)).fetchone()
        mismatch=self.client.post("/api/public/office/claims/"+claim_row["id"]+"/decision",json={
            "action":"approve","identity_verified_in_person":True,
            "verified_roll_number":"25B81A66J8",
            "verification_checks":["distinctive_features","date_location","physical_inspection","supporting_evidence"],
        })
        self.assertEqual(mismatch.status_code,422,mismatch.text)
        missing_checks=self.client.post("/api/public/office/claims/"+claim_row["id"]+"/decision",json={
            "action":"approve","identity_verified_in_person":True,
            "verified_roll_number":"25B81A66J9",
        })
        self.assertEqual(missing_checks.status_code,422,missing_checks.text)

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
        intake_url="/api/public/office/"+report.json()["case"]["reference"]+"/intake"
        mismatch=self.client.post(intake_url,json={
            "confirmed_physical_receipt":True,"identity_verified_in_person":True,
            "verified_roll_number":"25B81A66J9","storage_location":"Cabinet A / Shelf 2",
            "tag_id":"LL-CVR-2026-0001","private_detail":"Small dent underneath.",
        })
        self.assertEqual(mismatch.status_code,422,mismatch.text)
        intake=self.client.post(intake_url,json={
            "confirmed_physical_receipt":True,"identity_verified_in_person":True,
            "verified_roll_number":"25B81A66J8","storage_location":"Cabinet A / Shelf 2",
            "tag_id":"LL-CVR-2026-0001","private_detail":"Small dent underneath.",
        })
        self.assertEqual(intake.status_code,200,intake.text)
        public=self.client.get("/api/public/found")
        self.assertEqual(len(public.json()["reports"]),1)
        self.assertNotIn("tag_id",public.json()["reports"][0])
        self.assertNotIn("storage_location",public.json()["reports"][0])


if __name__ == "__main__":
    unittest.main()
