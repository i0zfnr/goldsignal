from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [*ROOT.glob("src/**/*"), *ROOT.glob("public/**/*"), ROOT / "index.html"]
SUFFIXES = {".tsx", ".ts", ".css", ".js", ".html", ".json", ".webmanifest"}
DOUBLE_ENCODED = ("\u00c2", "\u00e2", "\ufffd")


def test_sources_have_no_double_encoded_text():
    offenders = []
    for path in SOURCES:
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            if any(marker in line for marker in DOUBLE_ENCODED):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == [], f"Double-encoded text found: {offenders}"
