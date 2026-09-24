import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/privacy-check.py"


def check(repo):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--staged"], cwd=repo, text=True, capture_output=True
    )


def test_guard_reads_index_not_unstaged_clean_file(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    path = tmp_path / "settings.txt"
    secret = "ghp_" + "A" * 36
    path.write_text(secret)
    subprocess.run(["git", "add", "settings.txt"], cwd=tmp_path, check=True)
    path.write_text("clean working tree copy")
    result = check(tmp_path)
    assert result.returncode == 1
    assert secret not in result.stdout + result.stderr
    assert "settings.txt" in result.stdout


def test_guard_rejects_forced_database_and_accepts_empty_template(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".env.example").write_text("BINANCE_API_KEY=\nBINANCE_API_SECRET=\n")
    subprocess.run(["git", "add", ".env.example"], cwd=tmp_path, check=True)
    assert check(tmp_path).returncode == 0
    (tmp_path / "copied.sqlite3").write_bytes(b"example")
    subprocess.run(["git", "add", "-f", "copied.sqlite3"], cwd=tmp_path, check=True)
    assert check(tmp_path).returncode == 1


def test_ignore_rules_cover_copies_and_keep_templates():
    root = SCRIPT.parents[1]
    private = [
        ".env.local",
        "nested/.env.production",
        "copied.db-wal",
        "nested/a.sqlite3",
        "exports/trades.csv",
        "backups/account.zip",
        "bot.log",
    ]
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        cwd=root,
        input="\n".join(private) + "\n",
        text=True,
        capture_output=True,
    )
    assert set(result.stdout.splitlines()) == set(private)
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", ".env.example"], cwd=root, capture_output=True
    )
    assert result.returncode == 1
