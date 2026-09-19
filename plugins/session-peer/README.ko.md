# session-peer Codex 플러그인

Python 3.10+에서 `session-peer[mcp]`를 설치한 다음, Codex 호스트의 PATH에서 `session-peer-mcp`를 사용할 수 있도록 설정합니다. 저장소 체크아웃에서 `codex plugin marketplace add /absolute/path/to/session-peer`를 실행한 후 `codex plugin add session-peer@session-peer`를 실행합니다. 체크아웃에는 `.agents/plugins/marketplace.json`이 포함되어 있습니다. 매니페스트는 번들된 `.mcp.json` stdio 서버를 등록합니다.

서버 환경의 `SESSION_PEER_MCP_CONFIG`를 절대 경로 정책 파일로 설정하십시오. 이것이 없으면 로컬 목록 조회만 허용됩니다. [MCP 설정 및 정책](../../docs/ko/mcp.md)을 참조하십시오. 이 번들을 설치한다고 해서 Python 의존성이 설치되거나 전송 권한이 부여되지는 않습니다.
