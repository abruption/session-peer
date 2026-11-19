"""Stable version and publication boundary agree across package and docs."""

from pathlib import Path
import hashlib
import re
import unittest

import session_peer


ROOT = Path(__file__).resolve().parents[2]


class StableCandidate(unittest.TestCase):
    def test_v161_publication_preserves_preparation_and_records_separate_assets(self):
        profiles = [
            ('', '', 'Source version: ',
             '9142e9e065aba97d470896ab41cd8e2b0a264c084e153c01fd147bab6867d1c4',
             '82e15f9f5f5fc2fe5f3484d6f84e9db2d631d1a6cd6d09fbd9b810bc2b668ad9',
             '5610f1b6c5959637edbd60bafb1f93dccfb75e25e50412872234d1dbe70d98fc'),
            ('ko/', '.ko', '소스 버전: ',
             '9819bf1913b08ad68b81f4b15122ed2d810cdf3849e4097616f62c2745b0a50d',
             '5907becd7f9002b0a80afa493aef9ada6585630e94c1beaada73df135fe1c9cc',
             '4e9b06abd05840da8508465f250e9c1f80071ca865b461055969441da19ef09c'),
            ('ja/', '.ja', 'ソースバージョン：',
             '2be5c63c1a0365a86db7416b91030770c6bb5127233ba8ecd35ca5e20520d795',
             'b46e31f59fb91fafb91314cfed0103f08521db20043de2117297290ca28e0bd3',
             '2d7b9250c54c57845bbe9d7c918aa7feee4a21338be47e73f1d9c3291986fae5'),
            ('zh-CN/', '.zh-CN', '源码版本：',
             'bbe3e4f522a238c641be462baad9716bdccdaab3993b8e6e5802dc54d9ad27bf',
             '820f53e6d924042f0796d0aacb06af721d6bc4de5a52f0b31e18b67a7e3f8790',
             '171e0ac8d6b2398e0c6a94043dfe86c877a9bdc98d1c8780a24caf8339d0600e'),
        ]
        for locale, suffix, prefix, notes_hash, book_hash, hero_hash in profiles:
            notes = (ROOT / ('docs/' + locale + 'releases/v1.6.1.md')).read_text(encoding='utf-8')
            preparation, publication = notes.split('\n<a id="v161-publication-record"></a>', 1)
            self.assertEqual(notes_hash, hashlib.sha256(preparation.encode('utf-8')).hexdigest())
            for fact in ('23ec62bf0f25cbf1cdbf6ea04710d0854ad34e80', 'type=commit',
                    '2026-11-17T03:19:08Z', '2026-11-17T03:21:20.924302Z', '2026-11-17T03:21:22.395012Z',
                    'session_peer-1.6.1-py3-none-any.whl', 'session_peer-1.6.1.tar.gz',
                    '6eaeb0e9e2598fbb3a1681c752f1d6222488cfb666c444413d290fcb0c01217c',
                    'a04e189bfb15741c888387241ec1578138219ff84c12d3eb3f2870bd456bd5f3',
                    'install.sh', '3ba1bac086c009691a269964e23ff66e422295a389a14ef040633b630eff1900',
                    'session_peer.py', '0100e9646f779cef49360aa2b34ae372a6835296e804b72825fbfdc3f45f1c90',
                    '44007602649', '44007603025', '44008951082', '44009347500', 'pypi', 'abruption',
                    '0.5.1', '0.9.1', '1.4.0', '922512869577cc3d8b9d305641479e2dd659f0e669298584ca06f1ca15de1d31'):
                with self.subTest(locale=locale, fact=fact):
                    self.assertIn(fact, publication)
            table = '\n'.join(line for line in publication.splitlines() if line.startswith('|'))
            self.assertEqual(2, sum(line.startswith('| `session_peer-') for line in table.splitlines()))
            self.assertNotIn('install.sh', table)
            book = (ROOT / ('RELEASING' + suffix + '.md')).read_text(encoding='utf-8')
            marker = {'': '## v1.6.1 preparation', '.ko': '## v1.6.1 준비',
                      '.ja': '## v1.6.1準備', '.zh-CN': '## v1.6.1准备'}[suffix]
            self.assertEqual(book_hash, hashlib.sha256(book[book.index(marker):].encode('utf-8')).hexdigest())
            readme = (ROOT / ('README' + suffix + '.md')).read_text(encoding='utf-8')
            self.assertEqual(hero_hash, hashlib.sha256(readme.split(prefix, 1)[0].encode('utf-8')).hexdigest())
            notice = next(line for line in readme.splitlines() if line.startswith(prefix))
            for fact in ('**1.6.1**', 'releases/v1.6.1.md#v161-publication-record',
                         'https://pypi.org/project/session-peer/1.6.1/', 'releases/v1.6.0.md#v160-publication-record'):
                self.assertIn(fact, notice)
        publication = (ROOT / 'docs/releases/v1.6.1.md').read_text(encoding='utf-8').split(
            '<a id="v161-publication-record"></a>', 1)[1]
        for boundary in ('not a third PyPI file', 'exact UTC of that observation was not separately recorded',
                         'no exact approval timestamp', 'This task did not automate approval', 'not a repair'):
            self.assertIn(boundary, publication)

    def test_v161_preparation_keeps_patch_scope_and_publication_gates(self):
        histories = [
            ('', '', '## Publication record — v1.6.0 (verified 2026-11-15)',
             '32154ab7f6aba91578e38cbcc40d61a03a6a02a5d453f18a0caeb21da5625ac2'),
            ('ko/', '.ko', '## 공개 기록 — v1.6.0 (2026-11-15 확인)',
             'dce6290f48251f24a25ed4ab709804cd46f3dc36b89c4aee5dca7e662c5d645b'),
            ('ja/', '.ja', '## 公開記録 — v1.6.0（2026-11-15確認）',
             'c9c8861361fb94536c80953ab16b252638a99278982e540b0300942153de1a7f'),
            ('zh-CN/', '.zh-CN', '## 发布记录 — v1.6.0（2026-11-15核实）',
             'b5a1860fdd6206709f562983e03d949f5972a0f0b852f6ed2d5cdf12edb303da'),
        ]
        for locale, suffix, marker, digest in histories:
            book = (ROOT / ('RELEASING' + suffix + '.md')).read_text(encoding='utf-8')
            self.assertEqual(digest, hashlib.sha256(book[book.index(marker):].encode('utf-8')).hexdigest())
            notes = (ROOT / ('docs/' + locale + 'releases/v1.6.1.md')).read_text(encoding='utf-8').split('\n<a id="v161-publication-record"></a>', 1)[0]
            for fact in ('2026-11-17', '1.6.1', '1.6.0', '0154c33f14dc5b9a64c4a3937c2eb50901ed28a4',
                    '#401', '#403', 'f133153b32f68e39061d9c49d91e5042359e888f', 'python3 -I -S -',
                    'PYTHONPATH', 'sitecustomize', 'usercustomize', 'ubuntu-24.04', '3.9', '49', '44003241812',
                    '0.5.1', '0.9.1', '1.4.0', '1.0.1', '31688',
                    '922512869577cc3d8b9d305641479e2dd659f0e669298584ca06f1ca15de1d31',
                    'SHA256SUMS', 'release-provenance.json', '#367'):
                with self.subTest(locale=locale, fact=fact):
                    self.assertIn(fact, notes)
            self.assertNotIn('releases/tag/v1.6.1', notes)
            self.assertNotIn('pypi.org/project/session-peer/1.6.1/', notes)
            self.assertIn('releases/v1.6.1.md', (ROOT / ('docs/' + locale + 'README.md')).read_text(encoding='utf-8'))
        english = (ROOT / 'docs/releases/v1.6.1.md').read_text(encoding='utf-8')
        for boundary in ('unpublished source candidate', 'not the final release commit',
                'does not isolate every Python invocation', 'repair existing installations',
                'does not replace independent review', 'required human PyPI environment approval',
                'does not waive that approval', 'does not install globally'):
            self.assertIn(boundary, english)

    def test_v160_publication_preserves_preparation_and_current_availability(self):
        source = "8a45803748baf371dd31bb33db5db68373cd45f5"
        histories = {
            "": ("6e3e4b551a6494675ef783c01645e150085c4e77d308a3a52cb9ec919cea9022",
                 "## v1.6.0 preparation", "6720f70290473194226f39fd9f1e16e2226f1261fc3509fc9c5a8b175e8a8f60"),
            "ko/": ("30134fbbfcc4e92f7fd3d2869790bea5a0550cbcfd5c13010bc4a798c5d7a559",
                    "## v1.6.0 준비", "63a64fc4268f54ab1ef3a22cb09c6963ccde64d22f1af5579b1a74221638b898"),
            "ja/": ("dac25b5379063df97017107d4bc74ef9170091dae81be2460994c07419afbb97",
                    "## v1.6.0準備", "0bb39a549175251a64ba87d61ca5e4244c745c2287462f8c337c45bce6394871"),
            "zh-CN/": ("553654262be112ece446f2a6d95f89a0ac564fb6954fb7b27460101ea561e357",
                       "## v1.6.0准备", "c1cf69abb2316f9917b41cb0a45b2b1a54143e9cccf2d2ef37811c803642273f"),
        }
        facts = (source, "type=commit", "2026-11-15T05:34:06Z", "2026-11-15T05:36:12.216330Z",
                 "2026-11-15T05:36:13.738944Z", "session_peer-1.6.0-py3-none-any.whl", "session_peer-1.6.0.tar.gz",
                 "747b1b454462fa67b812faec42d9cfdf68713a70c1c25e5f723f5ab05569dc8c",
                 "64b21c22a8c734c18d1c63ecf81308a677f02582d01133a4d33359fc3f49343d",
                 "43680720785", "43680720818", "43681446312", "43681634997", "pypi", "abruption",
                 "95cf5e1dd92654775b2f0ea86c1cb4b6107f49c3", "31688", "0.5.1", "0.9.1", "1.4.0", "1.0.1",
                 "922512869577cc3d8b9d305641479e2dd659f0e669298584ca06f1ca15de1d31")
        for locale, suffix, prefix in (("", "", "Source version: "), ("ko/", ".ko", "소스 버전: "),
                ("ja/", ".ja", "ソースバージョン："), ("zh-CN/", ".zh-CN", "源码版本：")):
            notes = (ROOT / ("docs/" + locale + "releases/v1.6.0.md")).read_text(encoding="utf-8")
            preparation, publication = notes.split('\n<a id="v160-publication-record"></a>', 1)
            old_hash, runbook_marker, runbook_hash = histories[locale]
            self.assertEqual(old_hash, hashlib.sha256(preparation.encode("utf-8")).hexdigest())
            for fact in facts:
                with self.subTest(locale=locale, fact=fact):
                    self.assertIn(fact, publication)
            self.assertNotIn(source, preparation)
            book = (ROOT / ("RELEASING" + suffix + ".md")).read_text(encoding="utf-8")
            self.assertEqual(runbook_hash, hashlib.sha256(
                book[book.index(runbook_marker):].encode("utf-8")).hexdigest())
            for fact in (source, *facts[2:5], "#v160-publication-record", "43680720785", "43680720818",
                         "43681446312", "43681634997", "pypi", "abruption"):
                self.assertIn(fact, book[:book.index(runbook_marker)])
            readme = (ROOT / ("README" + suffix + ".md")).read_text(encoding="utf-8")
            current = next(line for line in readme.splitlines() if line.startswith(prefix))
            for fact in ("**1.6.0**", source, "releases/v1.6.0.md#v160-publication-record",
                         "https://pypi.org/project/session-peer/1.6.0/"):
                self.assertIn(fact, current)
            mcp = (ROOT / ("docs/" + locale + "mcp.md")).read_text(encoding="utf-8")
            self.assertIn("releases/v1.6.0.md#v160-publication-record", mcp.split("\n\n")[1])
            self.assertIn('<a id="bounded-session-listing-393"></a>', mcp)
        publication = (ROOT / "docs/releases/v1.6.0.md").read_text(encoding="utf-8").split(
            '<a id="v160-publication-record"></a>', 1)[1]
        for marker in ("lightweight tag", "not an annotated tag object", "exactly two non-yanked files",
                       "metadata alone was not treated as file verification", "All 7 locked GitHub asset hashes",
                       "does not expose an exact approval timestamp", "No administrator bypass",
                       "byte-for-byte", "neither rebuilds nor replaces"):
            self.assertIn(marker, publication)

    def test_v160_preparation_preserves_scope_history_and_publication_boundaries(self):
        source_base = "0c5bd4243d76ac951dd70bca2b56c8a103fa4231"
        skill_sha = "922512869577cc3d8b9d305641479e2dd659f0e669298584ca06f1ca15de1d31"
        self.assertEqual(skill_sha, hashlib.sha256((ROOT / "skills/session-peer/SKILL.md").read_bytes()).hexdigest())
        histories = {
            "": ("5e5cd23933264be97d3ed8e737efb229198e5cb61eb0837201ad6dcbd7082ce3",
                 "## Publication record — v1.5.0 (verified 2026-11-09)",
                 "9a31b8684fc9616615af5359d7491caa96ba84a460c1200360113449a9e14865"),
            "ko/": ("3a8b2da3d985f3c6706693e7c79d2f84d86cc282861040cbe8dd87b2f21c6908",
                    "## 공개 기록 — v1.5.0 (2026-11-09 확인)",
                    "c464bfc892723e06ae70648e3f8c79abdb076d516ef69425c877dfa583b001fd"),
            "ja/": ("58e4554de49fecae4046a1f94717845ee0cf9dbf1fa21cef4d1d6c8c6a97fc97",
                    "## 公開記録 — v1.5.0（2026-11-09確認）",
                    "5b0dff5fd67ee935f1b11c134509ef9b56a059b901018d05384667cd96a2ef91"),
            "zh-CN/": ("2867db0cf1a24e98c2a7b2fe8c3c64d47e49742a410d4e70c5e3804bdb1b0ef2",
                       "## 发布记录 — v1.5.0（2026-11-09核实）",
                       "f2d8889a1eb9d68b2a19c2c3962eaa7b9e281ac61f6aa4ee42acb8bd7d47c243"),
        }
        for locale, suffix, prefix in (("", "", "Source version: "), ("ko/", ".ko", "소스 버전: "),
                ("ja/", ".ja", "ソースバージョン："), ("zh-CN/", ".zh-CN", "源码版本：")):
            notes = (ROOT / ("docs/" + locale + "releases/v1.6.0.md")).read_text(encoding="utf-8").split(
                '\n<a id="v160-publication-record"></a>', 1)[0]
            for marker in (source_base, "2026-11-15", "1.6.0", "1.5.0", "#393", "#394", "#395", "#396",
                    "4 MiB", "64 KiB", "8 MiB", "20,000", "600", "RSS", "JSON-RPC",
                    "list_sessions_page", "nameOmitted=true", "nameTruncated=true", "complete=false",
                    'type="refusal"', "retryAllowed=false", "isError=false", "isError=true", "0.9.1", "1.4.0", "1.0.1",
                    "mcp>=1.30,<3,!=2.0.*,!=2.1.*,!=2.2.*", "#367", "#380/#387/#388", "31688", skill_sha,
                    "95cf5e1dd92654775b2f0ea86c1cb4b6107f49c3", "SHA256SUMS", "release-provenance.json"):
                with self.subTest(locale=locale, marker=marker):
                    self.assertIn(marker, notes)
            self.assertNotIn("releases/tag/v1.6.0", notes)
            self.assertNotIn("pypi.org/project/session-peer/1.6.0/", notes)
            readme = (ROOT / ("README" + suffix + ".md")).read_text(encoding="utf-8")
            active = next(line for line in readme.splitlines() if line.startswith(prefix))
            self.assertIn("**1.6.0**", active)
            self.assertIn("2026-11-15", active)
            self.assertIn("releases/v1.6.0.md", active)
            runbook = (ROOT / ("RELEASING" + suffix + ".md")).read_text(encoding="utf-8")
            old_notes_hash, old_runbook_marker, old_runbook_hash = histories[locale]
            self.assertEqual(old_notes_hash, hashlib.sha256(
                (ROOT / ("docs/" + locale + "releases/v1.5.0.md")).read_bytes()).hexdigest())
            self.assertEqual(old_runbook_hash, hashlib.sha256(
                runbook[runbook.index(old_runbook_marker):].encode("utf-8")).hexdigest())
            for path in ("docs/" + locale + "README.md", "docs/" + locale + "mcp.md"):
                self.assertIn("releases/v1.6.0.md", (ROOT / path).read_text(encoding="utf-8"))
        english = (ROOT / "docs/releases/v1.6.0.md").read_text(encoding="utf-8").split(
            '\n<a id="v160-publication-record"></a>', 1)[0]
        for marker in ("unpublished source candidate", "before version preparation, not the final release commit",
                "seventh MCP tool", "30-second idle deadline", "absolute 600-second lifetime",
                "no separate elapsed-time deadline", "required human PyPI environment approval",
                "not certification", "do not replace checks of the exact preparation head"):
            self.assertIn(marker, english)

    def test_v150_publication_record_preserves_preparation_and_historical_guidance(self):
        source = "9a0b23ff5e1f83e1cee4dc22bec7e3c0ca8063bb"
        annotation = "a94dc17f7c04cb2691a1079b9e19f8a954c677af"
        historical_base = "a622dc0d9f04a252af65147eb36188998bf0c8b4"
        facts = (source, annotation, "2026-11-09T11:53:51Z",
                 "2026-11-09T11:56:07.458092Z", "2026-11-09T11:56:09.127893Z",
                 "993029cab7d2b11aaac4e85de0319992d686e8c1338344806be1195ad3637299",
                 "9f56d785ca5ba250a2e88c5e59e73dc4c6e07d39d60e073a89e9a89bea5617e2",
                 "42609705390", "42609703536", "42612126606", "42612614015",
                 "session_peer-1.5.0-py3-none-any.whl", "session_peer-1.5.0.tar.gz")
        profiles = (("", "", "Source version: "), ("ko/", ".ko", "소스 버전: "),
                    ("ja/", ".ja", "ソースバージョン："), ("zh-CN/", ".zh-CN", "源码版本："))
        for locale, suffix, prefix in profiles:
            notes = (ROOT / ("docs/" + locale + "releases/v1.5.0.md")).read_text(encoding="utf-8")
            preparation, publication = notes.split('<a id="v150-publication-record"></a>', 1)
            self.assertIn(historical_base, preparation)
            self.assertNotIn(source, preparation)
            for marker in facts:
                with self.subTest(locale=locale, marker=marker):
                    self.assertIn(marker, publication)
            runbook = (ROOT / ("RELEASING" + suffix + ".md")).read_text(encoding="utf-8")
            old_preparation = re.search(r"^## v1\.5\.0[^\n]*$", runbook, re.MULTILINE)
            self.assertIsNotNone(old_preparation)
            record = runbook[:old_preparation.start()]
            for marker in (source, facts[2], facts[3], facts[4], "#v150-publication-record",
                           "42609705390", "42612126606", "42612614015", "pypi", "abruption"):
                self.assertIn(marker, record)
            self.assertIn(historical_base, runbook[old_preparation.start():])
            readme = (ROOT / ("README" + suffix + ".md")).read_text(encoding="utf-8")
            # Publication history stays independently checked when current
            # source guidance advances to a new preparation version.
            self.assertIn(source, readme)
            self.assertIn("releases/v1.5.0.md#v150-publication-record", readme)
            self.assertIn("https://pypi.org/project/session-peer/1.5.0/", readme)
            sdk = next(part for part in readme.split("\n\n") if "sdk1-sdk2-published-v150" in part)
            self.assertIn("v1.5.0", sdk)
            self.assertIn("mcp>=1.30,<3,!=2.0.*,!=2.1.*,!=2.2.*", sdk)
            mcp = (ROOT / ("docs/" + locale + "mcp.md")).read_text(encoding="utf-8")
            self.assertIn("releases/v1.5.0.md#v150-publication-record", mcp)
            self.assertIn('<a id="sdk2-compatibility-candidate"></a>', mcp)
        english = (ROOT / "docs/releases/v1.5.0.md").read_text(encoding="utf-8").split(
            '<a id="v150-publication-record"></a>', 1)[1]
        self.assertIn("all 49 [main CI]", english)
        self.assertIn("All 7 GitHub asset attestations", english)
        self.assertIn("does not expose an exact approval timestamp", english)
        self.assertIn("No administrator bypass", english)
        self.assertIn("does not rebuild or replace tags or immutable assets", english)
        self.assertIn("Publication does not establish fleet/global installation", english)

    def test_v150_preparation_keeps_candidate_and_publication_boundaries(self):
        integrated_base = "a622dc0d9f04a252af65147eb36188998bf0c8b4"
        self.assertRegex(integrated_base, r"^[0-9a-f]{40}$")
        skill_sha = "922512869577cc3d8b9d305641479e2dd659f0e669298584ca06f1ca15de1d31"
        self.assertEqual(skill_sha, hashlib.sha256(
            (ROOT / "skills/session-peer/SKILL.md").read_bytes()).hexdigest())
        receiver_floors = {
            "": "receiver `codexBin` floor remains 1.0.1",
            "ko/": "수신측 `codexBin` 하한은 1.0.1",
            "ja/": "受信側`codexBin`の下限は1.0.1",
            "zh-CN/": "接收端`codexBin`下限仍为1.0.1",
        }
        for locale, suffix in (("", ""), ("ko/", ".ko"), ("ja/", ".ja"), ("zh-CN/", ".zh-CN")):
            notes = (ROOT / ("docs/" + locale + "releases/v1.5.0.md")).read_text(encoding="utf-8")
            for marker in (integrated_base, "2026-11-09", "1.5.0", "1.4.2", "#390", "#379", "#381",
                           "mcp>=1.30,<3,!=2.0.*,!=2.1.*,!=2.2.*", "MCPServer(subscriptions=False)",
                           "64 KiB", "24", skill_sha, "0.5.1", "0.9.1", "1.4.0", "1.0.1",
                           "#387/#388", "SHA256SUMS", "release-provenance.json"):
                with self.subTest(locale=locale, marker=marker):
                    self.assertIn(marker, notes)
            self.assertNotIn("V150_" + "INTEGRATED_BASE_PENDING", notes)
            self.assertIn(receiver_floors[locale], notes)
            runbook = (ROOT / ("RELEASING" + suffix + ".md")).read_text(encoding="utf-8")
            preparation = re.search(r"^## v1\.5\.0[^\n]*\n[\s\S]*?(?=^## |\Z)",
                                    runbook, re.MULTILINE)
            self.assertIsNotNone(preparation)
            self.assertIn(integrated_base, preparation.group(0))
            for stem in ("README", "RELEASING"):
                self.assertIn("releases/v1.5.0.md", (ROOT / (stem + suffix + ".md")).read_text(encoding="utf-8"))
        english = (ROOT / "docs/releases/v1.5.0.md").read_text(encoding="utf-8")
        self.assertIn("for 24 CI cells", english)
        self.assertIn("31688 UTF-8 bytes, SHA-256 `" + skill_sha + "`", english)
        self.assertIn("documented full workflow coverage 1.4.0", english)
        self.assertIn("unpublished source candidate", english)
        self.assertIn("does not authorize merging the release-preparation PR", english)
        self.assertIn("No tag, draft, workflow dispatch or publication is performed", english)
        self.assertIn("only the test dependency Paramiko 5.1.0 and its matching test assertion", english)
        self.assertIn("Control remains private version 0.1.0", english)
        self.assertIn("Required human PyPI environment approval remains", english)

    def test_v141_maintenance_keeps_runtime_and_skill_release_boundaries(self):
        expected = ("2026-11-03", "1.4.1", "1.4.0", "0.5.1", "0.9.1", "1.0.1",
                    "192b77ec4a168859c26fe886ff42901f24060608",
                    "95cf5e1dd92654775b2f0ea86c1cb4b6107f49c3", "31688",
                    "922512869577cc3d8b9d305641479e2dd659f0e669298584ca06f1ca15de1d31",
                    "immutable=false", "#366", "#369", "#370", "#367",
                    "SHA256SUMS", "release-provenance.json", "0.4.1")
        for locale, suffix in (("", ""), ("ko/", ".ko"), ("ja/", ".ja"), ("zh-CN/", ".zh-CN")):
            with self.subTest(locale=locale):
                notes = (ROOT / ("docs/" + locale + "releases/v1.4.1.md")).read_text(encoding="utf-8")
                for marker in expected:
                    self.assertIn(marker, notes)
                for stem in ("README", "RELEASING"):
                    self.assertIn("releases/v1.4.1.md", (ROOT / (stem + suffix + ".md")).read_text(encoding="utf-8"))
        english = (ROOT / "docs/releases/v1.4.1.md").read_text(encoding="utf-8")
        self.assertIn("no runtime defect is claimed fixed", english)
        self.assertIn("This patch does not fix #370", english)
        self.assertIn("Required human PyPI environment approval remains", english)

    def test_v140_publication_record_preserves_preparation_and_pinned_skill_history(self):
        source = "476c67e636ef02cb93797dd2f42252dfe577625f"
        facts = (source, "2026-11-03", "2026-11-02T04:36:59Z",
                 "2026-11-02T04:38:34.686393Z", "2026-11-02T04:38:36.363777Z",
                 "b9d931ae9046f081dac15fcbeb5ca886aa437aa8e3bbb4be8296b81b2cec6832",
                 "cfb06b3a8c4410178ddf0bbdd3f2b1733288d6221174b05309cf2dfaba7930bf",
                 "41389266767", "41389462046", "0.4.1", "0.5.0", "0.5.1",
                 "95cf5e1dd92654775b2f0ea86c1cb4b6107f49c3", "31688",
                 "922512869577cc3d8b9d305641479e2dd659f0e669298584ca06f1ca15de1d31",
                 "immutable=false", "0.9.1", "1.4.0", "1.0.1")
        for locale, suffix in (("", ""), ("ko/", ".ko"), ("ja/", ".ja"), ("zh-CN/", ".zh-CN")):
            with self.subTest(locale=locale):
                notes = (ROOT / ("docs/" + locale + "releases/v1.4.0.md")).read_text(encoding="utf-8")
                preparation, publication = notes.split('<a id="v140-publication-record"></a>', 1)
                for fact in facts:
                    self.assertIn(fact, publication)
                self.assertIn("f290973962c63548f24153eeee12a8e3666fd043", preparation)
                self.assertNotIn(source, preparation)
                for stem in ("README", "RELEASING"):
                    text = (ROOT / (stem + suffix + ".md")).read_text(encoding="utf-8")
                    self.assertIn("releases/v1.4.0.md#v140-publication-record", text)

    def test_v140_preparation_separates_source_publication_and_skill_contracts(self):
        for locale in ('', 'ko/', 'ja/', 'zh-CN/'):
            notes = (ROOT / ('docs/' + locale + 'releases/v1.4.0.md')).read_text(encoding='utf-8')
            for marker in ('2026-11-02', '1.4.0', '1.3.3',
                           'f290973962c63548f24153eeee12a8e3666fd043',
                           '#356', '#357', '#358', '#359', '#361', '#362', '#363', '#364',
                           '41381070618', '41381070309', 'SHA256SUMS', 'release-provenance.json',
                           '0.4.1', '0.5.0', '0.9.1', '1.3.2', '1.0.1',
                           'fdf5697c04f4a37194986622afb3a7966bb02631c128cf18a323e3fbe5ae90ed'):
                self.assertIn(marker, notes)
        english = (ROOT / 'docs/releases/v1.4.0.md').read_text(encoding='utf-8')
        for marker in ('unpublished', 'not the final release commit',
                       'human PyPI environment approval', '7 frozen assets'):
            self.assertIn(marker, english)

    def test_json_guide_distinguishes_ordinary_and_specialized_schemas(self):
        for locale in ('', 'ko/', 'ja/', 'zh-CN/'):
            text = (ROOT / ('docs/' + locale + 'cli-reference.md')).read_text(encoding='utf-8')
            block = text.split('"version": "0.8.0"')[0].rsplit('### ', 1)[-1]
            self.assertIn('`--json`', block)
            self.assertIn('`--explain-json`', block)
            self.assertIn('`send.preflight`', block)
            self.assertIn('MCP', block)
            self.assertIn('"host": "mac-mini.example.ts.net"', block)

    def test_v133_preparation_preserves_source_and_publication_boundaries(self):
        localized_gates = {
            "": ("unpublished candidate", "does not authorize merge, tag creation or publication",
                 "required human PyPI environment approval", "final protected-main source"),
            "ko/": ("미공개 후보", "병합·태그 생성·발행을 승인하지 않습니다",
                    "PyPI 환경의 사람 승인", "최종 보호된 main 소스의 검사"),
            "ja/": ("未公開の候補", "マージ・タグ作成・公開を承認しません",
                    "PyPI環境の人による承認", "最終的な保護されたmainソースの検査"),
            "zh-CN/": ("尚未发布", "候选版本", "不授权合并、创建标签或发布",
                       "PyPI环境必需的人工批准", "最终受保护main源码的检查"),
        }
        expected = ("1.3.3", "2026-10-30", "ec2f7fc808f1e22519348091d51c28a2fd522caf",
                    "6f9026e46138db544fb9c990387fcd4ccf37400f",
                    "88f2c906e3f4bae8b377fcfac049a65fd68dea64",
                    "263b0c333d539dc4e885b16ae3369a26f33097d8",
                    "ba08d19af33cad0f7d032b7fe18c82d6ddd6793f",
                    "fdf5697c04f4a37194986622afb3a7966bb02631c128cf18a323e3fbe5ae90ed",
                    "27126", "0.4.1", "0.9.1", "1.3.2", "1.0.1",
                    "40982760413", "40982759604", "SHA256SUMS", "release-provenance.json")
        for locale, suffix in (("", ""), ("ko/", ".ko"), ("ja/", ".ja"), ("zh-CN/", ".zh-CN")):
            with self.subTest(locale=locale):
                notes = (ROOT / ("docs/" + locale + "releases/v1.3.3.md")).read_text(encoding="utf-8")
                for marker in expected:
                    self.assertIn(marker, notes)
                for marker in localized_gates[locale]:
                    self.assertIn(marker, notes)
                self.assertIn("releases/v1.3.3.md", (ROOT / ("RELEASING" + suffix + ".md")).read_text(encoding="utf-8"))
                self.assertNotIn("```", notes)
        notes = (ROOT / "docs/releases/v1.3.3.md").read_text(encoding="utf-8")
        for boundary in ("unpublished candidate", "not the final release commit",
                         "does not authorize merge, tag creation or publication",
                         "not new live native-agent, Windows 3.14 or free-threaded Python acceptance",
                         "required human PyPI environment approval",
                         "do not replace checks of the preparation head"):
            self.assertIn(boundary, notes)

    def test_v121_preparation_records_patch_sources_and_publication_gates(self):
        notes = [(ROOT / ("docs/" + locale + "releases/v1.2.1.md")).read_text(encoding="utf-8")
                 for locale in ("", "ko/", "ja/", "zh-CN/")]
        source_base = "32e76d2c85d945d66466f630d9729ec0be5288d8"
        expected_pairs = ((319, 317, "ba00540e24e4e378c002c11e7cbeb23b85003b9f"),
                          (320, 318, "c5625a1667de50b2684067febed1772ed693eca7"),
                          (303, 302, source_base))
        locale_boundaries = {
            "": ("unknown never permits automatic resend",
                 "does not authorize its own merge, tag/draft creation, workflow dispatch, publication or deployment"),
            "ko/": ("unknown은 자동 재전송을 허용하지 않습니다",
                    "준비 PR 자체의 병합, 태그·초안 생성, 워크플로 실행 요청, 공개·배포를 승인하지 않습니다"),
            "ja/": ("unknownは自動再送を許可しません",
                    "この準備自身のマージ、タグ・ドラフト作成、ワークフロー実行、公開・配備も承認しません"),
            "zh-CN/": ("unknown不允许自动重发",
                       "也不授权准备自身合并、创建标签/草稿、派发工作流、发布或部署"),
        }
        for locale, text in zip(("", "ko/", "ja/", "zh-CN/"), notes):
            with self.subTest(locale=locale):
                self.assertNotIn("PENDING", text)
                positions = []
                for pr, issue, expected_sha in expected_pairs:
                    row = re.search(r"\| #%d \| #%d \| `([0-9a-f]{40})` \|" % (pr, issue), text)
                    self.assertIsNotNone(row)
                    positions.append(row.start())
                    self.assertEqual(expected_sha, row.group(1))
                self.assertEqual(positions, sorted(positions))
                self.assertIn(source_base, text)
                suffix = "." + locale.rstrip("/") if locale else ""
                self.assertIn(source_base, (ROOT / ("RELEASING" + suffix + ".md")).read_text(encoding="utf-8"))
                for marker in ("1.2.1", "1.2.0", "2026-10-19", "macOS", "Windows/Linux",
                               "CLAUDE_CONFIG_DIR", "ANTHROPIC_CONFIG_DIR", "16 KiB", "UTF-8",
                               "0.3.3", "0.9.1", "1.0.1", "#316", "#161", "20/21",
                               "#321", "#322", "HUP/INT/TERM", "SIGKILL",
                               "#180", "#181", "#268", "#304", "#306", "#307", "Control/Relay",
                               "pypi", "attach-draft", "SHA256SUMS", "release-provenance.json",
                               "ad4aa0e464fb142424f6fb6a30303bb88e47163e",
                               "4cd202af4b6a2f0b5e7daa1e7f9d960eb7a67217", "generationStatus=available",
                               "eb239fb358336d85b49bab2c80e4ea39037d1374",
                               "15378c6d503a69d1d738ac4739182e23257aa6f2f7fd31ef3fd2fa60e692867f"):
                    self.assertIn(marker, text)
                for marker in locale_boundaries[locale]:
                    self.assertIn(marker, text)
                self.assertNotIn("```", text)
        for marker in ("not a publication announcement", "No YAML or skill instructions are executed",
                       "refuses all target selection", "ordinary socket aliases remain supported",
                       "not publishable release assets", "required human pypi environment approval",
                       "not a reservation", "no executable release commands",
                       "does not authorize its own merge", "never rebuild or replace immutable assets",
                       "not the proven cause of the original CI failure", "only the allocation child",
                       "no-automatic-retry contract are unchanged", "not a universal cancellation deadline"):
            self.assertIn(marker, notes[0])

    def test_v120_publication_addendum_does_not_erase_candidate_history(self):
        for locale in ("", "ko/", "ja/", "zh-CN/"):
            text = (ROOT / ("docs/" + locale + "releases/v1.2.0.md")).read_text(encoding="utf-8")
            for marker in ("2026-10-19", "2026-10-16", "12:39:13 UTC", "12:41:38.903354 UTC",
                           "12:41:40.537212 UTC", "4fc526f36afc65bb6ec460439eb0986c09ecc8ee",
                           "https://github.com/abruption/session-peer/releases/tag/v1.2.0",
                           "https://pypi.org/pypi/session-peer/1.2.0/json", "#315", "2026-10-15"):
                self.assertIn(marker, text)
        english = (ROOT / "docs/releases/v1.2.0.md").read_text(encoding="utf-8")
        self.assertIn("historical preparation snapshot", english)
        self.assertIn("not current status", english)
        self.assertIn("candidate is unpublished", english)

    def test_v120_candidate_records_merged_scope_and_open_gates(self):
        source_base = "21a0be0c0c5bcb8bca214d90a873b7479d7ba97a"
        merged_prs = (
            (305, "3392c561e8b8b3221c8c5fcad6077cad8f7becd8"),
            (311, "57c42d4a97b351de41a6180b7a05a0ec018d0c4c"),
            (310, "10a6da72b8b94f08b6b3b2ff70f581aadf548279"),
            (308, "b04e46c4e641fd0defab72b96c26d0612d0d6a5e"),
            (313, "9c625bebb21dec2519214889fc60cc3f362142c1"),
            (314, source_base),
        )
        profiles = (
            ("", "The 26 regression tests include unsupported API cases",
             "Merge the release-preparation PR last", "not publishable release assets"),
            ("ko/", "회귀 테스트 26개에는 미지원 API 사례",
             "릴리스 준비 PR은 범위 내 PR 6개를 모두 병합한 뒤 마지막으로 병합",
             "게시할 릴리스 자산이 아닙니다"),
            ("ja/", "26件の回帰テストには未対応API例",
             "リリース準備PRは対象6件のPRをすべてマージした後、最後にマージ",
             "公開用リリース資産ではありません"),
            ("zh-CN/", "26项回归测试包括不支持API的情况",
             "发布准备PR必须在范围内全部6项PR合并后最后合并",
             "不是可发布的版本资产"),
        )
        for locale, regression_scope, merge_order, artifact_boundary in profiles:
            text = (ROOT / ("docs/" + locale + "releases/v1.2.0.md")).read_text(encoding="utf-8")
            for marker in ("1.1.2", "1.2.0", "2026-10-15", "2026-10-16", "2026-10-18",
                           "#305", "#308", "#310", "#311", "#313", "#314", "#315", source_base,
                           "#180", "#181", "#268", "#304", "#306", "#307",
                           regression_scope, merge_order, artifact_boundary,
                           "20/21", "#161", "#316", "pypi", "Control/Relay"):
                self.assertIn(marker, text)
            merge_rows = ["| #%d | `%s` |" % pair for pair in merged_prs]
            positions = [text.index(row) for row in merge_rows]
            self.assertEqual(positions, sorted(positions))
            suffix = "." + locale.rstrip("/") if locale else ""
            runbook = (ROOT / ("RELEASING" + suffix + ".md")).read_text(encoding="utf-8")
            self.assertIn(merge_order, runbook)
            self.assertIn(artifact_boundary, runbook)
            self.assertIn(source_base, runbook)
            self.assertIn("#315", runbook)
            neutral_freeze, immutable_metadata, diagnostic = {
                "": ("publication-neutral wording", "never rebuild or replace immutable assets",
                     "transport-creation and shutdown diagnostics"),
                "ko/": ("공개 여부와 무관하게 정확한 문구", "불변 자산을 다시 빌드하거나 교체하지",
                        "transport 생성·종료 진단"),
                "ja/": ("公開の前後によらず正確な表現", "不変資産を再ビルド・置換せず",
                        "transport生成・終了診断"),
                "zh-CN/": ("发布前后均准确的表述", "重新构建或替换不可变资产",
                           "transport创建及关闭诊断"),
            }[locale]
            for marker in (neutral_freeze, immutable_metadata, diagnostic,
                           "SHA256SUMS", "release-provenance.json"):
                self.assertIn(marker, text)
                self.assertIn(marker, runbook)
        english = (ROOT / "docs/releases/v1.2.0.md").read_text(encoding="utf-8")
        for marker in ("candidate is unpublished", "The six scoped PRs are merged",
                       "PR #315 remains open", "not the final release-preparation or publication commit",
                       "3-second timeout", "up to 2 seconds", "not effective-storage attestation",
                       "unmaterialized empty TUIs may be refused", "remain open",
                       "not proof of general first-input support",
                       "required human pypi environment approval",
                       "review its final head", "historical approvals do not authorize v1.2.0",
                       "final protected-main CI", "rebuild and verify release assets",
                       "At publication time", "actual publication evidence"):
            self.assertIn(marker, english)
        self.assertNotIn("## Proposed changes", english)
        runbook = (ROOT / "RELEASING.md").read_text(encoding="utf-8")
        self.assertIn("not recorded as verified", runbook)
        self.assertNotIn("six unmerged feature branches", runbook)

    def test_historical_pid_patch_preparation_remains_narrow(self):
        for locale in ("", "ko/", "ja/", "zh-CN/"):
            note = (ROOT / ("docs/" + locale + "releases/v1.1.2.md")).read_text(encoding="utf-8")
            for marker in ("#298", "1.1.1", "1.1.2", "2026-10-13", "²",
                           "Control/Relay", "20/21", "#161", "handoff-runtime.md"):
                with self.subTest(locale=locale, marker=marker):
                    self.assertIn(marker, note)
        english = (ROOT / "docs/releases/v1.1.2.md").read_text(encoding="utf-8")
        self.assertIn("candidate is unpublished", english)
        self.assertIn("preparation does not authorize merge", english)
        self.assertIn("Package publication does not include operational deployment", english)

    def test_maintenance_notes_do_not_claim_runtime_remediation(self):
        for locale in ("", "ko/", "ja/", "zh-CN/"):
            note = (ROOT / ("docs/" + locale + "releases/v1.1.1.md")).read_text(encoding="utf-8")
            for marker in ("#297", "#281", "#299", "#298", "Paramiko 5.0.0",
                           "OpenSSH", "2026-10-12", "1.1.0", "20/21", "#161",
                           "handoff-runtime.md", "Control/Relay",
                           "https://github.com/abruption/session-peer/releases/tag/v1.1.1",
                           "https://pypi.org/pypi/session-peer/1.1.1/json"):
                with self.subTest(locale=locale, marker=marker):
                    self.assertIn(marker, note)
        english = (ROOT / "docs/releases/v1.1.1.md").read_text(encoding="utf-8")
        self.assertIn("runtime behavior is unchanged", english)
        self.assertIn("This patch does not fix that runtime defect", english)
        self.assertIn("Paramiko is not a shipped runtime dependency", english)
        self.assertIn("Package publication does not include operational deployment", english)

    def test_documentation_maps_keep_published_and_historical_status_distinct(self):
        profiles = (
            ("", "Experimental handoff runtime", "remaining acceptance gates",
             "published 1.1.0 evidence", "prior maintenance release"),
            ("ko/", "실험적 Handoff 런타임", "남은 수락 조건",
             "공개된 1.1.0 증거", "이전 유지보수 릴리스"),
            ("ja/", "実験的なHandoffランタイム", "残る受け入れ条件",
             "公開済み1.1.0の証拠", "以前のメンテナンス版"),
            ("zh-CN/", "实验性Handoff运行时", "剩余验收条件",
             "已发布1.1.0的证据", "先前维护版本"),
        )
        for locale, handoff_label, gates, stable, historical in profiles:
            text = (ROOT / ("docs/" + locale + "README.md")).read_text(encoding="utf-8")
            with self.subTest(locale=locale or "en"):
                handoff = next(line for line in text.splitlines() if "(handoff-runtime.md)" in line)
                current = next(line for line in text.splitlines() if "(releases/v1.1.0.md)" in line)
                previous = next(line for line in text.splitlines() if "(releases/v1.0.4.md)" in line)
                self.assertIn(handoff_label, handoff)
                self.assertIn("1.1.0", handoff)
                self.assertIn(gates, handoff)
                self.assertIn(stable, current)
                maintenance = next(line for line in text.splitlines()
                                   if "(releases/v1.1.1.md)" in line)
                self.assertIn("2026-10-12", maintenance)
                self.assertIn("1.1.0", maintenance)
                self.assertIn(historical, previous)
                self.assertIn("2026-10-07", previous)
                self.assertIn("releases/v1.0.3.md", previous)
                self.assertIn("validation/69-rc.md", previous)

    def test_published_guides_share_exact_source_and_publication_evidence(self):
        source = "8ca77cf31254c8287a2593fe484bb30a7dba2727"
        for locale in ("", "ko/", "ja/", "zh-CN/"):
            note = (ROOT / ("docs/" + locale + "releases/v1.1.0.md")).read_text(encoding="utf-8")
            for marker in (source, "06:46:41 UTC", "08:04:35", "08:04:37 UTC",
                           "https://github.com/abruption/session-peer/releases/tag/v1.1.0",
                           "https://pypi.org/pypi/session-peer/1.1.0/json"):
                with self.subTest(locale=locale, marker=marker):
                    self.assertIn(marker, note)
            guide = (ROOT / ("docs/" + locale + "handoff-runtime.md")).read_text(encoding="utf-8")
            self.assertIn("Python v1.1.0", guide)
            self.assertIn("#181", guide)
            self.assertIn("2026-10-09", guide)
            self.assertNotIn("Python v1.0.4", guide)

    def test_completed_release_examples_are_explicitly_historical(self):
        warning = "# Historical v1.1.0 example: do not rerun or reuse this version."
        for suffix in ("", ".ko", ".ja", ".zh-CN"):
            text = (ROOT / ("RELEASING" + suffix + ".md")).read_text(encoding="utf-8")
            with self.subTest(locale=suffix or "en"):
                self.assertIn("8ca77cf31254c8287a2593fe484bb30a7dba2727", text)
                self.assertEqual(2, text.count(warning))
                self.assertIn(warning + "\ngit fetch origin main --tags", text)
                self.assertIn(warning + "\ngh release edit v1.1.0", text)
                self.assertIn("state_db_missing", text)
                self.assertIn("POSIX", text)

    def test_source_version_keeps_experimental_acceptance_gates(self):
        for suffix in ("", ".ko", ".ja", ".zh-CN"):
            text = (ROOT / ("README" + suffix + ".md")).read_text(encoding="utf-8")
            self.assertIn("**" + session_peer.__version__ + "**", text)
            self.assertIn("releases/v1.3.0.md", text)
            self.assertIn("handoff-runtime.md", text)
            self.assertIn("POSIX", text)
            self.assertNotIn("**1.0.4**", text)
            self.assertIn('<div align="center">', text)
        for locale in ("", "ko/", "ja/", "zh-CN/"):
            text = (ROOT / ("docs/" + locale + "releases/v1.1.0.md")).read_text(encoding="utf-8")
            for marker in ("#261", "#283–#290", "#242", "#268", "#232", "#180", "#183",
                           "#238", "#211", "#181", "#30", "1.0.4", "1.1.0", "0.154.0",
                           "0.3.2", "0.9.1", "1.0.1", "32 KiB", "64 KiB", "256 KiB",
                           "1 MiB", "131,071", "90,000", "20/21", "#161"):
                with self.subTest(locale=locale, marker=marker):
                    self.assertIn(marker, text)
        english = (ROOT / "docs/releases/v1.1.0.md").read_text(encoding="utf-8")
        for marker in ("Published on 2026-10-09", "correlation-only", "unsupported", "receipt",
                       "Package publication does not include operational deployment"):
            self.assertIn(marker, english)

    def test_package_and_generated_core_version_agree(self):
        self.assertEqual(session_peer.__version__, "1.6.2")
        self.assertIn('__version__ = "1.6.2"',
                      (ROOT / "session_peer_core/common.py").read_text(encoding="utf-8"))

    def test_current_readmes_and_runbooks_match_source_version(self):
        for suffix in ("", ".ko", ".ja", ".zh-CN"):
            for stem in ("README", "RELEASING"):
                with self.subTest(stem=stem, suffix=suffix):
                    text = (ROOT / (stem + suffix + ".md")).read_text(encoding="utf-8")
                    if stem == "README":
                        prefixes = {"": "Source version: ", ".ko": "소스 버전: ",
                                    ".ja": "ソースバージョン：", ".zh-CN": "源码版本："}
                        line = next(line for line in text.splitlines() if line.startswith(prefixes[suffix]))
                        self.assertTrue(line.startswith(prefixes[suffix] + "**" + session_peer.__version__ + "**"))
                    else:
                        first_preparation = re.search(r"^## (v\d+\.\d+\.\d+)[^\n]*$", text, re.MULTILINE)
                        self.assertIsNotNone(first_preparation)
                        self.assertEqual("v" + session_peer.__version__, first_preparation.group(1))
                    self.assertNotIn("1.0.0rc4", text)
                    if stem == "RELEASING":
                        self.assertIn("--draft=false --prerelease=false --latest", text)
                        self.assertIn("20/21", text)
                        self.assertIn("#161", text)
                        for marker in ("prepare-release.yml", "publish.yml", "SHA256SUMS",
                                       "release-provenance.json", "Review deployments",
                                       "Approve and deploy", "Reject"):
                            self.assertIn(marker, text)

    def test_release_notes_keep_scope_and_limits_visible(self):
        for locale in ("", "ko/", "ja/", "zh-CN/"):
            text = (ROOT / ("docs/" + locale + "releases/v1.0.4.md")).read_text(encoding="utf-8")
            for marker in ("#262", "#263", "#264", "#265", "#266", "#267",
                           "1.0.4", "1.0.3", "0.3.2", "0.9.1", "1.0.1", "2026-10-07",
                           "32 KiB", "64 KiB", "256 KiB", "1 MiB",
                           "outcome_unknown", "retryAllowed: false", "20/21", "#161"):
                with self.subTest(locale=locale, marker=marker):
                    self.assertIn(marker, text)

    def test_stable_release_keeps_operational_deployment_separate(self):
        profiles = (
            ("", "Source version: **1.6.2**",
             "At the 2026-10-28 preparation checkpoint, the last verified published stable release was **1.3.1**.",
             "Development candidate 1.2.1 is unpublished"),
            (".ko", "소스 버전: **1.6.2**",
             "2026-10-28 준비 시점의 마지막 확인 공개 안정판은 **1.3.1**이었습니다.",
             "개발 후보 1.2.1은 미공개입니다"),
            (".ja", "ソースバージョン：**1.6.2**",
             "2026-10-28の準備時点で、最後に確認した公開済み安定版は**1.3.1**でした。",
             "開発候補1.2.1は未公開です"),
            (".zh-CN", "源码版本：**1.6.2**",
             "在2026-10-28的准备检查时，最后确认的已发布稳定版本为**1.3.1**。",
             "开发候选版本1.2.1尚未发布"),
        )
        for suffix, source_version, obsolete_checkpoint, stale_unpublished in profiles:
            text = (ROOT / ("README" + suffix + ".md")).read_text(encoding="utf-8")
            self.assertIn(source_version, text)
            self.assertNotIn(obsolete_checkpoint, text)
            self.assertIn("releases/v1.4.0.md", text)
            for stale_version in ("1.2.0", "1.2.1", "1.3.0"):
                self.assertNotIn(stale_unpublished.replace("1.2.1", stale_version), text)
            self.assertIn("https://github.com/abruption/session-peer/releases", text)
            self.assertIn("https://pypi.org/project/session-peer/", text)
            self.assertNotIn("**1.0.3**", text)
        for locale, merged_scope, stale_scope in (
                ("", "the merged six-PR scope", "the proposed six-PR scope"),
                ("ko/", "병합된 PR 6개 범위", "제안한 PR 6개 범위"),
                ("ja/", "マージ済み6件のPRの範囲", "提案する6件のPRの範囲"),
                ("zh-CN/", "已合并的6项PR范围", "拟议的6项PR范围")):
            text = (ROOT / ("docs/" + locale + "README.md")).read_text(encoding="utf-8")
            self.assertIn("releases/v1.0.3.md", text)
            self.assertIn("releases/v1.0.4.md", text)
            self.assertIn(merged_scope, text)
            self.assertNotIn(stale_scope, text)
            self.assertIn("2026-10-16", text)
        self.assertIn("Package publication and operational deployment are separate.",
                      (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("Package publication does not include operational deployment",
                      (ROOT / "docs/releases/v1.0.4.md").read_text(encoding="utf-8"))

    def test_v132_publication_record_distinguishes_released_files_from_preparation(self):
        source = "f5e7c49554ff02771990a151e00b52f2abf3df0a"
        historical_base = "ef7748a78e6b466f67074708f5c14decf37f31d7"
        facts = (source, "2026-10-29", "2026-10-28T01:52:40Z",
                 "2026-10-28T01:55:11.612762Z", "2026-10-28T01:55:13.659910Z",
                 "https://github.com/abruption/session-peer/releases/tag/v1.3.2",
                 "https://pypi.org/pypi/session-peer/1.3.2/json")
        hashes = ("196552714b755c2ff755f3de507bd94a17ebd27b1c474ede83fbcc1301c488de",
                  "e1824b089d2d3e38e03783f5dfc6e2d5ec54fa9758837deb0ebcbbb567837065")
        direct_status = {
            "": ("Direct listener diagnostics published in v1.3.2", "unreleased change after v1.3.1"),
            "ko/": ("v1.3.2에 공개된 Direct 리스너 진단", "v1.3.1 이후의 미발행 변경"),
            "ja/": ("v1.3.2で公開されたDirectリスナー診断", "v1.3.1以降の未公開の変更"),
            "zh-CN/": ("v1.3.2中已发布的Direct监听器诊断", "v1.3.1之后尚未发布的变更"),
        }
        for locale, suffix in (("", ""), ("ko/", ".ko"), ("ja/", ".ja"), ("zh-CN/", ".zh-CN")):
            with self.subTest(locale=locale):
                notes = (ROOT / ("docs/" + locale + "releases/v1.3.2.md")).read_text(encoding="utf-8")
                publication, preparation = notes.split('<a id="v132-preparation-snapshot"></a>', 1)
                self.assertIn('<a id="v132-publication-record"></a>', publication)
                for fact in facts + hashes:
                    self.assertIn(fact, publication)
                for filename in ("session_peer-1.3.2-py3-none-any.whl", "session_peer-1.3.2.tar.gz"):
                    self.assertIn(filename, publication)
                self.assertNotIn(historical_base, publication)
                self.assertIn(historical_base, preparation)
                self.assertIn("2026-10-28", preparation)
                if not locale:
                    self.assertIn("against published v1.3.1", preparation)
                runbook = (ROOT / ("RELEASING" + suffix + ".md")).read_text(encoding="utf-8")
                self.assertIn('<a id="post-publication-documentation-check"></a>', runbook)
                record = runbook.split('<a id="post-publication-documentation-check"></a>', 1)[0]
                for fact in facts:
                    self.assertIn(fact, record)
                self.assertIn("#v132-publication-record", record)
                self.assertIn("prepare-release.yml", runbook)
                self.assertIn("publish.yml", runbook)
                paired = (ROOT / ("docs/" + locale + "paired-devices.md")).read_text(encoding="utf-8")
                published, obsolete = direct_status[locale]
                self.assertIn(published, paired)
                self.assertNotIn(obsolete, paired)
        english = (ROOT / "RELEASING.md").read_text(encoding="utf-8")
        checklist = english.split('<a id="post-publication-documentation-check"></a>', 1)[1].split("## v1.3.2 preparation", 1)[0]
        for instruction in ("independently verify the PyPI", "dated publication record",
                            "all four README editions", "normal documentation PR",
                            "Do not announce publication in advance", "published tags/assets"):
            self.assertIn(instruction, checklist)

    def test_historical_security_notes_keep_validation_and_limits_visible(self):
        for locale in ("", "ko/", "ja/", "zh-CN/"):
            text = (ROOT / ("docs/" + locale + "releases/v1.0.3.md")).read_text(encoding="utf-8")
            for marker in ("#161", "#249", "#250", "#251", "#252", "#253", "#254",
                           "#255", "#256", "#257", "#258", "1.0.3", "ACK", "20/21",
                           "GHSA-9x52-82cv-4c22", "GHSA-4rvw-q2vm-v4x3",
                           "GHSA-6xwm-5p7g-8v8q", "GHSA-2hjv-35jg-gghm",
                           "GHSA-646x-xjw9-mf6x", "CVE", "ProxyCommand", "LocalCommand"):
                with self.subTest(locale=locale, marker=marker):
                    self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
