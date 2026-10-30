"""Bounded metadata only; no skill instruction execution or manager changes."""
import errno
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import session_peer as peer


# Exact frontmatter from the released v0.3.2 and v0.3.3 skills. Bodies below
# are synthetic padding at the observed document sizes, not copied instructions.
RELEASED_HEADER = '''---
name: session-peer
description: Send user-requested messages to Claude Code, Codex, or a live registered Antigravity TUI on this machine, an SSH host, or a paired device using session-peer. Use for cross-session handoffs and notifications when the available native tools do not cover the requested target.
allowed-tools: Bash, Read
metadata:
  version: "{version}"
  runtime-min-version: "0.9.1"
  runtime-full-version: "1.0.1"
---
'''
LIMIT = 16384
UNKNOWN = {"version": None, "runtimeMinVersion": None}


class SkillFrontmatter(unittest.TestCase):
    def test_published_v041_snapshot_is_exact_and_metadata_remains_readable(self):
        path = Path(__file__).resolve().parents[2] / "skills/session-peer/SKILL.md"
        content = path.read_bytes()
        self.assertEqual(27126, len(content))
        self.assertEqual("fdf5697c04f4a37194986622afb3a7966bb02631c128cf18a323e3fbe5ae90ed",
                         hashlib.sha256(content).hexdigest())
        self.assertGreater(len(content), LIMIT)
        self.assertEqual({"version": "0.4.1", "runtimeMinVersion": "0.9.1"},
                         peer.installed_skill_metadata(path))

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="skill-metadata-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "SKILL.md"

    def write(self, data):
        self.path.write_bytes(data)
        return self.path

    def metadata(self, data):
        return peer.installed_skill_metadata(self.write(data))

    def test_released_headers_survive_their_real_document_sizes(self):
        for version, size in (("0.3.2", 16459), ("0.3.3", 18824)):
            with self.subTest(version=version):
                header = RELEASED_HEADER.format(version=version).encode("utf-8")
                content = header + b"\n# Synthetic body\n" + b"x" * (size - len(header) - 18)
                self.assertEqual(len(content), size)
                self.assertEqual(self.metadata(content), {"version": version, "runtimeMinVersion": "0.9.1"})

    def test_large_invalid_or_split_utf8_body_is_not_decoded_as_metadata(self):
        header = RELEASED_HEADER.format(version="0.3.3").encode()
        body = b"x" * (LIMIT - len(header)) + "한".encode() + b"\xff" * 100000
        self.assertEqual(self.metadata(header + body), {"version": "0.3.3", "runtimeMinVersion": "0.9.1"})

    def test_valid_utf8_header_is_decoded_with_a_byte_not_character_limit(self):
        prefix = '---\nname: 한글\nmetadata:\n  version: "0.3.3"\n# '
        self.assertEqual(self.metadata((prefix + '\n---\n').encode("utf-8")),
                         {"version": "0.3.3", "runtimeMinVersion": None})
        text = prefix + "한" * (LIMIT // 3) + "\n---\n"
        self.assertLess(len(text), LIMIT)
        self.assertGreater(len(text.encode("utf-8")), LIMIT)
        self.assertEqual(self.metadata(text.encode("utf-8")), UNKNOWN)

    def test_exact_budget_includes_both_delimiters_and_line_endings(self):
        for eol in (b"\n", b"\r\n", b"\r"):
            for final in (True, False):
                with self.subTest(eol=eol, final_newline=final):
                    prefix = eol.join([b"---", b"metadata:", b'  version: "0.3.3"', b"# "])
                    suffix = eol + b"---" + (eol if final else b"")
                    header = prefix + b"x" * (LIMIT - len(prefix) - len(suffix)) + suffix
                    self.assertEqual(len(header), LIMIT)
                    self.assertEqual(self.metadata(header), {"version": "0.3.3", "runtimeMinVersion": None})
                    self.assertEqual(self.metadata(prefix + b"x" + header[len(prefix):]), UNKNOWN)

    def test_closing_delimiter_at_read_limit_is_not_assumed_to_be_eof(self):
        prefix = b'---\nmetadata:\n  version: "0.3.3"\n# '
        header = prefix + b"x" * (LIMIT - len(prefix) - 4) + b"\n---"
        self.assertEqual(len(header), LIMIT)
        self.assertEqual(self.metadata(header + b"not-a-delimiter\n"), UNKNOWN)
        self.assertEqual(self.metadata(header + b"\n"), UNKNOWN)

    def test_missing_malformed_truncated_and_bad_utf8_header_stay_unknown(self):
        self.assertEqual(peer.installed_skill_metadata(self.path), UNKNOWN)
        for data in (b"", b"not frontmatter", b"---\nmetadata:\n  version: 0.3.3\n",
                     b"\xef\xbb\xbf---\nmetadata:\n  version: 0.3.3\n---\n",
                     b"---\nname: fixture\n---\n", b"---\n\xff\nmetadata:\n  version: 0.3.3\n---\n",
                     b"---\nmetadata: !!python/object/apply:fixture\n---\n"):
            with self.subTest(case=len(data)):
                self.assertEqual(self.metadata(data), UNKNOWN)

    def test_existing_field_selection_and_partial_unknown_semantics_are_preserved(self):
        data = b'---\nmetadata:\n  version: "bad"\n  runtime-min-version: "0.9.1"\n---\n'
        self.assertEqual(self.metadata(data), {"version": None, "runtimeMinVersion": "0.9.1"})
        duplicate = b'---\nmetadata:\n  version: "0.3.2"\n  version: "0.3.3"\n---\n'
        self.assertEqual(self.metadata(duplicate), {"version": "0.3.3", "runtimeMinVersion": None})

    def test_oversized_numeric_fields_are_unknown_independently(self):
        for value in ("9" * 5000 + ".0.0", str(peer.sys.maxsize + 1) + ".0.0"):
            for field in ("version", "runtime-min-version"):
                with self.subTest(field=field, digits=len(value)):
                    version = value if field == "version" else "0.3.3"
                    minimum = value if field == "runtime-min-version" else "0.9.1"
                    content = ('---\nmetadata:\n  version: "' + version + '"\n  runtime-min-version: "'
                               + minimum + '"\n---\n').encode()
                    self.assertLess(len(content), LIMIT)
                    expected = {"version": None if field == "version" else "0.3.3",
                                "runtimeMinVersion": None if field == "runtime-min-version" else "0.9.1"}
                    self.assertEqual(self.metadata(content), expected)

    def test_reads_at_most_budget_plus_one_without_read_text(self):
        path = self.write(RELEASED_HEADER.format(version="0.3.3").encode() + b"x" * 100000)
        original = os.read
        reads = []
        def bounded_read(fd, count):
            self.assertGreater(count, 0)
            reads.append(count)
            return original(fd, count)
        with mock.patch.object(peer.os, "read", side_effect=bounded_read), \
                mock.patch.object(Path, "read_text", side_effect=AssertionError("No whole text read")):
            result = peer.installed_skill_metadata(path)
        self.assertEqual(result["version"], "0.3.3")
        self.assertLessEqual(sum(reads), LIMIT + 1)

    def test_short_reads_are_accumulated_with_a_total_byte_bound(self):
        path = self.write(RELEASED_HEADER.format(version="0.3.3").encode() + b"x" * 100000)
        original = os.read
        returned = []
        def short(fd, count):
            data = original(fd, min(count, 137))
            returned.append(len(data))
            return data
        with mock.patch.object(peer.os, "read", side_effect=short):
            result = peer.installed_skill_metadata(path)
        self.assertEqual(result["version"], "0.3.3")
        self.assertLessEqual(sum(returned), LIMIT + 1)

    @unittest.skipIf(os.name == "nt", "symlink privilege is not assumed")
    def test_manager_symlink_is_followed_without_mutation(self):
        target = self.write(RELEASED_HEADER.format(version="0.3.3").encode() + b"x" * 18824)
        alias = self.root / "manager-link.md"
        alias.symlink_to(target)
        original = target.read_bytes()
        self.assertEqual(peer.installed_skill_metadata(alias)["version"], "0.3.3")
        self.assertTrue(alias.is_symlink())
        self.assertEqual(target.read_bytes(), original)

    def test_unreadable_and_directory_paths_are_unknown(self):
        self.assertEqual(peer.installed_skill_metadata(self.root), UNKNOWN)
        with mock.patch.object(peer.os, "open", side_effect=PermissionError("fixture")):
            self.assertEqual(peer.installed_skill_metadata(self.path), UNKNOWN)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX nonblocking FIFO")
    def test_fifo_is_unknown_without_blocking_on_open(self):
        os.mkfifo(self.path)
        original_open = os.open
        def nonblocking(path, flags):
            self.assertTrue(flags & os.O_NONBLOCK, "FIFO open must be nonblocking")
            return original_open(path, flags)
        with mock.patch.object(peer.os, "open", side_effect=nonblocking), \
                mock.patch.object(Path, "open", side_effect=AssertionError("No blocking buffered FIFO open")):
            self.assertEqual(peer.installed_skill_metadata(self.path), UNKNOWN)

    def test_descriptor_is_closed_after_read_failure_or_nonregular_rejection(self):
        self.write(RELEASED_HEADER.format(version="0.3.3").encode())
        for failure in ("read", "stat", "nonregular"):
            with self.subTest(failure=failure), mock.patch.object(peer.os, "close", wraps=os.close) as closed:
                if failure == "nonregular":
                    patcher = mock.patch.object(peer.stat, "S_ISREG", return_value=False)
                else:
                    patcher = mock.patch.object(peer.os, "fstat" if failure == "stat" else "read",
                                                side_effect=OSError("fixture"))
                with patcher:
                    self.assertEqual(peer.installed_skill_metadata(self.path), UNKNOWN)
                closed.assert_called_once()
                with self.assertRaises(OSError) as caught:
                    os.fstat(closed.call_args.args[0])
                self.assertEqual(caught.exception.errno, errno.EBADF)
