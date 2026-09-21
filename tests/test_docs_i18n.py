"""Keep translated documentation structurally aligned with the English source."""

from collections import Counter
from pathlib import Path
import hashlib
import json
import os
import re
import unittest
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ("ko", "ja", "zh-CN")
FENCE_RE = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+[\"'][^)]*[\"'])?\)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
EXPLICIT_ANCHOR_RE = re.compile(r'<a\s+(?:name|id)=["\']([^"\']+)["\']\s*></a>', re.IGNORECASE)
GITHUB_MAIN_PREFIX = "/abruption/session-peer/blob/main/"


def canonical_documents():
    documents = [Path("README.md"), Path("RELEASING.md"), Path("SECURITY.md")]
    documents.extend(
        sorted(
            path.relative_to(ROOT)
            for path in (ROOT / "docs").rglob("*.md")
            if not any(part in LANGUAGES for part in path.relative_to(ROOT).parts)
        )
    )
    documents.append(Path("plugins/session-peer/README.md"))
    return documents


def localized_path(source, language):
    if source.parent == Path("."):
        return source.with_name("{}.{}{}".format(source.stem, language, source.suffix))
    if source.parts[0] == "docs":
        return Path("docs") / language / Path(*source.parts[1:])
    return source.with_name("{}.{}{}".format(source.stem, language, source.suffix))


def github_slug(value):
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"[`*_~]", "", value).strip().lower()
    value = "".join(char for char in value if char.isalnum() or char in " -_")
    return re.sub(r"\s+", "-", value)


def anchors(text):
    found = set(EXPLICIT_ANCHOR_RE.findall(text))
    counts = Counter()
    for heading in HEADING_RE.findall(text):
        base = github_slug(heading)
        suffix = counts[base]
        counts[base] += 1
        found.add(base if suffix == 0 else "{}-{}".format(base, suffix))
    return found


class DocumentationTranslationsTest(unittest.TestCase):
    maxDiff = None

    def test_every_canonical_document_has_each_translation(self):
        sources = canonical_documents()
        self.assertEqual(31, len(sources), "Update the translation manifest for new canonical docs")
        canonical_docs = {
            path.relative_to(ROOT / "docs")
            for path in (ROOT / "docs").rglob("*.md")
            if not any(part in LANGUAGES for part in path.relative_to(ROOT).parts)
        }
        for language in LANGUAGES:
            expected = {localized_path(source, language) for source in sources}
            missing = sorted(str(path) for path in expected if not (ROOT / path).is_file())
            self.assertEqual([], missing, "{} translations are missing".format(language))
            actual_docs = {
                path.relative_to(ROOT / "docs" / language)
                for path in (ROOT / "docs" / language).rglob("*.md")
            }
            self.assertEqual(canonical_docs, actual_docs)

    def test_commands_and_code_examples_are_byte_exact(self):
        for source in canonical_documents():
            source_text = (ROOT / source).read_text(encoding="utf-8")
            source_fences = FENCE_RE.findall(source_text)
            source_inline = Counter(INLINE_CODE_RE.findall(source_text))
            for language in LANGUAGES:
                translated = localized_path(source, language)
                translated_text = (ROOT / translated).read_text(encoding="utf-8")
                if source != Path("README.md"):
                    with self.subTest(source=str(source), language=language, kind="fences"):
                        self.assertEqual(source_fences, FENCE_RE.findall(translated_text))
                with self.subTest(source=str(source), language=language, kind="inline"):
                    self.assertEqual(source_inline, Counter(INLINE_CODE_RE.findall(translated_text)))

    def test_heading_and_link_counts_stay_aligned(self):
        structure_patterns = (
            r"^\s*[-*+] ",
            r"^\s*\d+\. ",
            r"^\|.*\|\s*$",
            r"^> ?",
        )
        for source in canonical_documents():
            source_text = (ROOT / source).read_text(encoding="utf-8")
            heading_count = len(HEADING_RE.findall(source_text))
            link_count = len(LINK_RE.findall(source_text))
            source_structure = tuple(len(re.findall(pattern, source_text, re.MULTILINE)) for pattern in structure_patterns)
            for language in LANGUAGES:
                translated_text = (ROOT / localized_path(source, language)).read_text(encoding="utf-8")
                translated_structure = tuple(len(re.findall(pattern, translated_text, re.MULTILINE)) for pattern in structure_patterns)
                with self.subTest(source=str(source), language=language):
                    self.assertEqual(heading_count, len(HEADING_RE.findall(translated_text)))
                    self.assertEqual(link_count, len(LINK_RE.findall(translated_text)))
                    self.assertEqual(source_structure, translated_structure)

    def test_canonical_source_manifest_is_current(self):
        manifest = json.loads((ROOT / "docs/i18n-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(1, manifest["schemaVersion"])
        self.assertEqual("en", manifest["canonicalLocale"])
        self.assertEqual(list(LANGUAGES), manifest["translatedLocales"])
        expected = {
            source.as_posix(): hashlib.sha256(
                (ROOT / source).read_text(encoding="utf-8").encode("utf-8")
            ).hexdigest()
            for source in canonical_documents()
        }
        self.assertEqual(expected, manifest["sources"])

    def test_repository_links_resolve(self):
        documents = list(canonical_documents())
        for source in canonical_documents():
            documents.extend(localized_path(source, language) for language in LANGUAGES)

        for document in documents:
            text = (ROOT / document).read_text(encoding="utf-8")
            for target in LINK_RE.findall(text):
                parsed = urlparse(target)
                destination = None
                if not parsed.scheme and not parsed.netloc:
                    if not parsed.path:
                        destination = document
                    else:
                        destination = Path(os.path.normpath((document.parent / unquote(parsed.path)).as_posix()))
                elif parsed.netloc == "github.com" and parsed.path.startswith(GITHUB_MAIN_PREFIX):
                    destination = Path(unquote(parsed.path[len(GITHUB_MAIN_PREFIX):]))
                if destination is None:
                    continue
                with self.subTest(document=str(document), target=target):
                    self.assertTrue((ROOT / destination).is_file(), "missing {}".format(destination))
                    if parsed.fragment:
                        destination_text = (ROOT / destination).read_text(encoding="utf-8")
                        self.assertIn(unquote(parsed.fragment), anchors(destination_text))


if __name__ == "__main__":
    unittest.main()
