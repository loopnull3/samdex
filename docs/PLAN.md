# One UI 9.5 DeX on Galaxy Z Flip5 — 실행 계획

## 0. 전제 (2026-11-25 기준 확인된 것)

- **기기**: Galaxy Z Flip5. Samsung이 **공식적으로 DeX를 빼고 출시**했고, 보도에 따르면 이유는
  "발열(thermal) 설계상 판단"이라고 밝혔다 — 단순히 플래그 하나 꺼놓은 게 아니라
  **의도적 배제일 수 있다**는 뜻. ([SamMobile](https://sammobile.com/news/no-samsung-dex-support-galaxy-z-flip-5), [GSMArena](https://www.gsmarena.com/samsung_galaxy_z_flip5_might_get_dex_support-news-58552.php))
  → 그래서 이 계획은 "거의 확실히 됨"이 아니라 **단계별로 싼 실험부터 검증**하는 구조다.
- **루팅**: OEM 언락 가능, 아직 안 함.
- **One UI 9.5**: 아직 기기에 없음, 베타 트래커로 받을 예정.
- One UI 8(Android 16 네이티브 Desktop Mode) 이상에서는 DeX가 가상 디스플레이 기반으로
  재구축돼서, scrcpy `--new-display` 로도 미러링되는 구조로 바뀌었다 — 즉 **창 관리 핵심 로직은
  이미 프레임워크에 있고**, Flip5에서 막힌 건 대부분 "메뉴/진입점 노출" 레이어일 가능성이 높다.
  이게 맞다면 포팅 범위는 "프레임워크 포팅"이 아니라 "게이트 해제"로 훨씬 작아진다.

## 1. 선행 작업 (사용자가 기기/PC에서 직접 — 이 세션은 폰에 물리적으로 접근 못 함)

1. One UI 9.5 베타 설치 (베타 트래커 경로).
2. 설정 → 휴대전화 정보 → 7번 탭 → 개발자 옵션 → OEM 잠금해제 ON.
3. Download 모드 진입 → `adb reboot bootloader` 또는 볼륨키 조합 → 부트로더 언락
   (Knox 워런티 비트 영구적으로 올라감, 삼성페이/일부 금융앱 깨짐 — 알고 진행).
4. 언락된 기기에서 **스톡 AP 펌웨어의 boot.img(또는 init_boot.img, Android 16 GKI 기준)**를
   추출 → Magisk app으로 패치 → Odin으로 패치된 이미지만 AP 슬롯에 플래시.
5. 부팅 후 Magisk 루트 확인.

## 2. Recon (루팅 끝나면 이 레포의 스크립트로)

`bin/dex-recon.sh` 를 루팅된 기기에서 `su -c sh dex-recon.sh` 로 실행 (adb shell이든
Termux든 무관). **읽기 전용**, 아무것도 안 바꿈. 확인하는 것:

1. `floating_feature.xml` 안의 `SEC_FLOATING_FEATURE_COMMON_CONFIG_DEX_MODE` 류 플래그
2. `/system|vendor|product/etc/{permissions,sysconfig}/*.xml` 안의 DeX 관련 `<feature>` 선언
   (`pm list features`로도 동일 계열 확인)
3. DeX/desktop 관련 system property
4. SystemUI / Settings / framework-res / services.jar 안의 관련 문자열 상수

결과 파일(`/sdcard/Download/samdex-recon-*.txt`)을 저한테 다시 공유해주면 다음 단계를
정확히 짤 수 있다. **이 파일 없이는 2.5/3단계를 추측으로 짤 수밖에 없다.**

## 3. 플래그만으로 풀리는 경우 (제일 싼 경로)

`magisk-module/`: `SEC_FLOATING_FEATURE_COMMON_CONFIG_DEX_MODE` 값에 `standalone`이
없으면 추가하는 Magisk 모듈. systemless (Magisk의 자체 오버레이 마운트 사용,
수동 bind mount 없음) → 모듈 끄면 즉시 스톡 상태로 복귀.

- 설치: Magisk app → 모듈 → "저장소에서 설치" → `magisk-module/` 를 zip으로 묶어서 설치
  (`cd magisk-module && zip -r ../samdex-dexunlock.zip .`).
- `customize.sh`가 flag가 없거나 이미 `standalone`이면 그 자리에서 알려주고 멈춘다 —
  맹목적으로 아무 XML이나 건드리지 않음.
- 설치 로그: `/data/local/tmp/samdex-dex-install.log`.

같은 방식으로, recon에서 `<feature>` XML 선언이 원인으로 보이면 **그 정확한 feature 이름을
알려주면** 바로 같은 패턴의 두 번째 모듈을 만들어줄 수 있음 (몇 분 작업).

## 4. 플래그로 안 풀리는 경우 (더 무거운 경로)

SystemUI/Settings/services.jar 안에 `FLIP`/모델ID/`WINSET` 하드코딩 체크가 있다면:

1. `python3 -m samdex strings SystemUI.apk --grep 'DEX|FLIP|WINSET'` 로
   정확히 어떤 클래스·메서드가 그 문자열을 로드하는지 특정 (레포의 `samdex/` 패키지,
   pure-stdlib, Termux에서 `pip install` 없이 바로 돌아감).
2. 그 메서드의 로직을 smali 레벨에서 패치 — 이건 baksmali(디컴파일)/smali(재컴파일)
   jar가 필요한데, 이건 Java 툴(Google Maven의 `com.android.tools.smali` 아티팩트)이라
   pure-Termux로는 못 피한다. `apt install openjdk-21` 후 jar 받아서 사용.
3. 패치된 dex를 다시 APK에 넣고 **재서명**은 못 함(플랫폼 키가 없음) → 패치된 시스템 앱은
   Magisk 오버레이로 `/system`에 올리는 방식으로만 설치 가능 (서명 우회/위조 기법은
   이 프로젝트에서 다루지 않음 — 그 방향은 안전상 돕지 않음).
4. `samdex/apiindex.py` + `samdex/apiscan.py`: 9.5 donor APK가 One UI 8 프레임워크에 없는
   클래스/메서드를 참조하는지 미리 스캔하는 도구. 3단계까지 가면 유용함
   (`python3 -m samdex scan DeXHome.apk --target <One UI 8 framework dump>`).

## 5. 플래그/코드까지 다 뚫어도 남는 벽

일부 DeX 기능(특정 하드웨어 제어 API 등)은 `signature`/`signatureOrSystem` 권한이라
플랫폼 키로 서명된 앱만 호출 가능. 패치한 APK는 그 키가 없어서 거기서 `SecurityException`이
날 수 있음. 이건:

- 그 기능만 포기하고 나머지(창 관리, 타스크바, 데스크톱 UI)로 만족, 또는
- 루팅된 테스트 기기에서 LSPosed/Xposed로 그 체크 하나를 후킹해서 넘기는 정도까지만.
- **서명을 위조/전치(transplant)해서 플랫폼 신뢰를 흉내 내는 방향은 하지 않음** — 같은 메커니즘이
  일반적인 APK 서명 위조 공격과 동일해서, 의도가 뭐든 그 코드는 안 만든다.
  (`samdex/apksig.py`는 그래서 읽기 전용 서명 진단 도구로만 존재함.)

## 지금 레포에 있는 것

```
samdex/            pure-stdlib 파이썬 패키지 (Termux에서 pip 없이 바로 동작)
  dexfile.py        DEX 파서 (문자열/클래스/메서드/필드/바이트코드 명령어 디코더)
  apiindex.py       jar/apk/dex 모음 -> 클래스/메서드/필드 인덱스 (.json.gz 저장)
  apiscan.py        donor APK가 target 프레임워크에 없는 API를 참조하는지 스캔 (3단계용)
  axml.py           바이너리 AndroidManifest.xml 파서 + minSdk/targetSdk 제자리 패치
  apksig.py         읽기 전용 APK 서명 진단 (v1/v2/v3 signer cert fingerprint)
  strconst.py       "이 문자열, 어느 클래스·메서드가 로드하나" 역추적
  __main__.py       CLI: strings / classes / sig / manifest / index / scan
tests/             위 파서들 검증용 (외부 툴 없이 손으로 만든 최소 dex/axml로 ground-truth 비교)
magisk-module/     floating_feature DEX_MODE 플래그 실험용 Magisk 모듈
bin/dex-recon.sh   루팅된 기기에서 돌리는 읽기 전용 recon 스크립트
```

## 다음에 사용자가 할 일 (체크리스트)

- [ ] 9.5 베타 설치
- [ ] OEM 언락 + Magisk 루팅
- [ ] `bin/dex-recon.sh` 실행, 결과 파일 공유
- [ ] (결과 보고 2/2.5/3단계 중 뭘 할지 같이 결정)
