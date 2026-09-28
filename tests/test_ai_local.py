"""AI 해석(src/ai_local.py) 테스트 — Claude Code는 실제로 부르지 않고 subprocess 를 흉내낸다."""

from __future__ import annotations

import json
import subprocess

import pytest

from src import ai_local
from src.report import add_markdown, _new_document


def ok_json(text: str = "## 한 줄 결론\n동의합니다.", **extra) -> str:
    payload = {"type": "result", "subtype": "success", "is_error": False,
               "result": text, "duration_ms": 147764,
               "modelUsage": {"claude-opus-5-5": {}}}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


class Test응답해석:
    def test_정상_응답(self):
        r = ai_local.parse_result(ok_json())
        assert r.text.startswith("## 한 줄 결론")
        assert r.model == "claude-opus-5-5"
        assert round(r.seconds) == 148

    def test_로그가_앞에_섞여도_마지막_줄을_읽는다(self):
        r = ai_local.parse_result("경고 메시지\n" + ok_json())
        assert "동의" in r.text

    def test_JSON이_아니면_오류(self):
        with pytest.raises(ai_local.AIError):
            ai_local.parse_result("not json")

    def test_빈_응답이면_오류(self):
        with pytest.raises(ai_local.AIError):
            ai_local.parse_result("")

    def test_사용_한도는_알아듣게(self):
        with pytest.raises(ai_local.AIError, match="한도"):
            ai_local.parse_result(ok_json("Usage limit reached", is_error=True))

    def test_로그인_필요는_알아듣게(self):
        with pytest.raises(ai_local.AIError, match="로그인"):
            ai_local.parse_result(ok_json("Please run /login", is_error=True))


class Test안전장치:
    def test_웹검색만_허용하고_파일수정과_명령실행은_막는다(self):
        cmd = ai_local.build_command("claude")
        allowed = cmd[cmd.index("--allowedTools") + 1: cmd.index("--disallowedTools")]
        assert set(allowed) == {"WebSearch", "WebFetch"}
        blocked = cmd[cmd.index("--disallowedTools") + 1:]
        for tool in ("Bash", "PowerShell", "Edit", "Write", "Read"):
            assert tool in blocked
        assert "--no-session-persistence" in cmd
        assert "-p" in cmd

    def test_지침_파일을_시스템_지침으로_붙인다(self):
        cmd = ai_local.build_command("claude")
        assert cmd[cmd.index("--append-system-prompt-file") + 1] == str(ai_local.INSTRUCTIONS_PATH)

    def test_claude가_없으면_사용_불가(self, monkeypatch):
        monkeypatch.setattr(ai_local.shutil, "which", lambda name: None)
        assert ai_local.available() is False
        with pytest.raises(ai_local.AIError, match="찾지 못했습니다"):
            ai_local.interpret("요약")


class Test실행:
    def fake_run(self, captured: dict, stdout: str = "", returncode: int = 0, stderr: str = ""):
        def run(cmd, input, capture_output, cwd, timeout):
            captured.update(cmd=cmd, input=input.decode("utf-8"), cwd=cwd, timeout=timeout)
            return subprocess.CompletedProcess(cmd, returncode, stdout.encode("utf-8"),
                                               stderr.encode("utf-8"))
        return run

    def test_요약을_입력으로_넘기고_임시폴더에서_실행(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(ai_local.shutil, "which", lambda name: "claude")
        monkeypatch.setattr(ai_local.subprocess, "run", self.fake_run(captured, ok_json()))
        r = ai_local.interpret("# 삼성전자 — 앱 분석 요약")
        assert "동의" in r.text
        assert captured["input"].endswith("# 삼성전자 — 앱 분석 요약")
        assert "특례" in captured["input"]
        assert "stock_ai_" in captured["cwd"]           # 저장소가 아닌 빈 임시 폴더
        assert captured["timeout"] == ai_local.TIMEOUT_SEC

    def test_시간초과(self, monkeypatch):
        def run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="claude", timeout=1)
        monkeypatch.setattr(ai_local.shutil, "which", lambda name: "claude")
        monkeypatch.setattr(ai_local.subprocess, "run", run)
        with pytest.raises(ai_local.AIError, match="끝나지 않았습니다"):
            ai_local.interpret("요약")

    def test_실행_오류는_stderr를_보여준다(self, monkeypatch):
        monkeypatch.setattr(ai_local.shutil, "which", lambda name: "claude")
        monkeypatch.setattr(ai_local.subprocess, "run",
                            self.fake_run({}, stdout="", returncode=1, stderr="boom"))
        with pytest.raises(ai_local.AIError, match="boom"):
            ai_local.interpret("요약")


class TestWord변환:
    MD = """## 한 줄 결론
앱 의견에 **동의**합니다.

---

## 피어 비교
- **SK하이닉스**: 메모리 경쟁사
| 항목 | 삼성 | 하이닉스 |
|---|---|---|
| PER | 12.8배 | 31.7배 |
"""

    def test_제목_목록_표_굵게(self):
        doc = _new_document()
        add_markdown(doc, self.MD)
        headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
        assert headings == ["한 줄 결론", "피어 비교"]
        bullets = [p for p in doc.paragraphs if p.style.name == "List Bullet"]
        assert bullets[0].runs[0].bold and bullets[0].runs[0].text == "SK하이닉스"
        assert len(doc.tables) == 1
        table = doc.tables[0]
        assert [c.text for c in table.rows[0].cells] == ["항목", "삼성", "하이닉스"]
        assert [c.text for c in table.rows[1].cells] == ["PER", "12.8배", "31.7배"]
        assert not any("---" in p.text for p in doc.paragraphs)
