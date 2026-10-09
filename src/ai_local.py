"""AI 해석 — 이 PC에 설치된 Claude Code(구독 로그인)를 호출한다.

추가 요금 없이 클로드 구독을 쓰는 유일한 경로다. 앱을 이 PC에서 run.bat 으로 켰을 때만 동작하고,
인터넷에 배포된 앱(Streamlit Cloud)에는 claude 명령이 없으므로 available() 이 False 가 되어
화면은 자동으로 '요약 복사' 방식으로 돌아간다.

안전 장치:
  * 웹 검색·웹 페이지 읽기만 허용하고 파일 수정·명령 실행 도구는 막는다.
  * 빈 임시 폴더에서 실행해 저장소 파일을 건드릴 수 없게 한다.
  * 대화 기록을 남기지 않는다 (--no-session-persistence).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

INSTRUCTIONS_PATH = Path(__file__).resolve().parent.parent / "docs" / "claude_project_instructions.md"
SAVE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "ai"
ONE_LINER_MAX = 200
TIMEOUT_SEC = 420
ALLOWED_TOOLS = ["WebSearch", "WebFetch"]
BLOCKED_TOOLS = ["Bash", "PowerShell", "Edit", "Write", "NotebookEdit", "Read", "Glob", "Grep", "Agent"]

REQUEST = """아래 '앱 분석 요약'을 받았습니다. 지침의 '앱 분석 요약 입력 (특례)'에 따라 해석해 주세요.

출력 형식 (한국어 마크다운, 이 순서, 서론·맺음 인사 없이 바로 시작):
## 한 줄 결론
## 지표 선정과 이익 기준 검토 (Step 3)
## 피어 비교 (Step 4) — 피어 2~3개, 표 필수, 수치마다 [출처, 기준일]
## 프리미엄·디스카운트 요인 (Step 7) — 할증/할인 근거 각 2~3개와 멀티플 조정 폭
## 앱 목표주가 검토 (Step 9) — 밴드·이익 전제가 타당한지, 조정이 필요하면 조정안
## 투자의견과 논리 (Step 10) — 앱의 규칙 기반 의견에 동의/보완, 핵심 가정 3개, 의견 변경 조건, 6~12개월 촉매, 가장 큰 리스크 2개
## 이번 해석의 한계

웹 검색은 8회 이내로 피어 수치와 최근 1년 내 사실 확인에만 쓰세요.
요약에 있는 수치는 다시 찾지 말고, 요약과 다른 숫자를 만들어내지 마세요.
마지막 줄: "이 분석은 투자 판단을 돕는 참고 자료이며, 투자 결정과 결과는 본인 책임입니다."

---

