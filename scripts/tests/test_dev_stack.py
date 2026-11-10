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
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.trace = self.root / "trace"
        for name, body in {
            "portless": 'case "$1" in get) echo "http://$2.localhost:1355";; esac',
            "curl": 'if [[ "$*" == *http_code* ]]; then echo 200; fi',
            "docker": 'printf "%s\\n" "$*" >> "$TRACE"; case " $* " in *" port "*) echo 127.0.0.1:54123;; *" ps "*) echo container;; esac',
        }.items():
            path = self.bin / name
            path.write_text("#!/usr/bin/env bash\n" + body + "\n")
            path.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "TRACE": str(self.trace),
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

    def test_refuses_mode_flip_without_destroy(self):
        self.assertEqual(self.run_cli("up").returncode, 0)
        self.assertNotEqual(self.run_cli("up", "--real-x").returncode, 0)

    def test_refuses_real_mode_over_an_older_emulated_stack(self):
        state = self.root / ".sdlc/dev-stack"
        state.mkdir(parents=True)
        (state / "e2e-target").write_text("legacy-emulated-target\n")
        self.assertNotEqual(
            self.run_cli("up", "--real-x", "http://127.0.0.1:59237").returncode, 0
        )

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
            result = self.run_cli(
                "up", "--real-x", f"http://127.0.0.1:{listener.getsockname()[1]}"
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.trace.exists())


@unittest.skipUnless(
    shutil.which("docker"), "Docker Compose is needed to render its configuration"
)
class ComposeSettingsTests(unittest.TestCase):
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
                        command
                        + extra
                        + ["--profile", "emulators", "config", "--format", "json"],
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
                        self.assertEqual(
                            settings["PUBLIC_URL"], "http://127.0.0.1:5173"
                        )
                        self.assertEqual(settings["PUBLISHER_ENABLED"], "false")
                        self.assertEqual(settings["POSTHOG_ENABLED"], "false")
                        self.assertEqual(settings["SMTP_HOST"], "")
                        self.assertEqual(settings["EMAIL_FROM"], "")
                        self.assertEqual(
                            settings["TRIAL_IDENTITY_KEYS"] == "synthetic-ring", real
                        )
                    staged = services["staged-x"]["environment"]
                    self.assertEqual(staged["X_CLIENT_ID"], "pumpkit-dev-x")
                    self.assertEqual(staged["X_API_URL"], "http://emulate:4002")
                    self.assertNotIn(
                        "X_CLIENT_SECRET", services["emulate"]["environment"]
                    )
                    self.assertEqual(
                        services["frontend"]["ports"][0]["host_ip"], "127.0.0.1"
                    )
                    self.assertEqual(
                        services["frontend"]["ports"][0]["published"], "5173"
                    )


if __name__ == "__main__":
    unittest.main()
