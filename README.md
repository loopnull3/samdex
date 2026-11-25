# samdex

One UI 9.5 기반 Samsung DeX를 (공식적으로는 빠진) 다른 기기에서 돌리기 위한 도구 모음.
지금 타겟은 Galaxy Z Flip5. 전체 계획과 현재 상태는 **[docs/PLAN.md](docs/PLAN.md)** 참고.

순수 Python 표준 라이브러리로만 작성 — Termux에서 `pip install` 없이 바로 `python3 -m samdex ...`
로 실행된다.

## 구성

| 경로 | 역할 |
|---|---|
| `samdex/` | DEX/AXML/APK 분석 파이썬 패키지 (CLI: `python3 -m samdex`) |
| `tests/` | 손으로 만든 최소 dex/axml로 파서를 검증하는 테스트 |
| `magisk-module/` | floating_feature DEX_MODE 플래그 실험용 Magisk 모듈 |
| `bin/dex-recon.sh` | 루팅된 기기에서 돌리는 읽기 전용 recon 스크립트 |
| `docs/PLAN.md` | 단계별 실행 계획, 지금까지 확인된 사실, 다음 할 일 |

## CLI

```sh
python3 -m samdex strings  SystemUI.apk services.jar --grep 'DEX_MODE|FLIP|WINSET'
python3 -m samdex classes  framework.jar --grep DesktopMode
python3 -m samdex manifest base.apk
python3 -m samdex sig      SystemUI.apk              # 읽기 전용: 서명 지문만 확인
python3 -m samdex index    /pulled/one_ui8_system --out one_ui8.json.gz
python3 -m samdex scan     DeXHome.apk --target one_ui8.json.gz
```

## 테스트

```sh
python3 tests/test_dexfile.py
python3 tests/test_axml.py
```
