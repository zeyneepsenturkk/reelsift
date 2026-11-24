import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.db import OperationalError
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from apps.core.exceptions import ServiceError
from apps.core.schemas import GpuOut
from apps.core.services import health


class HealthServiceTests(TestCase):
    def test_check_database_returns_pgvector_version(self):
        version = health.check_database()

        self.assertRegex(version, r"^\d+\.\d+")

    def test_check_database_raises_when_connection_fails(self):
        with patch("apps.core.services.health.connection") as fake_connection:
            fake_connection.cursor.side_effect = OperationalError("bağlantı yok")

            with self.assertRaises(ServiceError) as ctx:
                health.check_database()

        self.assertEqual(ctx.exception.code, "database_unavailable")
        self.assertEqual(ctx.exception.status_code, 503)

    def test_check_database_raises_when_pgvector_missing(self):
        with patch("apps.core.services.health.connection") as fake_connection:
            cursor = MagicMock()
            cursor.fetchone.return_value = None
            fake_connection.cursor.return_value.__enter__.return_value = cursor

            with self.assertRaises(ServiceError) as ctx:
                health.check_database()

        self.assertEqual(ctx.exception.code, "pgvector_missing")

    def test_get_health_collects_all_checks(self):
        result = health.get_health()

        self.assertEqual(result.status, "ok")
        self.assertTrue(result.database)
        self.assertIsInstance(result.gpu.available, bool)
        self.assertIsInstance(result.data_mounted, bool)
        self.assertIsInstance(result.models_mounted, bool)

    def test_get_health_propagates_service_error(self):
        error = ServiceError("Veritabanına bağlanılamadı.", "database_unavailable", 503)
        with patch("apps.core.services.health.check_database", side_effect=error):
            with self.assertRaises(ServiceError) as ctx:
                health.get_health()

        self.assertIs(ctx.exception, error)


class GpuCheckTests(SimpleTestCase):
    def test_gpu_unavailable_when_torch_missing(self):
        with patch("apps.core.services.health.find_spec", return_value=None):
            self.assertEqual(health.check_gpu(), GpuOut(available=False))

    def test_gpu_unavailable_when_cuda_not_visible(self):
        with patch("torch.cuda.is_available", return_value=False):
            self.assertEqual(health.check_gpu(), GpuOut(available=False))

    def test_gpu_name_reported_when_cuda_visible(self):
        with (
            patch("torch.cuda.is_available", return_value=True),
            patch("torch.cuda.get_device_name", return_value="Test GPU"),
        ):
            self.assertEqual(health.check_gpu(), GpuOut(available=True, name="Test GPU"))


class MountCheckTests(SimpleTestCase):
    def test_mount_point_is_reported_as_mounted(self):
        # Dosya sisteminin kökü her zaman bir bağlama noktasıdır.
        root = Path(tempfile.gettempdir()).anchor

        self.assertTrue(health.check_mount(root))

    def test_plain_directory_is_not_reported_as_mounted(self):
        with tempfile.TemporaryDirectory() as plain_dir:
            self.assertFalse(health.check_mount(plain_dir))

    def test_missing_path_is_not_reported_as_mounted(self):
        self.assertFalse(health.check_mount("/yok/boyle/bir/yol"))


class HealthApiTests(TestCase):
    def test_health_returns_typed_payload(self):
        response = self.client.get(reverse("api:get_health"))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["database"])
        self.assertIn("pgvector_version", body)
        self.assertEqual(set(body["gpu"]), {"available", "name"})

    def test_health_error_uses_uniform_error_shape(self):
        error = ServiceError("Veritabanına bağlanılamadı.", "database_unavailable", 503)
        with patch("apps.core.services.health.check_database", side_effect=error):
            response = self.client.get(reverse("api:get_health"))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "Veritabanına bağlanılamadı.", "code": "database_unavailable"},
        )

    def test_unknown_path_uses_uniform_error_shape(self):
        response = self.client.get("/api/yok")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(set(response.json()), {"detail", "code"})

    def test_unknown_path_post_uses_uniform_error_shape(self):
        csrf_client = Client(enforce_csrf_checks=True)

        response = csrf_client.post("/api/yok", data={})

        self.assertEqual(response.status_code, 404)
        self.assertTrue(response["Content-Type"].startswith("application/json"))
        self.assertEqual(response.json(), {"detail": "Bulunamadı.", "code": "not_found"})
