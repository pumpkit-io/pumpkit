import errno
import os
import pty
import select
import signal
import subprocess
import termios
import time
from pathlib import Path


def test_interactive_setup_names_both_x_fields_and_hides_their_input(tmp_path):
    script = Path(__file__).resolve().parents[3] / "scripts" / "setup.sh"
    target = tmp_path / ".env"
    master, slave = pty.openpty()
    process = subprocess.Popen(
        ["sh", str(script), "--env-file", str(target)],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env={
            "PATH": os.environ["PATH"],
            "PUBLIC_URL": "http://localhost:8080",
            "LLM_API_KEY": "interactive-llm",
            "TWITTERAPI_IO_API_KEY": "interactive-reader",
        },
        start_new_session=True,
    )
    os.close(slave)
    transcript = b""

    def read_prompt(name: str) -> None:
        nonlocal transcript
        deadline = time.monotonic() + 10
        while (name + ",").encode() not in transcript:
            remaining = deadline - time.monotonic()
            assert remaining > 0, f"Setup did not label the {name} prompt"
            readable, _, _ = select.select([master], [], [], remaining)
            assert readable, f"Setup did not label the {name} prompt"
            transcript += os.read(master, 4096)
        while termios.tcgetattr(master)[3] & termios.ECHO:
            assert time.monotonic() < deadline, f"Setup did not hide {name} input"
            time.sleep(0.01)

    try:
        read_prompt("X_CLIENT_ID")
        os.write(master, b"interactive-x-client\n")
        read_prompt("X_CLIENT_SECRET")
        os.write(master, b"interactive-x-secret\n")
        assert process.wait(timeout=10) == 0
        while True:
            try:
                chunk = os.read(master, 4096)
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            transcript += chunk
        assert b"interactive-x-client" not in transcript
        assert b"interactive-x-secret" not in transcript
        written = target.read_text()
        assert "X_CLIENT_ID=interactive-x-client" in written
        assert "X_CLIENT_SECRET=interactive-x-secret" in written
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
        os.close(master)
