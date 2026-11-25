# One UI 9.5 DeX를 (9.5가 안 올라가는) Galaxy Z Flip5에 이식 — 실행 계획

## 0. 전제 (2026-11-25 기준 확인된 것, 1차 계획에서 정정됨)

- **기기**: Galaxy Z Flip5 (2023, Android 13 출시). Samsung의 "4회 OS 업그레이드" 정책상
  **One UI 9(Android 17)가 플립5의 마지막 메이저 업그레이드로 확정**됐고, 이미 안정판으로
  배포됨. **One UI 9.5는 플립5 제외 대상으로 커뮤니티 예상 리스트에 일관되게 빠져 있음**
  ([SammyFans](https://www.sammyfans.com/2026/11/13/samsung-one-ui-9-5-eligible-devices/),
  [Android Authority](https://androidauthority.com/galaxy-z-fold-5-flip-5-one-ui-9-global-rollout-3725729)).
  → **플립5 자체에 9.5를 OTA/베타로 설치하는 경로는 없다.** 9.5 DeX를 플립5에서 쓰려면
  **다른(9.5 지원) 기기의 펌웨어에서 DeX 관련 컴포넌트를 뽑아 플립5(One UI 9)에 이식**해야 함.
- Samsung은 플립5에 DeX를 안 넣은 이유로 "발열(thermal) 설계상 판단"을 든 적이 있음
  ([SamMobile](https://sammobile.com/news/no-samsung-dex-support-galaxy-z-flip-5)) — 이건
  9.5 여부와 별개로, **One UI 9에서도 DeX 메뉴 자체가 모델 단위로 막혀 있을 가능성**을 뜻함.
  그래서 이 계획은 두 개의 독립된 작업으로 나뉜다 (아래 1단/2단).
- **루팅**: OEM 언락 가능, 아직 안 함. 현재 펌웨어는 (추정) One UI 9 안정판.
- One UI 8(Android 16) 이상에서는 DeX가 가상 디스플레이 기반으로 재구축돼서 scrcpy
  `--new-display` 로도 미러링되는 구조 — **창 관리 핵심 로직은 이미 Android 17 프레임워크에
  있을 가능성이 높고**, 9.5가 더하는 건 주로 UI(상단 트레이, 창 스냅, Samsung Internet
  데스크톱 모드) 쪽. 같은 Android 메이저 버전(17) 안의 포팅이라 ABI/API 격차는 비교적 작을 것.

## 작업 트랙 두 개 (독립적으로 진행 가능)

- **트랙 A — 게이트 해제**: 플립5 자체(One UI 9)에서 DeX 메뉴/기능이 모델 단위로 막혀 있는지
  확인하고 플래그/선언만으로 풀리는지 테스트. 기기+루팅만 있으면 됨, 9.5 펌웨어 필요 없음.
  (아래 1~3단, 기존 계획과 동일, "9.5" → "현재 One UI 9"로 대상만 바뀜)
- **트랙 B — 9.5 DeX 컴포넌트 이식**: 9.5가 실제로 올라가는 기기(현재는 Galaxy S26 베타,
  2027년 초 S27부터 정식)의 **펌웨어 파일(AP.tar.md5)만** 받아서 PC/Termux에서 풀고
  DeX 관련 APK/리소스를 추출 — **이건 그 기기를 실제로 갖고 있을 필요 없음, 펌웨어 파일만
  있으면 됨** (samfirm/frija 같은 도구로 다운로드, 플래싱 안 함). 추출한 걸
  `samdex scan`으로 플립5의 One UI 9 프레임워크와 비교해서 뭐가 빠지는지 확인.

## 트랙 A — 1. 선행 작업 (사용자가 기기/PC에서 직접 — 이 세션은 폰에 물리적으로 접근 못 함)

1. 현재 펌웨어가 One UI 9 안정판인지 확인 (설정 → 소프트웨어 업데이트 → 다운로드 및 설치,
   최신까지 올려둠). **9.5는 안 뜬다 — 그게 정상.**
2. 설정 → 휴대전화 정보 → 7번 탭 → 개발자 옵션 → OEM 잠금해제 ON.
3. Download 모드 진입 → `adb reboot bootloader` 또는 볼륨키 조합 → 부트로더 언락
   (Knox 워런티 비트 영구적으로 올라감, 삼성페이/일부 금융앱 깨짐 — 알고 진행).
4. 언락된 기기에서 **스톡 AP 펌웨어의 boot.img(또는 init_boot.img, Android 17 GKI 기준)**를
   추출 → Magisk app으로 패치 → Odin으로 패치된 이미지만 AP 슬롯에 플래시.
5. 부팅 후 Magisk 루트 확인.

## 트랙 B — 1. 선행 작업

**실제 기기(Galaxy S26, One UI 9.5 베타 설치됨, 루팅 안 됨) 보유 확정** → 펌웨어 파일을
풀 필요 없이 **루팅 없이 `adb pull`로 바로 추출** 가능. 시스템 앱 APK는 보통
world-readable이라 USB 디버깅만 켜져 있으면 root 없이도 읽힘.

1. S26에서 설정 → 휴대전화 정보 → 7번 탭 → 개발자 옵션 → USB 디버깅 ON.
2. PC에 `adb`(Android platform-tools) 설치, USB로 연결, 디버깅 허용 팝업 승인.
3. `bash bin/dex-pull-donor.sh` 실행 (이 레포의 스크립트, **PC에서** 실행 — 이 세션은 폰에
   물리적으로 연결 못 함). `pm list packages -f`로 DeX/desktopmode/SystemUI/Internet 관련
   패키지를 찾아서 해당 APK를 자동으로 `adb pull`. `floating_feature.xml`/`services.jar`/
   `framework.jar`도 되는 대로 같이 시도 (루팅 안 됐으니 막힐 수도 있음, 그건 괜찮음 —
   그 파일들은 S26 쪽 분석에 필수는 아니고, 그게 필요해지면 그때 가서 루팅하거나
   AP 펌웨어를 풀면 됨 — 아래 "펌웨어 직접 풀기" 참고).
4. 나온 `donor-s26-9.5/` 폴더(또는 그 안의 apk 몇 개)를 이 세션에 올려주면 바로
   `python3 -m samdex strings/classes/scan` 으로 분석 시작.

### (대안/보강) 루팅했거나 adb pull이 막히는 파일이 있을 때: 펌웨어 직접 풀기

`adb pull`이 권한으로 막히는 파일(주로 `/vendor` 아래 일부, 또는 odex 전용이라 raw dex가
없는 jar)이 있으면, samfirm/frija류 도구로 받은 `AP_*.tar.md5`를 직접 풀어서 꺼낼 수도
있음 — `tar`로 풀면 `super.img.lz4` 등이 나오고, `lpunpack`으로 `system.img`,
`system_ext.img`, `product.img`, `vendor.img`로 쪼갠 다음 `erofsfuse`(최신 기기는 EROFS가
흔함) 또는 `e2fsprogs`로 마운트해서 꺼냄. S26을 실제로 갖고 있으니 지금은 이 경로는
우선순위가 낮음 — adb pull로 막힌 파일이 나오면 그때 구체화.

## 트랙 A — 2. Recon (루팅 끝나면 이 레포의 스크립트로)

`bin/dex-recon.sh` 를 루팅된 기기에서 `su -c sh dex-recon.sh` 로 실행 (adb shell이든
Termux든 무관). **읽기 전용**, 아무것도 안 바꿈. 확인하는 것:

1. `floating_feature.xml` 안의 `SEC_FLOATING_FEATURE_COMMON_CONFIG_DEX_MODE` 류 플래그
2. `/system|vendor|product/etc/{permissions,sysconfig}/*.xml` 안의 DeX 관련 `<feature>` 선언
   (`pm list features`로도 동일 계열 확인)
3. DeX/desktop 관련 system property
4. SystemUI / Settings / framework-res / services.jar 안의 관련 문자열 상수

결과 파일(`/sdcard/Download/samdex-recon-*.txt`)을 저한테 다시 공유해주면 다음 단계를
정확히 짤 수 있다. **이 파일 없이는 2.5/3단계를 추측으로 짤 수밖에 없다.**

## 트랙 A — 3. 플래그만으로 풀리는 경우 (제일 싼 경로)

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

## 트랙 A — 4. 플래그로 안 풀리는 경우 (더 무거운 경로)

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

## 트랙 B — 2. 이식 (트랙 A에서 기본 DeX 게이트가 풀린 뒤)

트랙 A로 플립5에서 기본 DeX(One UI 9 수준)가 뜨는 걸 확인했으면, 9.5 "느낌"
(상단 트레이, 창 스냅, Samsung Internet 데스크톱 모드)은 트랙 B에서 뽑은 컴포넌트를
덧씌워서 가져옴:

1. `samdex/apiindex.py` + `samdex/apiscan.py`: 9.5 donor APK(SystemUI, DeXHome, Samsung
   Internet 등)가 플립5의 One UI 9 프레임워크에 없는 클래스/메서드를 참조하는지 스캔.
   같은 Android 17 메이저 버전이라 격차가 작을 걸로 기대하지만 실제로 돌려봐야 안다.
   (`python3 -m samdex index <플립5에서 뽑은 /system,/vendor,/product> --out oneui9.json.gz`
   `python3 -m samdex scan DeXHome.apk SystemUI.apk --target oneui9.json.gz`)
2. 리포트에서 "A: drop-in"이면 해당 APK를 Magisk 오버레이로 덮어쓰기만 하면 됨(서명은
   그대로 두고 priv-app 권한 화이트리스트만 맞추면 됨 — 서명 위조 아님, 표준 systemless
   오버레이).
3. "B: shimmable"이면 빠진 몇 개 클래스/메서드를 더미로 채워주는 shim dex를 짜서 같이
   오버레이 — 이것도 레포 도구로 리포트가 구체적인 클래스/시그니처까지 알려주니 바로 작성
   가능.
4. "C: heavy"면 서비스 레벨(services.jar) 포팅까지 필요해서 범위가 커짐 — 이 경우는 리포트
   받은 다음 실제로 뭐가 걸리는지 보고 범위를 다시 정하는 게 낫다.

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
bin/dex-recon.sh       (트랙 A) 루팅된 플립5에서 돌리는 읽기 전용 recon 스크립트
bin/dex-pull-donor.sh  (트랙 B) PC에서 adb로 S26 DeX 컴포넌트 추출 (루팅 불필요)
```

## 다음에 사용자가 할 일 (체크리스트)

트랙 A (기기):
- [ ] OEM 언락 + Magisk 루팅 (현재 One UI 9 그대로, 9.5 불필요)
- [ ] `bin/dex-recon.sh` 실행, 결과 파일 공유
- [ ] (결과 보고 플래그 패치 / feature XML 패치 / smali 패치 중 뭘 할지 같이 결정)

트랙 B (S26, 병행 가능, 루팅 불필요):
- [ ] S26 USB 디버깅 ON, PC에 adb 설치
- [ ] `bash bin/dex-pull-donor.sh` 실행
- [ ] 나온 폴더/apk 몇 개를 이 세션에 올려서 `samdex strings/scan`으로 분석 시작
