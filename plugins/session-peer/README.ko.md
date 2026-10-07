# session-peer Codex 플러그인

Python 3.10 이상 환경에서 `session-peer[mcp]`를 설치한 뒤, Codex 호스트의 PATH에서 `session-peer-mcp` 명령을 찾을 수 있도록 설정하십시오. 저장소를 체크아웃한 디렉터리에서 `codex plugin marketplace add /absolute/path/to/session-peer`를 실행한 다음 `codex plugin add session-peer@session-peer`를 실행하십시오. 체크아웃에는 `.agents/plugins/marketplace.json`이 포함되어 있습니다. 매니페스트는 플러그인에 포함된 `.mcp.json`에 정의된 표준 입출력(stdio) 서버를 등록합니다.

서버 환경 변수 `SESSION_PEER_MCP_CONFIG`에 정책 파일의 절대 경로를 설정하십시오. 이 변수를 설정하지 않으면 로컬 세션 목록 조회만 허용됩니다. [MCP 설정 및 정책](../../docs/ko/mcp.md)을 참조하십시오. 이 번들을 설치해도 Python 의존성이 설치되거나 전송 권한이 부여되지는 않습니다.
