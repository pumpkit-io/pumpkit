"""Exercise the managed stack CLI without starting containers or contacting providers."""

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[2]


class DevStackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()
        shutil.copy(SOURCE / "scripts/dev-stack", self.root / "scripts/dev-stack")
        shutil.copy(
            SOURCE / "scripts/check-personal-stack.py",
            self.root / "scripts/check-personal-stack.py",
        )
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.trace = self.root / "trace"
        for name, body in {
            "portless": 'printf "portless %s\\n" "$*" >> "$TRACE"; case "$1" in get) echo "http://$2.localhost:1355";; esac',
            "curl": 'if [[ "$*" == *http_code* ]]; then echo 200; fi',
            "docker": 'printf "%s\\n" "$*" >> "$TRACE"; case " $* " in *" config "*) printf "%s" "$PERSONAL_CONFIG";; *" port "*) echo 127.0.0.1:54123;; *" ps "*) echo container;; esac',
        }.items():
            path = self.bin / name
            path.write_text("#!/usr/bin/env bash\n" + body + "\n")
            path.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "TRACE": str(self.trace),
            "PERSONAL_CONFIG": json.dumps(
                {
                    "services": {
                        "backend": {
                            "environment": {
                                "STRIPE_SECRET_KEY": "sk_test_dummy",
                                "STRIPE_PUBLISHABLE_KEY": "pk_test_dummy",
                                "STRIPE_WEBHOOK_SECRET": "whsec_dummy",
                                "X_CLIENT_ID": "x",
                                "X_CLIENT_SECRET": "x",
                                "TRIAL_IDENTITY_KEYS": "persistent",
                                "BILLING_PLAN_KEYS": '["monthly"]',
                            }
                        }
                    }
                }
            ),
        }

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args):
        return subprocess.run(
            ["scripts/dev-stack", *args],
            cwd=self.root,
            env=self.env,
            text=True,
            capture_output=True,
        )

    def test_real_mode_persists_url_and_compose_selection_without_secrets(self):
        result = self.run_cli("up", "--real-x", "http://127.0.0.1:59237")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "http://127.0.0.1:59237")
        self.assertEqual(self.run_cli("url").stdout.strip(), result.stdout.strip())
        self.assertEqual(self.run_cli("status").stdout.strip(), "running")
        self.assertEqual(self.run_cli("logs", "backend").returncode, 0)
        self.assertIn("compose.real-x.yml", self.trace.read_text())
        self.assertIn("pumpkit-dev-real-x", self.trace.read_text())
        self.assertFalse((self.root / ".sdlc/dev-stack/e2e-target").exists())
        self.assertNotEqual(self.run_cli("up").returncode, 0)
        self.assertEqual(self.run_cli("down").returncode, 0)
        self.assertEqual(self.run_cli("url").stdout.strip(), result.stdout.strip())
        self.assertEqual(self.run_cli("destroy").returncode, 0)
        self.assertEqual(self.run_cli("up").returncode, 0)
        self.assertTrue((self.root / ".sdlc/dev-stack/e2e-target").exists())

    def test_personal_mode_persists_and_does_not_start_emulators(self):
        result = self.run_cli("up", "--personal", "http://localhost:59238")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "http://localhost:59238")
        self.assertEqual(self.run_cli("url").stdout.strip(), result.stdout.strip())
        self.assertEqual(self.run_cli("status").stdout.strip(), "running")
        self.assertEqual(self.run_cli("logs", "backend").returncode, 0)
        trace = self.trace.read_text()
        self.assertIn("pumpkit-dev-personal", trace)
        self.assertIn("compose.personal.yml", trace)
        self.assertNotIn("compose.emulators.yml", trace)
        self.assertNotIn("--profile emulators", trace)
        self.assertNotIn("portless", trace)
        self.assertFalse((self.root / ".sdlc/dev-stack/e2e-target").exists())
        self.assertNotEqual(self.run_cli("up").returncode, 0)
        self.assertEqual(self.run_cli("down").returncode, 0)
        self.assertEqual(self.run_cli("url").stdout.strip(), result.stdout.strip())
        self.assertEqual(self.run_cli("up", "--personal").returncode, 0)

    def test_personal_mode_rejects_invalid_settings_before_starting(self):
        valid = json.loads(self.env["PERSONAL_CONFIG"])
        for key, value in [
            ("STRIPE_SECRET_KEY", "sk_live_do-not-print"),
            ("STRIPE_PUBLISHABLE_KEY", "pk_live_do-not-print"),
            ("STRIPE_WEBHOOK_SECRET", ""),
            ("X_CLIENT_ID", ""),
            ("TRIAL_IDENTITY_KEYS", ""),
            ("BILLING_PLAN_KEYS", "[]"),
            ("X_API_URL", "http://emulate:4002"),
            ("X_AUTHORIZE_URL", "http://fake/authorize"),
            ("STRIPE_API_URL", "http://emulate:4001"),
            ("COUPONS_ENABLED", "true"),
        ]:
            with self.subTest(key=key):
                config = json.loads(json.dumps(valid))
                config["services"]["backend"]["environment"][key] = value
                self.env["PERSONAL_CONFIG"] = json.dumps(config)
                result = self.run_cli("up", "--personal", "http://localhost:59238")
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("do-not-print", result.stderr)
                self.assertNotIn("up -d", self.trace.read_text())

    def test_personal_mode_runs_without_portless(self):
        (self.bin / "portless").unlink()
        self.assertEqual(self.run_cli("up", "--personal", "http://localhost:59238").returncode, 0)

    def test_personal_mode_refuses_other_origins(self):
        for url in [
            "http://127.0.0.1:5173",
            "https://localhost:5173",
            "http://localhost",
            "http://localhost:0",
            "http://localhost:65536",
            "http://localhost:5173/path",
        ]:
            with self.subTest(url=url):
                self.assertNotEqual(self.run_cli("up", "--personal", url).returncode, 0)

    def test_refuses_mode_flip_without_destroy(self):
        self.assertEqual(self.run_cli("up").returncode, 0)
        self.assertNotEqual(self.run_cli("up", "--real-x").returncode, 0)

    def test_refuses_real_mode_over_an_older_emulated_stack(self):
        state = self.root / ".sdlc/dev-stack"
        state.mkdir(parents=True)
        (state / "e2e-target").write_text("legacy-emulated-target\n")
        self.assertNotEqual(self.run_cli("up", "--real-x", "http://127.0.0.1:59237").returncode, 0)

    def test_rejects_non_loopback_origins_and_extra_arguments(self):
        for url in [
            "https://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:0",
            "http://127.0.0.1:65536",
            "http://127.0.0.1:5173/path",
        ]:
            with self.subTest(url=url):
                self.assertNotEqual(self.run_cli("up", "--real-x", url).returncode, 0)
        self.assertNotEqual(self.run_cli("up", "--typo").returncode, 0)

    def test_down_works_without_portless_installed(self):
        (self.bin / "portless").unlink()
        self.env["PATH"] = f"{self.bin}:/usr/bin:/bin"
        self.assertEqual(self.run_cli("down").returncode, 0)

    def test_occupied_callback_port_is_not_taken(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            result = self.run_cli("up", "--real-x", f"http://127.0.0.1:{listener.getsockname()[1]}")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("up -d", self.trace.read_text() if self.trace.exists() else "")


@unittest.skipUnless(shutil.which("docker"), "Docker Compose is needed to render its configuration")
class ComposeSettingsTests(unittest.TestCase):
    def test_personal_compose_uses_real_providers_without_emulator_services(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["compose.dev.yml", "compose.personal.yml"]:
                shutil.copy(SOURCE / name, root / name)
            (root / ".env").write_text(
                "POSTGRES_PASSWORD=test\nX_CLIENT_ID=personal-x\nX_CLIENT_SECRET=personal-secret\n"
                "TRIAL_IDENTITY_KEYS=personal-ring\nSTRIPE_SECRET_KEY=sk_test_personal\n"
                "STRIPE_PUBLISHABLE_KEY=pk_test_personal\nSTRIPE_WEBHOOK_SECRET=whsec_personal\n"
                'BILLING_PLAN_KEYS=["monthly"]\nCOUPON_IDENTITY_KEYS=personal-coupon-ring\n'
            )
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-p",
                    "isolated-personal",
                    "-f",
                    "compose.dev.yml",
                    "-f",
                    "compose.personal.yml",
                    "config",
                    "--format",
                    "json",
                ],
                cwd=root,
                env={
                    **os.environ,
                    "DEV_PUBLIC_URL": "http://localhost:5173",
                    "DEV_PUBLIC_PORT": "5173",
                    "PUBLISHER_ENABLED": "false",
                    "SMTP_HOST": "",
                    "EMAIL_FROM": "",
                    "POSTHOG_ENABLED": "false",
                    "DEV_API_BIND": "127.0.0.1:",
                    "DEV_DB_BIND": "127.0.0.1:",
                },
                text=True,
                capture_output=True,
                check=True,
            )
            config = json.loads(result.stdout)
            services = config["services"]
            self.assertEqual(set(services), {"db", "backend", "publisher", "frontend"})
            for name in ["backend", "publisher"]:
                settings = services[name]["environment"]
                self.assertEqual(settings["PUBLIC_URL"], "http://localhost:5173")
                self.assertEqual(settings["X_LOCAL_CALLBACK_RELAY"], "true")
                self.assertEqual(settings["X_CLIENT_ID"], "personal-x")
                self.assertEqual(settings["STRIPE_SECRET_KEY"], "sk_test_personal")
                self.assertEqual(settings["TRIAL_IDENTITY_KEYS"], "personal-ring")
                self.assertEqual(settings["COUPON_IDENTITY_KEYS"], "personal-coupon-ring")
                self.assertEqual(settings["PUBLISHER_ENABLED"], "false")
                self.assertNotIn("X_API_URL", settings)
                self.assertNotIn("STRIPE_API_URL", settings)
            self.assertEqual(
                services["frontend"]["environment"]["DEV_PUBLIC_URL"], "http://localhost:5173"
            )
            self.assertEqual(
                {p["host_ip"] for p in services["frontend"]["ports"]}, {"127.0.0.1", "::1"}
            )
            self.assertTrue(
                all(v["name"].startswith("isolated-personal_") for v in config["volumes"].values())
            )

    def test_only_main_app_gets_real_x_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in [
                "compose.dev.yml",
                "compose.emulators.yml",
                "compose.real-x.yml",
            ]:
                shutil.copy(SOURCE / name, root / name)
            (root / ".env").write_text(
                "POSTGRES_PASSWORD=test\nX_CLIENT_ID=synthetic-client\nX_CLIENT_SECRET=synthetic-secret\nTRIAL_IDENTITY_KEYS=synthetic-ring\n"
            )
            command = [
                "docker",
                "compose",
                "-f",
                "compose.dev.yml",
                "-f",
                "compose.emulators.yml",
            ]
            env = {
                **os.environ,
                "X_API_URL": "http://emulate:4002",
                "X_AUTHORIZE_URL": "http://fake/i/oauth2/authorize",
                "PUBLISHER_ENABLED": "false",
                "SMTP_HOST": "",
                "EMAIL_FROM": "",
                "POSTHOG_ENABLED": "false",
                "DEV_PUBLIC_URL": "http://127.0.0.1:5173",
                "DEV_WEB_BIND": "127.0.0.1:5173",
                "X_CLIENT_ID": "synthetic-client",
                "X_CLIENT_SECRET": "synthetic-secret",
                "TRIAL_IDENTITY_KEYS": "synthetic-ring",
            }
            for real in [False, True]:
                with self.subTest(real=real):
                    extra = ["-f", "compose.real-x.yml"] if real else []
                    result = subprocess.run(
                        command + extra + ["--profile", "emulators", "config", "--format", "json"],
                        cwd=root,
                        env=env,
                        text=True,
                        capture_output=True,
                        check=True,
                    )
                    services = json.loads(result.stdout)["services"]
                    for name in ["backend", "publisher"]:
                        settings = services[name]["environment"]
                        self.assertEqual(
                            settings["X_CLIENT_ID"],
                            "synthetic-client" if real else "pumpkit-dev-x",
                        )
                        self.assertEqual(
                            settings["X_CLIENT_SECRET"],
                            "synthetic-secret" if real else "pumpkit-dev-x-secret",
                        )
                        self.assertEqual(
                            settings["X_API_URL"], "" if real else "http://emulate:4002"
                        )
                        self.assertEqual(
                            settings["X_AUTHORIZE_URL"],
                            "" if real else "http://fake/i/oauth2/authorize",
                        )
                        self.assertEqual(settings["PUBLIC_URL"], "http://127.0.0.1:5173")
                        self.assertEqual(settings["PUBLISHER_ENABLED"], "false")
                        self.assertEqual(settings["POSTHOG_ENABLED"], "false")
                        self.assertEqual(settings["SMTP_HOST"], "")
                        self.assertEqual(settings["EMAIL_FROM"], "")
                        self.assertEqual(settings["TRIAL_IDENTITY_KEYS"] == "synthetic-ring", real)
                    staged = services["staged-x"]["environment"]
                    self.assertEqual(staged["X_CLIENT_ID"], "pumpkit-dev-x")
                    self.assertEqual(staged["X_API_URL"], "http://emulate:4002")
                    self.assertNotIn("X_CLIENT_SECRET", services["emulate"]["environment"])
                    self.assertEqual(services["frontend"]["ports"][0]["host_ip"], "127.0.0.1")
                    self.assertEqual(services["frontend"]["ports"][0]["published"], "5173")


if __name__ == "__main__":
    unittest.main()