"""


class AIError(RuntimeError):
    """해석을 받지 못했을 때. 메시지는 화면에 그대로 보여줄 수 있는 한국어."""


@dataclass(frozen=True)
class Interpretation:
    text: str            # 마크다운 본문
    seconds: float       # 걸린 시간
    model: str = ""
    created: str = ""    # 생성 시각 'YYYY-MM-DD HH:MM' (저장본 표시용)


def claude_path() -> str | None:
    return shutil.which("claude")


def available() -> bool:
    """이 PC에서 Claude Code를 부를 수 있는가 (배포된 웹앱에서는 False)."""
    return claude_path() is not None and INSTRUCTIONS_PATH.exists()


def build_command(exe: str) -> list[str]:
    return [
        exe, "-p",
        "--output-format", "json",
        "--append-system-prompt-file", str(INSTRUCTIONS_PATH),
        "--allowedTools", *ALLOWED_TOOLS,
        "--disallowedTools", *BLOCKED_TOOLS,
        "--no-session-persistence",
    ]


def parse_result(stdout: str) -> Interpretation:
    """--output-format json 결과 한 덩어리를 해석한다."""
    try:
        payload = json.loads(stdout.strip().splitlines()[-1] if stdout.strip() else "")
    except (json.JSONDecodeError, IndexError) as exc:
        raise AIError("Claude Code 응답을 읽지 못했습니다.") from exc

    text = str(payload.get("result") or "").strip()
    if payload.get("is_error") or not text:
        reason = text or str(payload.get("subtype") or "알 수 없는 오류")
        if "limit" in reason.lower():
            raise AIError(f"구독 사용 한도에 걸렸습니다. 잠시 후 다시 시도하세요. ({reason})")
        if "login" in reason.lower() or "auth" in reason.lower():
            raise AIError("Claude Code 로그인이 필요합니다. 터미널에서 `claude` 를 한 번 실행해 로그인하세요.")
        raise AIError(f"해석을 받지 못했습니다: {reason}")

    models = payload.get("modelUsage") or {}
    return Interpretation(
        text=text,
        seconds=float(payload.get("duration_ms") or 0) / 1000.0,
        model=next(iter(models), ""),
    )


def interpret(handoff_text: str) -> Interpretation:
    """앱 분석 요약을 Claude Code에 넘기고 해석(마크다운)을 받는다. 실패 시 AIError."""
    exe = claude_path()
    if exe is None:
        raise AIError("이 PC에서 Claude Code(claude 명령)를 찾지 못했습니다.")
    if not INSTRUCTIONS_PATH.exists():
        raise AIError(f"지침 파일이 없습니다: {INSTRUCTIONS_PATH}")

    with tempfile.TemporaryDirectory(prefix="stock_ai_") as workdir:
        try:
            proc = subprocess.run(
                build_command(exe),
                input=(REQUEST + handoff_text).encode("utf-8"),
                capture_output=True,
                cwd=workdir,
                timeout=TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired as exc:
            raise AIError(f"{TIMEOUT_SEC // 60}분 안에 해석이 끝나지 않았습니다. 다시 시도해 보세요.") from exc
        except OSError as exc:
            raise AIError(f"Claude Code를 실행하지 못했습니다: {exc}") from exc

    stdout = proc.stdout.decode("utf-8", errors="replace")
    if proc.returncode != 0 and not stdout.strip():
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise AIError(f"Claude Code 실행 오류: {err[-300:] or proc.returncode}")
    return parse_result(stdout)


# ------------------------------------------------------------- 저장·요약

def save_key(region: str, code: str, price_date: str) -> str:
    """같은 종목·같은 가격 기준일이면 같은 해석을 다시 쓴다."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", f"{region}_{code}_{price_date or 'latest'}")


def save(key: str, result: Interpretation, base: Path | None = None) -> Interpretation:
    """해석을 디스크에 저장한다. 생성 시각이 비어 있으면 채운다. 저장 실패는 무시 (화면엔 그대로 보인다)."""
    if not result.created:
        result = Interpretation(result.text, result.seconds, result.model,
                                dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    folder = base or SAVE_DIR
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{key}.json").write_text(json.dumps(asdict(result), ensure_ascii=False),
                                            encoding="utf-8")
    except OSError:
        pass
    return result


def load_saved(key: str, base: Path | None = None) -> Interpretation | None:
    path = (base or SAVE_DIR) / f"{key}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Interpretation(text=str(data["text"]), seconds=float(data.get("seconds") or 0),
                              model=str(data.get("model") or ""), created=str(data.get("created") or ""))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def one_liner(text: str) -> str:
    """'## 한 줄 결론' 아래 첫 문단. 제목이 없으면 첫 일반 문단. 굵게 기호는 지운다."""
    lines = text.splitlines()
    start = next((i + 1 for i, ln in enumerate(lines) if ln.strip().startswith("#") and "결론" in ln), 0)
    for ln in lines[start:]:
        s = ln.strip()
        if not s or s.startswith(("#", "|", "---")):
            if s.startswith("#") and start:
                break
            continue
        s = s.lstrip("-* ").replace("**", "")
        return s if len(s) <= ONE_LINER_MAX else s[:ONE_LINER_MAX - 1] + "…"
    return ""
