import base64
import io
import json
import os
import sys
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEVELOPMENT_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DATABASE_FILE = Path(tempfile.gettempdir()) / f"pocketsmart-tests-{uuid.uuid4().hex}.sqlite3"
# Tests must never touch the real (Supabase) database: blank these *before* the app
# imports, so a developer's backend/.env cannot leak in (load_dotenv never overrides).
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", "")
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_DB_PASSWORD"] = ""
os.environ["ENVIRONMENT"] = "development"
os.environ["RENDER"] = ""
os.environ["DATABASE_PATH"] = str(DATABASE_FILE)
os.environ["GEMINI_API_KEY"] = ""
os.environ["SECRET_KEY"] = "pocketsmart-integration-test-secret"
sys.path.insert(0, str(DEVELOPMENT_DIR))

from fastapi.testclient import TestClient

from app import app


def tearDownModule():
    from database import dispose_engine

    dispose_engine()
    DATABASE_FILE.unlink(missing_ok=True)


class PocketSmartAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def setUp(self):
        self.client.cookies.clear()
        self.username = f"user_{uuid.uuid4().hex[:12]}"

    def register(self, username=None):
        username = username or self.username
        return self.client.post(
            "/register",
            json={
                "username": username,
                "email": f"{username}@example.test",
                "full_name": "PocketSmart Test User",
                "password": "correct-horse-battery",
            },
        )

    def login(self, username=None, password="correct-horse-battery"):
        return self.client.post(
            "/token",
            data={"username": username or self.username, "password": password},
        )

    def create_account_session(self):
        self.assertEqual(self.register().status_code, 201)
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertIn("httponly", response.headers["set-cookie"].lower())
        return response

    def test_every_html_template_compiles(self):
        from jinja2 import Environment, FileSystemLoader

        template_dir = FRONTEND_DIR / "templates"
        environment = Environment(loader=FileSystemLoader(str(template_dir)))
        template_files = list(template_dir.glob("*.html"))
        self.assertGreaterEqual(len(template_files), 9)
        for template_file in template_files:
            with self.subTest(template=template_file.name):
                environment.get_template(template_file.name)

    def test_public_pages_static_assets_and_database_startup(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/login").status_code, 200)
        self.assertEqual(self.client.get("/register").status_code, 200)
        self.assertEqual(self.client.get("/static/styles.css").status_code, 200)
        self.assertEqual(self.client.get("/favicon.ico").status_code, 200)
        self.assertEqual(self.client.get("/static/favicon.svg").status_code, 200)
        startup = self.client.get("/startup")
        self.assertEqual(startup.status_code, 200)
        self.assertFalse(startup.json()["ai_enabled"])
        self.assertTrue(startup.json()["database"]["ok"])
        if not os.getenv("DATABASE_URL"):
            self.assertTrue(DATABASE_FILE.exists())
        self.assertEqual(self.client.get("/dashboard").status_code, 401)
        self.assertEqual(self.client.get("/api/history").status_code, 401)

    def test_gemini_provider_uses_validated_json_when_configured(self):
        from recommendations import generate_recommendations

        valid_response = json.dumps(
            {
                "categories": [
                    {"name": "Room essentials", "allocation": 1000, "items": []}
                ],
                "tips": [],
            }
        )
        client = Mock()
        client.models.generate_content.return_value.text = valid_response
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-provider-key"}):
            with patch("recommendations.genai.Client", return_value=client):
                result, source = generate_recommendations(
                    "home", {"budget": 1000, "rooms": "1", "style": "Modern"}
                )
        self.assertEqual(source, "gemini")
        self.assertEqual(result["categories"][0]["allocation"], 1000)
        client.models.generate_content.assert_called_once()

    def test_registration_password_validation_login_and_logout(self):
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(self.register().status_code, 409)
        self.assertEqual(
            self.client.post("/register", json={"username": "x", "password": "short"}).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(
                "/register",
                json={"username": "long_password", "password": "a" * 73},
            ).status_code,
            422,
        )
        self.assertEqual(self.login(password="not-the-password").status_code, 401)
        login = self.login()
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["token_type"], "bearer")
        self.assertEqual(self.client.get("/api/me").json()["username"], self.username)
        self.assertEqual(self.client.get("/session-info").json()["username"], self.username)
        self.assertEqual(self.client.get("/session-data").json()["recommendations"], 0)
        self.assertEqual(self.client.get("/dashboard").status_code, 200)
        api_logout = self.client.post("/logout")
        self.assertEqual(api_logout.status_code, 204)
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.assertEqual(self.login().status_code, 200)
        response = self.client.get("/logout", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/login")
        self.assertEqual(self.client.get("/dashboard").status_code, 401)

    def test_all_planners_fallback_and_history(self):
        self.create_account_session()
        for path in ("/home-planner", "/party-planner", "/jewelry-planner", "/history"):
            self.assertEqual(self.client.get(path).status_code, 200, path)

        plans = [
            (
                "/generate-home",
                {"budget": 50000, "rooms": "2", "style": "Modern", "room_types": ["Living Room"], "platforms": ["IKEA"]},
                "home",
            ),
            (
                "/generate-party",
                {"budget": 30000, "event_type": "Birthday", "guests": "25", "location": "Home", "includes": ["Catering", "Decoration"]},
                "party",
            ),
            (
                "/generate-jewelry",
                {"budget": 12000, "occasion": "Wedding", "jewelry_types": ["Earrings", "Ring"], "platforms": ["Amazon"]},
                "jewelry",
            ),
        ]
        for path, payload, category in plans:
            response = self.client.post(path, json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body["source"], "fallback")
            self.assertEqual(body["budget"], payload["budget"])
            import json
            recommendation = json.loads(body["recommendations"])
            if category in {"home", "party"}:
                self.assertEqual(sum(item["allocation"] for item in recommendation["categories"]), payload["budget"])
            else:
                self.assertLessEqual(sum(item["price"] for item in recommendation["jewelry"]), payload["budget"])

        history = self.client.get("/api/history").json()
        self.assertEqual(history["total"], 3)
        self.assertEqual({entry["category"] for entry in history["history"]}, {"home", "party", "jewelry"})
        cleared = self.client.delete("/api/history")
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json()["deleted"], 3)
        self.assertEqual(self.client.get("/api/history").json()["total"], 0)

    def test_history_is_isolated_between_accounts_and_bearer_auth_works(self):
        self.create_account_session()
        response = self.client.post(
            "/generate-home",
            json={"budget": 1000, "rooms": "1", "style": "Modern"},
        )
        self.assertEqual(response.status_code, 200)
        other_username = f"other_{uuid.uuid4().hex[:12]}"
        self.assertEqual(self.register(other_username).status_code, 201)
        bearer_login = self.login(other_username)
        bearer_token = bearer_login.json()["access_token"]
        self.client.cookies.clear()
        self.client.headers.update({"Authorization": f"Bearer {bearer_token}"})
        self.assertEqual(self.client.get("/api/history").json()["total"], 0)
        self.client.headers.pop("Authorization", None)

    def test_party_plan_without_selected_services_still_uses_full_budget(self):
        self.create_account_session()
        response = self.client.post(
            "/generate-party",
            json={
                "budget": 25000,
                "event_type": "Birthday",
                "guests": 20,
                "includes": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        result = __import__("json").loads(response.json()["recommendations"])
        self.assertEqual(
            sum(category["allocation"] for category in result["categories"]),
            25000,
        )

    def test_invalid_planner_inputs_and_outfit_images(self):
        self.create_account_session()
        self.assertEqual(
            self.client.post("/generate-home", json={"budget": 0, "rooms": "1", "style": "Modern"}).status_code,
            422,
        )
        self.assertEqual(
            self.client.post("/generate-party", json={"budget": 1000, "event_type": "Birthday", "guests": 0}).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(
                "/generate-jewelry",
                json={"budget": 1000, "occasion": "Wedding", "image": "not-base64"},
            ).status_code,
            422,
        )
        from PIL import Image

        image_buffer = io.BytesIO()
        Image.new("RGB", (4, 4), color=(25, 80, 140)).save(image_buffer, format="PNG")
        encoded_image = base64.b64encode(image_buffer.getvalue()).decode("ascii")
        image_response = self.client.post(
            "/generate-jewelry",
            json={
                "budget": 3000,
                "occasion": "Wedding",
                "jewelry_types": ["Earrings"],
                "image": encoded_image,
            },
        )
        self.assertEqual(image_response.status_code, 200, image_response.text)
        self.assertEqual(image_response.json()["source"], "fallback")
        image_plan = __import__("json").loads(image_response.json()["recommendations"])
        self.assertIsNone(image_plan["outfit_analysis"])
        self.assertTrue(any("unavailable in offline mode" in tip for tip in image_plan["tips"]))
        generic = self.client.post(
            "/recommendations-details",
            json={"category": "home", "budget": 1000, "preferences": {"rooms": "1"}},
        )
        self.assertEqual(generic.status_code, 200)
        self.assertEqual(generic.json()["source"], "fallback")
        self.assertEqual(self.client.get("/session-info").status_code, 200)


class PocketSmartSrsTests(unittest.TestCase):
    """Tests for the SRS features added on top of the original suite."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def setUp(self):
        self.client.cookies.clear()
        self.client.headers.pop("Authorization", None)
        self.username = f"user_{uuid.uuid4().hex[:12]}"
        self.assertEqual(
            self.client.post("/register", json={"username": self.username, "password": "correct-horse-battery"}).status_code,
            201,
        )
        self.login_response = self.client.post(
            "/token", data={"username": self.username, "password": "correct-horse-battery"}
        )
        self.assertEqual(self.login_response.status_code, 200)

    def _plan(self, path, payload):
        response = self.client.post(path, json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        return body, json.loads(body["recommendations"])

    def test_home_quantities_are_honoured_and_budget_adds_up(self):
        body, plan = self._plan(
            "/generate-home",
            {"budget": 100000, "rooms": "2", "style": "Modern", "room_types": ["Living Room", "Kitchen"],
             "platforms": ["Amazon", "IKEA", "Myntra", "Ajio"],
             "num_lights": 5, "num_fans": 4, "num_furniture": 2, "num_dining_tables": 1},
        )
        quantities = {item["name"]: item["quantity"] for cat in plan["categories"] for item in cat["items"]}
        self.assertEqual(quantities["LED light fixtures"], 5)
        self.assertEqual(quantities["Energy-efficient ceiling fans"], 4)
        self.assertEqual(quantities["Furniture pieces"], 2)
        self.assertEqual(quantities["Dining tables"], 1)
        self.assertEqual(sum(c["allocation"] for c in plan["categories"]), 100000)
        self.assertEqual(plan["remaining_budget"], 0)
        self.assertEqual(plan["total_budget"], 100000)
        self.assertEqual(len(plan["calculation_table"]), len(plan["categories"]))
        links = plan["categories"][0]["items"][0]["shopping_links"]
        self.assertEqual(set(links), {"Amazon", "IKEA", "Myntra", "Ajio"})
        self.assertTrue(all(url.startswith("https://") for url in links.values()))

    def test_home_without_quantities_still_works(self):
        _, plan = self._plan("/generate-home", {"budget": 50000, "rooms": "1", "style": "Modern"})
        self.assertEqual(sum(c["allocation"] for c in plan["categories"]), 50000)

    def test_party_links_follow_category_rules(self):
        _, plan = self._plan(
            "/generate-party",
            {"budget": 40000, "event_type": "Birthday", "guests": 30, "location": "Chennai",
             "includes": ["Catering", "Decoration", "Entertainment"]},
        )
        by_category = {c["name"]: set(c["items"][0]["shopping_links"]) for c in plan["categories"]}
        self.assertEqual(by_category["Catering"], {"Swiggy", "Zomato"})
        self.assertIn("Meesho", by_category["Decoration"])
        self.assertIn("BookMyShow", by_category["Entertainment"])
        venue = plan["venues"][0]
        self.assertTrue({"OYO", "Booking", "MakeMyTrip"} <= set(venue["search_links"]))

    def test_jewelry_links_and_remaining_budget(self):
        _, plan = self._plan(
            "/generate-jewelry",
            {"budget": 20000, "occasion": "Wedding", "jewelry_types": ["Earrings", "Ring"],
             "platforms": ["Tanishq", "CaratLane"]},
        )
        for item in plan["jewelry"]:
            self.assertEqual(set(item["shopping_links"]), {"Tanishq", "CaratLane"})
        spent = sum(item["price"] for item in plan["jewelry"])
        self.assertAlmostEqual(plan["remaining_budget"], 20000 - spent, places=2)

    def test_unknown_platforms_never_become_links(self):
        _, plan = self._plan(
            "/generate-home",
            {"budget": 10000, "rooms": "1", "style": "Modern",
             "platforms": ["Amazon", "javascript:alert(1)", "evil.example"]},
        )
        links = plan["categories"][0]["items"][0]["shopping_links"]
        self.assertEqual(set(links), {"Amazon"})

    def test_recommendation_details_endpoint_and_ownership(self):
        body, _ = self._plan("/generate-home", {"budget": 5000, "rooms": "1", "style": "Modern"})
        details = self.client.get(f"/recommendation-details/{body['id']}")
        self.assertEqual(details.status_code, 200)
        self.assertEqual(details.json()["type"], "home")
        self.assertIn("categories", details.json()["full_result"])
        self.assertEqual(self.client.get("/recommendation-details/does-not-exist").status_code, 404)
        # another account must not see it
        self.client.cookies.clear()
        other = f"other_{uuid.uuid4().hex[:12]}"
        self.client.post("/register", json={"username": other, "password": "correct-horse-battery"})
        self.client.post("/token", data={"username": other, "password": "correct-horse-battery"})
        self.assertEqual(self.client.get(f"/recommendation-details/{body['id']}").status_code, 404)

    def test_session_info_and_session_data_post(self):
        info = self.client.get("/session-info").json()
        self.assertEqual(info["username"], self.username)
        for key in ("login_time", "last_activity", "session_duration", "user_data"):
            self.assertIn(key, info)
        updated = self.client.post("/session-data", json={"theme": "dark"})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["data"], {"theme": "dark"})
        self.client.post("/session-data", json={"lang": "en"})
        self.assertEqual(self.client.get("/session-info").json()["user_data"], {"theme": "dark", "lang": "en"})
        self.assertEqual(self.client.post("/session-data", json={"x": "y" * 20000}).status_code, 413)

    def test_logout_revokes_the_token_server_side(self):
        token = self.login_response.json()["access_token"]
        self.client.post("/logout")
        self.client.cookies.clear()
        stolen = self.client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(stolen.status_code, 401)

    def test_session_cleanup_removes_idle_sessions(self):
        from database import cleanup_sessions, get_session, update_session_data

        token = self.login_response.json()["access_token"]
        from auth import session_id_from_token

        session_id = session_id_from_token(token)
        self.assertIsNotNone(get_session(session_id))
        self.assertEqual(cleanup_sessions(idle_minutes=30), 0 + cleanup_sessions(idle_minutes=30))
        self.assertIsNotNone(get_session(session_id))
        # idle_minutes=-1 treats every session as idle
        self.assertGreaterEqual(cleanup_sessions(idle_minutes=-1), 1)
        self.assertIsNone(get_session(session_id))
        self.assertEqual(self.client.get("/api/me").status_code, 401)

    def test_tampered_or_unsessioned_tokens_are_rejected(self):
        from auth import create_access_token

        no_jti = create_access_token({"sub": self.username})
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/me", headers={"Authorization": f"Bearer {no_jti}"}).status_code, 401)
        self.assertEqual(self.client.get("/api/me", headers={"Authorization": "Bearer garbage"}).status_code, 401)

    def test_browser_without_session_gets_login_redirect_page(self):
        self.client.cookies.clear()
        response = self.client.get("/dashboard", headers={"accept": "text/html"})
        self.assertEqual(response.status_code, 401)
        self.assertIn("/login?expired=1", response.text)
        api = self.client.get("/api/history", headers={"accept": "application/json"})
        self.assertEqual(api.status_code, 401)
        self.assertEqual(api.json()["detail"], "Authentication required")

    def test_cors_allows_only_configured_origins(self):
        allowed = self.client.options(
            "/token",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
        )
        self.assertEqual(allowed.headers.get("access-control-allow-origin"), "http://localhost:3000")
        denied = self.client.options(
            "/token",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
        self.assertNotIn("access-control-allow-origin", denied.headers)

    def test_case_insensitive_username_uniqueness(self):
        response = self.client.post(
            "/register", json={"username": self.username.upper(), "password": "correct-horse-battery"}
        )
        self.assertEqual(response.status_code, 409)
        login = self.client.post("/token", data={"username": self.username.upper(), "password": "correct-horse-battery"})
        self.assertEqual(login.status_code, 200)

    def test_gemini_failure_falls_back_and_reports_it(self):
        failing = Mock()
        failing.models.generate_content.side_effect = RuntimeError("model retired")
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k", "GEMINI_MODEL": "m1", "GEMINI_FALLBACK_MODELS": "m2"}):
            with patch("recommendations.genai.Client", return_value=failing):
                body, plan = self._plan("/generate-home", {"budget": 8000, "rooms": "1", "style": "Modern"})
        self.assertEqual(body["source"], "fallback")
        self.assertEqual(failing.models.generate_content.call_count, 2)  # both models tried
        self.assertTrue(any("unavailable" in tip for tip in plan["tips"]))

    def test_gemini_over_budget_plan_is_rejected(self):
        over = Mock()
        over.models.generate_content.return_value.text = json.dumps(
            {"categories": [{"name": "X", "allocation": 999999, "items": []}], "tips": []}
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
            with patch("recommendations.genai.Client", return_value=over):
                body, _ = self._plan("/generate-home", {"budget": 1000, "rooms": "1", "style": "Modern"})
        self.assertEqual(body["source"], "fallback")

    def test_gemini_success_is_enriched(self):
        good = Mock()
        good.models.generate_content.return_value.text = (
            '```json\n{"categories":[{"name":"Lighting","allocation":"3000","items":'
            '[{"name":"LED Bulb","description":"d","price":"₹100","quantity":5,"search_terms":"led bulb warm white"}]}],"tips":[]}\n```'
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
            with patch("recommendations.genai.Client", return_value=good):
                body, plan = self._plan("/generate-home", {"budget": 5000, "rooms": "1", "style": "Modern"})
        self.assertEqual(body["source"], "gemini")
        item = plan["categories"][0]["items"][0]
        self.assertEqual(item["price"], 100)
        self.assertIn("led+bulb+warm+white", item["shopping_links"]["Amazon"])
        self.assertEqual(plan["remaining_budget"], 2000)

    def test_startup_reports_database(self):
        info = self.client.get("/startup").json()
        self.assertEqual(info["status"], "running")
        self.assertIn(info["database"]["backend"], {"sqlite", "postgresql"})


if __name__ == "__main__":
    unittest.main()
