"""Validate the shared interface catalogs before building release packages."""

from __future__ import annotations

import ast
import json
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = re.compile(r"\{\w+\}")
CONSTANTS = (
    "CaseQuarry", "Anthropic", "OpenAI", "ChatGPT", "Gemini", "Grok", "Claude",
    "xAI", "Ollama", "SHA-256", "CSV/DAT/OPT", "UTF-8", "TOTP", "UTC",
    "127.0.0.1", "[::1]", "OLLAMA_NO_CLOUD=1",
)
CONTEXT_MESSAGES = {"Open (status)": "Open"}


class ConnectionMessages(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        message = dict(attrs).get("data-i18n")
        if message:
            self.messages.append(message)


def constants(message: str) -> Counter[str]:
    result = Counter({token: message.count(token) for token in CONSTANTS if token in message})
    for address in re.findall(r"https?://[A-Za-z0-9.\-:/\[\]]*", message):
        result[address.rstrip(".,;")] += 1
    return result


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate message: {key!r}")
        result[key] = value
    return result


def main() -> int:
    tree = ast.parse((ROOT / "apps/api/casequarry/languages.py").read_text(encoding="utf8"))
    declaration = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "Language" for target in node.targets)
    )
    languages = set(ast.literal_eval(declaration.value.slice))
    shared = (ROOT / "packages/i18n/index.ts").read_text(encoding="utf8")
    interface_languages = set(re.findall(r'code:\s*"([\w-]+)"', shared))
    directory = ROOT / "packages/i18n/catalogs"
    files = {path.stem: path for path in directory.glob("*.json")}
    errors = []
    if set(files) != languages or interface_languages != languages:
        errors.append("API, interface and catalog language codes must match exactly")
    catalogs = {}
    for language, path in sorted(files.items()):
        try:
            catalog = json.loads(path.read_text(encoding="utf8"), object_pairs_hook=unique_object)
            if not isinstance(catalog, dict):
                raise ValueError("catalog must be a flat object")
            catalogs[language] = catalog
        except (ValueError, UnicodeError) as error:
            errors.append(f"{language}: {error}")
    english = catalogs.get("en", {})
    if not english:
        errors.append("English catalog is empty or unavailable")
    desktop = ConnectionMessages()
    desktop.feed((ROOT / "apps/desktop/index.html").read_text(encoding="utf8"))
    desktop_source = (ROOT / "apps/desktop/src/main.ts").read_text(encoding="utf8")
    desktop.messages.extend(
        json.loads(literal) for literal in re.findall(
            r'\b(?:t|translate|setStatus)\(\s*("(?:[^"\\]|\\.)*")', desktop_source,
        )
    )
    for message in sorted(set(desktop.messages) - set(english) - {""}):
        errors.append(f"desktop: missing authored message {message!r}")
    for language, catalog in catalogs.items():
        missing, extra = set(english) - set(catalog), set(catalog) - set(english)
        if missing or extra:
            errors.append(f"{language}: {len(missing)} missing and {len(extra)} extra messages")
        for key, value in catalog.items():
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{language}: empty/non-string message {key!r}")
            elif "\ufffd" in value or "\x00" in value or any(
                0xD800 <= ord(character) <= 0xDFFF for character in value
            ):
                errors.append(f"{language}: invalid character in {key!r}")
            elif Counter(PLACEHOLDER.findall(key)) != Counter(PLACEHOLDER.findall(value)):
                errors.append(f"{language}: changed placeholders in {key!r}")
            elif constants(english.get(key, key)) != constants(value):
                errors.append(f"{language}: changed product/technical constant in {key!r}")
            elif language == "en" and value != CONTEXT_MESSAGES.get(key, key):
                errors.append(f"en: canonical message differs from its key: {key!r}")
    if errors:
        for error in errors:
            print(error)
        print(f"Catalog validation failed: {len(errors)} issue(s).")
        return 1
    print(f"Validated {len(catalogs)} interface languages and {len(english)} messages per language.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
