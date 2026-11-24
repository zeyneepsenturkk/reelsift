import json

from django.conf import settings

from apps.accounts.tests.base import PASSWORD, AuthApiTestCase, make_user


class MeTests(AuthApiTestCase):
    def test_anonymous_gets_401_and_csrf_cookie(self):
        response = self.client.get("/api/auth/me")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "not_authenticated")
        cookie = response.cookies["csrftoken"]
        self.assertTrue(cookie.value)
        self.assertFalse(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")

    def test_logged_in_gets_user_and_csrf_cookie(self):
        self.client.force_login(self.user)

        response = self.client.get("/api/auth/me")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "id": self.user.pk,
                "username": "editor",
                "display_name": "Zeynep Şentürk",
                "initials": "ZŞ",
            },
        )
        self.assertIn("csrftoken", response.cookies)


class LoginTests(AuthApiTestCase):
    def test_success_returns_user_and_secure_session_cookie(self):
        response = self.login()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "editor")
        session_cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(session_cookie["httponly"])
        self.assertEqual(session_cookie["samesite"], "Lax")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)

    def test_session_key_and_csrf_token_are_rotated(self):
        headers = self.csrf_headers()
        before = self.client.cookies["csrftoken"].value
        session = self.client.session  # girişten önce saldırganın tanıdığı bir oturum
        session["planted"] = True
        session.save()
        old_key = session.session_key

        response = self.login(headers=headers)

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(self.client.cookies["csrftoken"].value, before)
        self.assertNotEqual(self.client.cookies[settings.SESSION_COOKIE_NAME].value, old_key)

    def test_failures_are_indistinguishable(self):
        make_user("passive", is_active=False)
        cases = [
            ("editor", "yanlis-sifre"),
            ("yok-boyle-biri", PASSWORD),
            ("passive", PASSWORD),
            ("editor", ""),
            ("", ""),
        ]

        responses = [self.login(username, password) for username, password in cases]

        for response in responses:
            self.assertEqual(response.status_code, 401)
        self.assertEqual(len({response.content for response in responses}), 1)
        self.assertEqual(responses[0].json()["code"], "invalid_credentials")
        self.assertNotIn(settings.SESSION_COOKIE_NAME, responses[0].cookies)

    def test_nul_character_is_a_plain_credentials_failure(self):
        response = self.login("edi\x00tor", PASSWORD)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "invalid_credentials")

    def test_missing_csrf_header_is_forbidden(self):
        self.client.get("/api/auth/me")

        response = self.login(headers={})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "forbidden")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_unparsable_body_is_422_without_internal_message(self):
        response = self.client.post(
            "/api/auth/login",
            data="{bozuk json",
            content_type="application/json",
            **self.csrf_headers(),
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": "Geçersiz istek.", "code": "validation_error"})

    def test_missing_field_is_422(self):
        response = self.client.post(
            "/api/auth/login",
            data=json.dumps({"username": "editor"}),
            content_type="application/json",
            **self.csrf_headers(),
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "validation_error")

    def test_failed_attempt_log_has_no_credentials(self):
        with self.assertLogs("apps.accounts.api", level="WARNING") as logs:
            self.login("editor", "gizli-deneme-sifresi")

        text = "\n".join(logs.output)
        self.assertNotIn("gizli-deneme-sifresi", text)
        self.assertNotIn("editor", text)


class LoginThrottleTests(AuthApiTestCase):
    def test_eleventh_attempt_within_a_minute_is_rate_limited(self):
        headers = self.csrf_headers()

        statuses = [self.login("editor", "yanlis", headers=headers).status_code for _ in range(10)]
        blocked = self.login("editor", "yanlis", headers=headers)

        self.assertEqual(statuses, [401] * 10)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(
            blocked.json(),
            {
                "detail": "Çok fazla deneme yaptın. Biraz bekleyip tekrar dene.",
                "code": "rate_limited",
            },
        )

    def test_correct_password_is_also_blocked_after_the_limit(self):
        headers = self.csrf_headers()
        for _ in range(10):
            self.login("editor", "yanlis", headers=headers)

        response = self.login(headers=headers)

        self.assertEqual(response.status_code, 429)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_forged_forwarded_header_does_not_reset_the_limit(self):
        headers = self.csrf_headers()
        for index in range(10):
            self.login("editor", "yanlis", headers=headers, HTTP_X_FORWARDED_FOR=f"10.0.0.{index}")

        response = self.login("editor", "yanlis", headers=headers, HTTP_X_FORWARDED_FOR="10.9.9.9")

        self.assertEqual(response.status_code, 429)

    def test_different_address_has_its_own_counter(self):
        headers = self.csrf_headers()
        for _ in range(10):
            self.login("editor", "yanlis", headers=headers)

        response = self.login(headers=headers, REMOTE_ADDR="203.0.113.7")

        self.assertEqual(response.status_code, 200)


class LogoutTests(AuthApiTestCase):
    def test_logout_ends_the_session(self):
        self.login()
        headers = {"HTTP_X_CSRFTOKEN": self.client.cookies["csrftoken"].value}

        response = self.client.post("/api/auth/logout", **headers)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/api/chats").status_code, 401)

    def test_anonymous_logout_is_also_204(self):
        response = self.client.post("/api/auth/logout", **self.csrf_headers())

        self.assertEqual(response.status_code, 204)

    def test_logout_without_csrf_header_is_forbidden_and_keeps_session(self):
        self.login()

        response = self.client.post("/api/auth/logout")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "forbidden")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
