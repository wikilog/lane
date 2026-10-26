# Lane always-on

이 세션이 `/lane` 워커(프롬프트가 "You are a /lane worker"로 시작)이면 오케스트레이션하지 말고 맡은 항목만 한다.
비대화형 `codex exec`로 받은 단발 작업(프롬프트가 브리프·검증·리뷰 지시)도 워커로 보고 `/lane`으로 다시 넘기지 않는다.

그 외 모든 대화: 구현·문서·리뷰·설계·보안·조사·코딩이 섞이거나 이 호스트 레인이 아니면 `/lane`을 기다리지 않는다. `$HOME/.agents/skills/lane/SKILL.md`를 읽고 `probe.py` → `plan.py` → `run.py --execute --cwd` 를 실행한다. `here` 항목만 이 세션에서 한다.

짧은 질문(파일 작업 없음)과, 이 호스트 레인의 작은 수정은 여기서 끝낸다. 워커가 죽으면 `run.py`가 같은 모델 1회 후 Qwen→MiniMax로 재시도한다. 구현은 Claude로 넘기지 않는다.
