"""Exercise development startup boundaries without contacting providers."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2]


class DevStackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.main = base / "main"
        self.root = base / "worktree"
        subprocess.run(["git", "init", "-q", str(self.main)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.main),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.org",
                "commit",
                "--allow-empty",
                "-qm",
                "seed",
            ],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.main), "worktree", "add", "-qb", "feat/test", str(self.root)],
            check=True,
        )
        (self.root / "scripts").mkdir()
        shutil.copy(SOURCE / "scripts/dev-stack", self.root / "scripts/dev-stack")
        self.bin = base / "bin"
        self.bin.mkdir()
        self.trace = base / "trace"
        for name, body in {
            "portless": 'printf "portless %s\\n" "$*" >> "$TRACE"; case "$1" in get) echo "http://test.$2.localhost:1355";; esac',
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

    def run_cli(self, *args, cwd=None):
        return subprocess.run(
            [str(self.root / "scripts/dev-stack"), *args],
            cwd=cwd or self.root,
            env=self.env,
            text=True,
            capture_output=True,
        )

    def test_emulated_lifecycle_keeps_generated_url_and_isolated_project(self):
        result = self.run_cli("up")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "http://test.pumpkit.localhost:1355")
        self.assertEqual(self.run_cli("url").stdout, result.stdout)
        self.assertEqual(self.run_cli("status").stdout.strip(), "running")
        self.assertEqual(self.run_cli("logs", "backend").returncode, 0)
        target = (self.root / ".sdlc/dev-stack/e2e-target").read_text()
        self.assertIn("pumpkit-dev-test", target)
        self.assertIn("compose.emulators.yml", self.trace.read_text())
        self.assertNotIn(" -p pumpkit-dev ", self.trace.read_text())
        self.assertEqual(self.run_cli("down").returncode, 0)
        self.assertNotIn("down -v", self.trace.read_text())
        self.assertEqual(self.run_cli("destroy").returncode, 0)
        self.assertFalse((self.root / ".sdlc/dev-stack").exists())

    def test_retired_flags_fail_before_touching_routes_or_containers(self):
        for flag in ["--personal", "--real-x"]:
            with self.subTest(flag=flag):
                result = self.run_cli("up", flag)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("docker compose -f compose.dev.yml", result.stderr)
                self.assertFalse(self.trace.exists())

    def test_saved_retired_modes_leave_state_and_volumes_untouched(self):
        state = self.root / ".sdlc/dev-stack"
        state.mkdir(parents=True)
        for mode in ["personal", "real-x"]:
            (state / "mode").write_text(mode + "\n")
            (state / "public-url").write_text("http://localhost:5173\n")
            for command in ["up", "down", "destroy", "url", "status", "logs", "staged-x-url"]:
                with self.subTest(mode=mode, command=command):
                    result = self.run_cli(command)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("retired", result.stderr)
                    self.assertEqual((state / "mode").read_text(), mode + "\n")
                    self.assertFalse(self.trace.exists())

    def test_agent_launcher_refuses_main_checkout(self):
        result = self.run_cli("up", cwd=self.main)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("worktree", result.stderr)
        self.assertFalse(self.trace.exists())

    def test_down_works_without_portless_installed(self):
        (self.bin / "portless").unlink()
        self.env["PATH"] = f"{self.bin}:/usr/bin:/bin"
        self.assertEqual(self.run_cli("down").returncode, 0)


@unittest.skipUnless(shutil.which("docker"), "Docker Compose is needed to render its configuration")
class ComposeSettingsTests(unittest.TestCase):
    def render(self, emulated=False, overrides=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["compose.dev.yml", "compose.emulators.yml"]:
                shutil.copy(SOURCE / name, root / name)
            (root / ".env").write_text(
                "POSTGRES_PASSWORD=test\nX_CLIENT_ID=personal-x\nX_CLIENT_SECRET=personal-secret\n"
                "TRIAL_IDENTITY_KEYS=personal-ring\nSTRIPE_SECRET_KEY=sk_test_personal\n"
                "STRIPE_PUBLISHABLE_KEY=pk_test_personal\nSTRIPE_WEBHOOK_SECRET=whsec_personal\n"
                'BILLING_PLAN_KEYS=["monthly"]\nCOUPON_IDENTITY_KEYS=personal-coupon-ring\n'
            )
            env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith(
                    (
                        "DEV_",
                        "COMPOSE_",
                        "PUBLISHER_",
                        "X_",
                        "STRIPE_",
                        "POSTHOG_",
                        "SMTP_",
                        "EMAIL_",
                    )
                )
            }
            command = ["docker", "compose", "-f", "compose.dev.yml"]
            if emulated:
                command += [
                    "-p",
                    "pumpkit-dev-example",
                    "-f",
                    "compose.emulators.yml",
                    "--profile",
                    "emulators",
                ]
                env.update(
                    {
                        "DEV_PUBLIC_URL": "http://example.pumpkit.localhost:1355",
                        "DEV_STAGED_X_URL": "http://example.staged-x.pumpkit.localhost:1355",
                        "DEV_WEB_BIND": "127.0.0.1:53123",
                        "DEV_API_BIND": "127.0.0.1:",
                        "DEV_DB_BIND": "127.0.0.1:",
                        "X_API_URL": "http://emulate:4002",
                        "X_AUTHORIZE_URL": "http://example.pumpkit-x.emulate.pumpkit.localhost:1355/i/oauth2/authorize",
                        "STRIPE_API_URL": "http://emulate:4001",
                        "STRIPE_SECRET_KEY": "sk_test_dev",
                        "STRIPE_PUBLISHABLE_KEY": "pk_test_dev",
                        "STRIPE_WEBHOOK_SECRET": "whsec_dev",
                        "PUBLISHER_ENABLED": "false",
                        "SMTP_HOST": "",
                        "EMAIL_FROM": "",
                        "POSTHOG_ENABLED": "false",
                    }
                )
            env.update(overrides or {})
            result = subprocess.run(
                command + ["config", "--format", "json"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            return json.loads(result.stdout)

    def test_plain_compose_defaults_to_personal_localhost_without_dev_variables(self):
        config = self.render()
        services = config["services"]
        self.assertEqual(config["name"], "pumpkit-dev")
        self.assertEqual(set(services), {"db", "backend", "publisher", "frontend"})
        for name in ["backend", "publisher"]:
            settings = services[name]["environment"]
            self.assertEqual(settings["PUBLIC_URL"], "http://localhost:5173")
            self.assertEqual(settings["X_LOCAL_CALLBACK_RELAY"], "true")
            self.assertEqual(settings["X_CLIENT_ID"], "personal-x")
            self.assertEqual(settings["STRIPE_SECRET_KEY"], "sk_test_personal")
            self.assertEqual(settings["TRIAL_IDENTITY_KEYS"], "personal-ring")
            self.assertEqual(settings["PUBLISHER_ENABLED"], "true")
            self.assertNotIn("X_API_URL", settings)
        frontend = services["frontend"]
        self.assertEqual(frontend["environment"]["X_LOCAL_CALLBACK_RELAY"], "true")
        self.assertEqual(frontend["environment"]["DEV_PUBLIC_URL"], "http://localhost:5173")
        self.assertEqual({p["host_ip"] for p in frontend["ports"]}, {"127.0.0.1", "::1"})
        self.assertEqual({p["published"] for p in frontend["ports"]}, {"5173"})
        self.assertEqual(
            {v["name"] for v in config["volumes"].values()},
            {"pumpkit-dev_postgres_data", "pumpkit-dev_media_data"},
        )

    def test_personal_port_and_publishing_can_be_overridden(self):
        services = self.render(overrides={"DEV_PUBLIC_PORT": "5175", "PUBLISHER_ENABLED": "false"})[
            "services"
        ]
        for name in ["backend", "publisher"]:
            self.assertEqual(services[name]["environment"]["PUBLIC_URL"], "http://localhost:5175")
            self.assertEqual(services[name]["environment"]["PUBLISHER_ENABLED"], "false")
        self.assertEqual(
            services["frontend"]["environment"]["DEV_PUBLIC_URL"], "http://localhost:5175"
        )
        self.assertEqual({p["published"] for p in services["frontend"]["ports"]}, {"5175"})

    def test_emulators_override_personal_settings_in_every_service(self):
        config = self.render(emulated=True)
        services = config["services"]
        for name in ["backend", "publisher", "staged-x"]:
            settings = services[name]["environment"]
            self.assertEqual(settings["X_LOCAL_CALLBACK_RELAY"], "false")
            self.assertEqual(settings["X_CLIENT_ID"], "pumpkit-dev-x")
            self.assertEqual(settings["X_CLIENT_SECRET"], "pumpkit-dev-x-secret")
            self.assertEqual(settings["X_API_URL"], "http://emulate:4002")
            self.assertEqual(settings["STRIPE_SECRET_KEY"], "sk_test_dev")
            self.assertEqual(settings["PUBLISHER_ENABLED"], "false")
            self.assertEqual(settings["SMTP_HOST"], "")
            self.assertEqual(settings["POSTHOG_ENABLED"], "false")
            self.assertNotEqual(settings["TRIAL_IDENTITY_KEYS"], "personal-ring")
        self.assertEqual(
            services["backend"]["environment"]["PUBLIC_URL"],
            "http://example.pumpkit.localhost:1355",
        )
        self.assertEqual(
            services["staged-x"]["environment"]["PUBLIC_URL"],
            "http://example.staged-x.pumpkit.localhost:1355",
        )
        self.assertEqual(services["frontend"]["environment"]["X_LOCAL_CALLBACK_RELAY"], "false")
        self.assertEqual(len(services["frontend"]["ports"]), 1)
        self.assertEqual(services["frontend"]["ports"][0]["published"], "53123")
        self.assertTrue(
            all(v["name"].startswith("pumpkit-dev-example_") for v in config["volumes"].values())
        )


if __name__ == "__main__":
    unittest.main()
