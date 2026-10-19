# Garmin Data Pipeline for AI Analysis

**Garmin Connect → Linux Data Collection → GitHub Archive → Web ChatGPT Projects**

This repository is a reusable pipeline for archiving Garmin activity, wellness and performance data for **AI-assisted analysis in ChatGPT on the web**. Each ChatGPT **Project** can have its own instructions and analytical focus (training, recovery, race preparation, or data validation), while using the same trusted data archive.

이 저장소는 Garmin Connect의 운동·건강·퍼포먼스 데이터를 자동으로 수집하여 **웹 ChatGPT의 프로젝트별 지침(Project instructions)에 따라 AI 분석**에 활용하기 위한 데이터 파이프라인입니다. 하나의 저장소를 여러 GPT 프로젝트가 각기 다른 분석 목적에 맞게 참조하도록 설계했습니다.

> **Scope / 범위:** The Linux automation collects and pushes files. **ChatGPT analysis is a separate, user-initiated or separately configured step.** Merely naming a private GitHub repository in Project instructions does not grant ChatGPT access, and binary FIT files require appropriate parsing.
>
> Linux 자동화는 **수집·보관·Git Push**까지 수행합니다. AI 분석은 프로젝트에서 별도로 요청해야 하며, Private GitHub 접근 권한과 FIT 바이너리 파싱 가능 여부를 각각 확인해야 합니다.

**Language / 언어:** [한국어 가이드](#한국어-가이드) · [English guide](#english-guide) · [기존 상세 운영 문서](#기존-상세-운영-문서--preserved-legacy-documentation)

---

## 한국어 가이드

### 1. 프로젝트 개요와 사용 목적

이 프로젝트는 특정 장비나 한 번의 훈련을 분석하기 위한 프로그램이 아니라, Garmin Connect 데이터를 꾸준히 축적해 **시간이 지날수록 풍부해지는 개인 운동 데이터 저장소**를 구축하는 것을 목적으로 합니다.

**활용 시나리오**

- **훈련 분석 프로젝트:** Activity FIT를 중심으로 페이스·심박·랩·케이던스·주간 훈련량·강도 분포를 비교
- **회복/컨디션 프로젝트:** HRV·수면·안정시 심박·스트레스·Body Battery와 최근 훈련 부하를 결합
- **마라톤/레이스 프로젝트:** 최근 8~12주 기록, 장거리주, 인터벌, 레이스 결과를 종합해 목표 페이스와 전략 검토
- **데이터 품질 프로젝트:** FIT·JSON 간 날짜/단위/누락/센서 오류/중복 데이터를 점검

위 프로젝트들은 동일한 GitHub 저장소를 참조하되, 각각의 **ChatGPT 프로젝트 지침**을 다르게 적용할 수 있습니다. 데이터 파이프라인 자체는 모델·프롬프트·특정 AI 서비스에 종속되지 않습니다.

### 2. 전체 아키텍처

```text
Garmin Watch / Cycling Device / Sensors
                  │ Device synchronization
                  ▼
             Garmin Connect
                  │ Authenticated API session
                  ▼
        Linux VM (Rocky Linux 9)
        ┌────────────────────────────────────────────┐
        │ scripts/auth.py        최초 로그인/토큰 저장│
        │ scripts/sync_fit.py    Activity FIT 수집    │
        │ scripts/sync_health.py Wellness/Performance │
        │ scripts/sync_wellness_raw.py Wellness FIT   │
        │ scripts/run_sync.sh    수집 + Git 동기화    │
        └────────────────────────────────────────────┘
                  ▲
       systemd timer / service
          매일 00:00 KST
                  │
                  ▼
         GitHub Private Repository
      activities/   wellness/   wellness_raw/
                   performance/
                  │
        Authorized file / repository access
                  ▼
       Web ChatGPT: separate Projects
        ├─ Training Performance Analysis
        ├─ Recovery & Readiness Analysis
        └─ Marathon Race Planning
```

**처리 흐름**

1. Garmin 기기를 Garmin Connect와 동기화합니다. 기기가 서버에 직접 연결되는 구조는 아닙니다.
2. Linux 서버의 systemd 타이머가 정해진 시간에 `run_sync.sh`를 시작합니다.
3. 이전에 저장한 Garmin 인증 토큰으로 수집기들이 Garmin Connect 데이터를 조회합니다.
4. Activity FIT, Wellness 원본 FIT, 가공된 Wellness/Performance JSON을 **연·월·일** 디렉터리에 저장합니다.
5. `run_sync.sh`가 Git 변경사항을 Commit하고 Private Repository의 `main`에 Push합니다.
6. 사용자가 ChatGPT 프로젝트에서 질문하면, **해당 프로젝트에서 실제로 접근 가능한 파일만** 분석에 사용합니다.

### 3. 저장소 디렉터리 및 소스 파일 구성

```text
repository/
├── README.md
├── requirements.txt
├── .gitignore
├── scripts/
│   ├── auth.py
│   ├── sync_fit.py
│   ├── sync_health.py
│   ├── sync_wellness_raw.py
│   └── run_sync.sh
├── systemd/
│   ├── garmin-fit-sync.service
│   └── garmin-fit-sync.timer
├── activities/
│   └── YYYY/MM/DD/{activityId}.fit
├── wellness/
│   └── YYYY/MM/DD/
│       ├── sleep.json
│       ├── hrv.json
│       ├── heart_rate.json
│       ├── stress.json
│       ├── body_battery.json
│       └── daily_stats.json
├── wellness_raw/
│   └── YYYY/MM/DD/{id}_{type}.fit
└── performance/
    ├── YYYY/MM/DD/training_readiness.json
    └── snapshots/YYYY/MM/DD/
        ├── vo2max.json
        ├── training_status.json
        └── load_focus.json

# 로컬 서버 전용 (Git에 올리지 않음)
.collector.env
.venv/
~/.garminconnect/garmin_tokens.json
~/.ssh/<private-deploy-key>
```

| 파일 | 역할 | 주요 구현 방식 |
| --- | --- | --- |
| `scripts/auth.py` | Garmin Connect 최초 인증 | ID/비밀번호/MFA 입력, 인증 토큰을 Repository **외부**에 보관 |
| `scripts/sync_fit.py` | Activity 원본 다운로드 | Garmin Original 다운로드 ZIP에서 FIT 1개 추출, 활동 ID 중복 방지, 날짜별 저장, `--days` / `--since` / `--until` |
| `scripts/sync_health.py` | Wellness/Performance API 조회 | 날짜별 JSON, 변경된 내용만 갱신, 계산 지표 스냅샷 별도 저장 |
| `scripts/sync_wellness_raw.py` | Wellness 원본 FIT 수집 | Wellness ZIP 응답을 메모리에서 검증하고 개별 FIT로 추출; 신규 ZIP은 영구 보관하지 않음 |
| `scripts/run_sync.sh` | 전체 오케스트레이션 | `flock` 중복 실행 방지, 환경 설정 로드, Git fast-forward pull, 수집기 순차 실행, Commit/Push |
| `systemd/garmin-fit-sync.service` | 실제 배치 실행 | `oneshot`, `garmin` 계정, 실행 경로·타임아웃 설정 |
| `systemd/garmin-fit-sync.timer` | 스케줄 | 기본 설정 **매일 00:00:00 Asia/Seoul** |
| `requirements.txt` | Python 의존성 | `garminconnect>=0.3,<0.4`, `curl_cffi` |
| `.gitignore` | 민감/임시 파일 제외 | 인증 정보, 가상환경, 로컬 설정, Wellness ZIP 등 제외 |

**데이터 형식과 해석상 주의할 점**

- **Activity FIT:** 세션·랩·레코드 등 운동 원본을 분석합니다. 파일명 `{activityId}.fit`과 활동 ID로 운동을 식별하며, 활동의 **시작 현지 날짜**에 저장합니다.
- **Wellness FIT:** `WELLNESS`, `HRV_STATUS`, `METRICS`, `SLEEP_DATA`, `SLEEP_DISRUPTIONS` 등이 실제 응답에 포함될 수 있습니다. 폴더 날짜는 **Garmin Wellness API 조회일**이며, FIT 내부 시각은 자정을 넘길 수 있습니다.
- **Wellness JSON:** Garmin이 제공하는 수면, HRV, 심박, 스트레스, Body Battery 등의 가공·집계 정보를 담습니다. FIT와 일부 중복되더라도 정의·샘플링·계산 방식이 완전히 같지는 않습니다.
- **Performance JSON:** Training Readiness처럼 날짜가 지정된 응답과, VO₂max/Training Status/Load Focus처럼 **수집 날짜에 저장한 스냅샷**을 구분합니다. 스냅샷 날짜를 과거 측정일이라고 단정하지 않습니다.
- 데이터가 없는 날은 **0이 아니라 누락/미제공**으로 처리합니다. Garmin API에 따라 제공 여부가 달라질 수 있습니다.

### 4. 설치 준비

**권장 환경:** Rocky Linux 9, Python 3.12, Git, systemd, 외부 HTTPS 통신, Private GitHub Repository, GitHub SSH Deploy Key(쓰기 권한).

**예시 경로:** 운영 계정 `garmin`, 프로젝트 경로 `/garmin/garmin-fit-pipeline`. 새 환경에서는 계정/경로/저장소 이름을 변경해도 되지만 **systemd 유닛과 `run_sync.sh`의 경로 및 SSH 키 설정을 함께 변경**해야 합니다.

#### 4.1 OS 및 계정 준비

관리자 계정에서 다음을 실행합니다. 패키지 이름은 해당 Rocky Linux 이미지에서 제공하는 버전에 맞춰 조정합니다.

```bash
sudo dnf install -y git openssh-clients unzip python3.12 python3.12-pip
sudo useradd -m -s /bin/bash garmin  # 이미 존재하면 생략
sudo mkdir -p /garmin
sudo chown garmin:garmin /garmin
```

`python3.12 --version`으로 버전을 확인합니다. 다른 Python 버전을 사용하면 아래 venv 명령도 일관되게 변경하세요.

#### 4.2 GitHub Private Repository 및 SSH 인증

`garmin` 계정에서 SSH 키를 생성하고 공개키를 **대상 Private Repository의 Deploy keys**에 등록합니다. 자동 Push가 필요하므로 **Allow write access**를 활성화해야 합니다.

```bash
sudo -iu garmin
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/garmin_archive_ed25519 -C "garmin-data-pipeline"
chmod 600 ~/.ssh/garmin_archive_ed25519
cat ~/.ssh/garmin_archive_ed25519.pub
```

SSH 연결 시 처음 표시되는 github.com 서버 호스트 키 지문은 GitHub 공식 문서의 공개 지문과 대조해 `known_hosts`에 등록합니다. 그다음 인증을 검사합니다.

```bash
ssh -T -i ~/.ssh/garmin_archive_ed25519 -o IdentitiesOnly=yes git@github.com
```

`Hi ... You've successfully authenticated`라는 메시지는 인증 성공을 의미합니다. **Push 권한**은 나중에 실제 Push로 별도 확인합니다. 기존 서버에 키가 있으면 재생성하지 마세요.

#### 4.3 소스 Clone 및 Python 환경

```bash
sudo -iu garmin
cd /garmin
GIT_SSH_COMMAND='ssh -i /home/garmin/.ssh/garmin_archive_ed25519 -o IdentitiesOnly=yes' \
  git clone git@github.com:suh1027/garmin-fit-repository.git garmin-fit-pipeline
cd /garmin/garmin-fit-pipeline
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
chmod +x scripts/run_sync.sh
```

**Clone 주소는 예시 운영 저장소**입니다. 다른 사용자에게 배포한다면 자신의 Repository 주소로 변경해야 하며, `run_sync.sh`의 고정 SSH 키 경로도 확인해야 합니다.

이미 설치된 서버에서는 **재 Clone하지 말고** 기존 작업 디렉터리에서 진행합니다.

### 5. 인증·환경 설정·최초 다운로드

#### 5.1 Garmin 인증

```bash
cd /garmin/garmin-fit-pipeline
.venv/bin/python scripts/auth.py
```

이메일·비밀번호·MFA 코드를 대화형으로 입력하면 기본적으로 `/home/garmin/.garminconnect/` 아래에 토큰이 생성됩니다. 비밀번호와 토큰은 GitHub에 Push하지 않습니다. 추후 인증이 만료되면 이 명령으로 다시 로그인할 수 있습니다.

#### 5.2 배치 환경변수

프로젝트 루트에 **Git에서 제외된 로컬 설정 파일**을 만듭니다.

```bash
cd /garmin/garmin-fit-pipeline
cat > .collector.env <<'EOF'
ENABLE_HEALTH_JSON=1
HEALTH_DAYS=3
ENABLE_WELLNESS_RAW=1
WELLNESS_DAYS=3
EOF
chmod 600 .collector.env
```

| 변수 | 의미 | 예시 |
| --- | --- | --- |
| `ENABLE_HEALTH_JSON` | JSON 수집 활성화 (1/0) | `1` |
| `HEALTH_DAYS` | 완료된 최근 N일 Wellness/Performance JSON 재조회 | `3` |
| `ENABLE_WELLNESS_RAW` | Wellness 원본 FIT 수집 활성화 (1/0) | `1` |
| `WELLNESS_DAYS` | 완료된 최근 N일 Wellness 원본 FIT 재조회 | `3` |
| `GARMIN_TOKEN_DIR` | 기본 토큰 저장소 위치 변경 시 사용 | `/home/garmin/.garminconnect` |

`run_sync.sh`는 매 실행마다 `.collector.env`를 `source`하므로 **SSH 세션을 종료해도 설정이 유지**됩니다. 이 값은 예시이며 서버별 실제 값은 직접 확인해야 합니다.

**Activity 조회 범위는 위 변수와 별도**입니다. `run_sync.sh --days N` 인자가 `sync_fit.py`에 전달됩니다. GitHub에 보관된 서비스 원본은 `--days 30`입니다. Activity를 3일만 조회하려면 아래 systemd `ExecStart` Override를 사용합니다. Activity의 `--days`는 오늘을 포함하는 경계일 조회이고, Health/Wellness `--days`는 완료된 과거 N일 조회입니다.

#### 5.3 개별 수집기 검증

```bash
cd /garmin/garmin-fit-pipeline
.venv/bin/python -m py_compile scripts/*.py
bash -n scripts/run_sync.sh
.venv/bin/python scripts/sync_fit.py --days 3
.venv/bin/python scripts/sync_health.py --days 3
.venv/bin/python scripts/sync_wellness_raw.py --mode api --days 3
find wellness_raw -type f -name '*.fit' -printf '%h\n' | sort | uniq -c
```

- `sync_fit.py`는 이미 존재하는 유효한 Activity FIT의 재다운로드를 건너뜁니다.
- `sync_health.py`는 변경된 JSON만 저장합니다.
- `sync_wellness_raw.py`는 ZIP CRC·파일명·FIT 형식을 검증한 후 **개별 FIT**를 저장하며 같은 내용은 다시 쓰지 않습니다.
- Garmin의 비공식 API는 변경되거나 일시적인 속도 제한을 적용할 수 있습니다. 다량 백필은 기간을 나눠 실행합니다.
- 과거 수동 저장 ZIP을 변환할 때: `.venv/bin/python scripts/sync_wellness_raw.py --mode import --date 2026-10-19 --import-file /path/to/wellness_original.zip`.

### 6. systemd를 통한 자정 자동화

**현재 Repository의 Timer 원본**은 다음과 같습니다.

```ini
[Timer]
OnCalendar=*-*-* 00:00:00 Asia/Seoul
AccuracySec=1s
RandomizedDelaySec=0
Persistent=true
Unit=garmin-fit-sync.service
```

관리자 계정에서 서비스와 타이머를 설치합니다.

```bash
sudo cp /garmin/garmin-fit-pipeline/systemd/garmin-fit-sync.service /etc/systemd/system/
sudo cp /garmin/garmin-fit-pipeline/systemd/garmin-fit-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now garmin-fit-sync.timer
sudo systemctl restart garmin-fit-sync.timer
sudo systemctl is-enabled garmin-fit-sync.timer
sudo systemctl is-active garmin-fit-sync.timer
sudo systemctl list-timers --all garmin-fit-sync.timer
sudo systemctl cat garmin-fit-sync.timer
sudo systemctl cat garmin-fit-sync.service
```

**Activity 조회를 3일로 변경하는 선택 설정:** 서비스 원본의 `ExecStart`는 `--days 30`입니다. 설치 경로가 같을 경우 다음 drop-in을 사용할 수 있습니다.

```bash
sudo mkdir -p /etc/systemd/system/garmin-fit-sync.service.d
sudo tee /etc/systemd/system/garmin-fit-sync.service.d/lookback.conf >/dev/null <<'EOF'
[Service]
ExecStart=
ExecStart=/garmin/garmin-fit-pipeline/scripts/run_sync.sh --days 3
EOF
sudo systemctl daemon-reload
sudo systemctl show -p ExecStart garmin-fit-sync.service
```

타이머의 실효 설정은 `systemctl cat`으로 확인하세요. 기존 drop-in이 남아 있다면 원본보다 우선할 수 있습니다. `Persistent=true`는 놓친 실행을 복구할 수 있으므로, 재활성화 직후 서비스가 시작될 수도 있습니다.

배치는 **systemd 서비스 프로세스**로 실행되므로 로그인 세션에 의존하지 않습니다. `Type=oneshot` 서비스는 작업 완료 후 `inactive (dead)`로 표시될 수 있으며 정상 여부는 최근 실행 코드와 Journal 로그로 판단합니다.

### 7. GitHub 동기화·백필·운영 명령

```bash
# garmin 계정에서: Activity + Wellness JSON + Performance JSON + Wellness FIT + Push
cd /garmin/garmin-fit-pipeline
./scripts/run_sync.sh --days 3

# 과거 Activity 데이터 보충: 지정 기간
.venv/bin/python scripts/sync_fit.py --since 2026-01-01 --until 2026-01-31

# 과거 Wellness 원본: 최대 30일 범위에서 최근 N일
.venv/bin/python scripts/sync_wellness_raw.py --mode api --days 7

# 데이터별 건수
find activities -type f -name '*.fit' | wc -l
find wellness -type f -name '*.json' | wc -l
find wellness_raw -type f -name '*.fit' | wc -l
find performance -type f -name '*.json' | wc -l

# Git 동기화 상태
git fetch origin main
git status -sb

# 관리자 계정에서: 최근 실행 결과
sudo journalctl -u garmin-fit-sync.service -n 150 --no-pager
sudo systemctl status garmin-fit-sync.service
```

개별 `sync_*.py` 실행은 **다운로드/로컬 저장만 수행**하고, GitHub Commit/Push는 `run_sync.sh`가 수행합니다. 수동으로 개별 수집기를 실행했다면 별도로 Git Push를 하거나 통합 배치를 실행해야 합니다.

**Git 주의사항:** `run_sync.sh`는 시작 시 `git pull --ff-only origin main`을 실행하고 마지막에 Commit/Push합니다. GitHub에서 README를 편집한 뒤 Linux에 같은 파일의 미커밋 변경이 있으면 Pull이 실패할 수 있습니다. 브랜치가 갈라진 경우에는 `git fetch`와 `git status`로 확인하고 충돌을 해결합니다. **`git push --force`를 정기 복구 수단으로 사용하지 않습니다.**

**운영 트러블슈팅**

| 증상 | 확인 및 조치 |
| --- | --- |
| 자정 실행 없음 | `systemctl is-active ...timer`, `list-timers`, `systemctl cat`, `journalctl` |
| Garmin 인증 오류 | `~/.garminconnect/garmin_tokens.json` 존재 여부, `scripts/auth.py` 재로그인 |
| Push `non-fast-forward` | `git fetch origin main`, `git status -sb`, 이력 충돌 해결 후 Push |
| Git SSH `publickey` | Deploy Key 공개키 등록/쓰기 권한, private key 경로, `GIT_SSH_COMMAND` |
| Wellness ZIP만 생성 | 실제 설치된 `sync_wellness_raw.py`가 구형일 수 있음. 새 소스의 `atomic_write`/`archive` 구현 확인 |
| FIT 분석 불가 | FIT는 바이너리이므로 호환 디코더로 파싱한 데이터 또는 원본 파일 접근 필요 |
| 파일 누락 | Garmin 기기→Connect 동기화, 조회 기간, API 지원 여부, 수집 로그 확인 |

### 8. 웹 ChatGPT 프로젝트별 분석 방식

**중요:** 데이터 수집 시스템과 GPT 프로젝트는 분리합니다. 저장소에 FIT·JSON을 Push하는 것만으로 ChatGPT가 자동 접근하거나 분석하지 않습니다. 연결된 GitHub 앱의 접근 범위, FIT 바이너리 다운로드 가능 여부, 프로젝트의 실제 자료 접근을 확인해야 합니다.

**프로젝트 준비 절차**

1. 웹 ChatGPT에서 새 **프로젝트(Project)** 를 생성합니다.
2. 프로젝트마다 아래의 **공통 지침 + 목적별 추가 지침**을 설정합니다. 기술 지침이 길다면 공통 지침을 별도 프로젝트 참고문서로 관리할 수도 있습니다.
3. 해당 계정/환경에서 제공되는 GitHub 연동을 통해 Private Repository 접근을 허용하거나, 특정 FIT 및 JSON 파일을 프로젝트에 직접 첨부합니다.
4. FIT가 바이너리라 연결 도구에서 내용을 읽지 못한다면, 호환 FIT 파서(예: `fitdecode`/`fitparse`)로 `session`/`lap`/`record` 등을 파싱한 CSV/JSON을 분석 자료로 제공합니다.
5. 프로젝트가 실제로 읽은 날짜·파일 경로·활동 ID부터 확인하고, 파일 접근이 불가능하면 **추측 분석 대신 추가 업로드를 요청**합니다.

**분석 항목별 파일 선택**

| 요청 | 먼저 분석할 파일 | 결합할 파일 | 결과 |
| --- | --- | --- | --- |
| 특정 운동/인터벌 분석 | `activities/YYYY/MM/DD/*.fit` | 전후 1일 수면·HRV | 페이스/HR/케이던스/랩/회복 구간 |
| 주간·월간 훈련 요약 | 7~28일 Activity FIT | 일별 Wellness 및 Readiness | 훈련량, 강도 분포, 추세 |
| 피로와 회복 | `wellness/*.json` | `wellness_raw/*.fit`, Activity FIT | HRV/수면/안정시 HR/스트레스/Body Battery |
| 레이스 예상 기록 | 최근 8~12주 FIT, 레이스/롱런 | Performance 스냅샷·회복 데이터 | 보수/기본/공격 범위 및 가정 |
| 오류 검증 | FIT 원본·JSON 동시 조회 | Garmin 조회 날짜 및 내부 타임스탬프 | 누락/중복/타임존/센서 품질 |

**필수 분석 원칙:** 데이터가 실제로 읽혔는지 구분합니다. FIT 바이너리를 텍스트처럼 해석하지 않습니다. `session`·`lap`·`record`의 실제 필드와 단위를 사용합니다. 활동 현지 날짜와 수면 귀속 날짜를 확인합니다. 손목 광학 심박 센서 오류, GPS·케이던스 문제, 지형/기상·신발·보급·체감 강도를 고려합니다. Garmin의 VO₂max·Training Readiness·Body Battery는 가공된 알고리즘 지표입니다. 한두 번의 수치 변동만으로 과훈련·질병·심장 이상을 진단하지 않습니다.

#### 8.1 모든 프로젝트에 적용할 공통 지침 (복사용)

```text
당신은 Garmin Connect 데이터에 근거하여 러닝·사이클링·회복·레이스 퍼포먼스를 분석하는 전문가다.

목적:
- 운동 원본 FIT와 Garmin의 Wellness/Performance JSON을 근거로 장기적인 훈련·회복 변화를 평가한다.
- 관측 사실, 계산값, 해석, 가설을 명확히 구분한다.
- 사용자 요청 범위를 벗어난 건강 진단이나 확정적 경기 결과 예측은 하지 않는다.

데이터 위치:
- Private GitHub Repository: suh1027/garmin-fit-repository (환경에 맞게 변경 가능)
- 활동: activities/YYYY/MM/DD/{activityId}.fit
- 원본 Wellness: wellness_raw/YYYY/MM/DD/*.fit
- Wellness JSON: wellness/YYYY/MM/DD/*.json
- Performance JSON: performance/YYYY/MM/DD/*.json
- Performance Snapshot: performance/snapshots/YYYY/MM/DD/*.json
- 표준 시간대: Asia/Seoul (KST)

접근 및 품질:
1. 분석 전 파일 목록과 날짜·활동 ID를 확인한다. 실제로 접근하지 못한 파일을 읽었다고 주장하지 않는다.
2. FIT는 바이너리 파일이다. 접근·파싱할 수 없으면 원본 첨부 또는 FIT에서 변환한 CSV/JSON을 요청한다.
3. FIT 메시지의 시각, 거리, 속도, 심박, 케이던스, 파워, 랩, 일시정지 정보를 실제 존재하는 필드만 사용한다.
4. Garmin 파생 지표(HRV 상태, VO2max, Body Battery, Training Readiness 등)는 계산된 값으로 취급한다.
5. Wellness FIT와 JSON의 중복 샘플을 이중 집계하지 않는다.
6. performance/snapshots의 경로 날짜는 수집 날짜이며 해당 값의 최초 측정 날짜라고 단정하지 않는다.
7. 누락 데이터는 0이 아니며, GPS 오류·손목 심박 오류·자정 경계·동기화 지연 가능성을 확인한다.
8. 사용자 개인 기준선, 체감 강도, 최근 레이스, 날씨, 지형, 장비, 통증, 회복 상태를 고려한다.
9. 심박 존, 최대심박, 역치, FTP 등 확인되지 않은 기준을 만들어내지 않는다.
10. 레이스 예상 기록은 조건부 범위를 제시하고 불확실성을 설명한다.

응답 형식:
- 핵심 결론을 먼저 설명한다.
- 분석 기간과 실제로 접근한 파일/활동 ID를 밝힌다.
- 주요 수치와 전주/장기 추세를 비교하고 근거를 제시한다.
- 실행 가능한 훈련·회복 제안을 제공한다.
- 데이터가 부족하거나 확실하지 않으면 명시한다.
- 사용자가 지정한 언어로 답한다.
```

#### 8.2 프로젝트별 추가 지침 예시

**A. Training Performance / 훈련 퍼포먼스**

```text
우선 최근 7일과 28일 Activity FIT를 분석하고, 훈련 형태·총 거리·운동 시간·강도 분포,
구간 페이스·심박·케이던스·파워(존재 시)와 회복 구간 품질을 비교한다.
운동 강도는 개인 기준선과 목표 레이스 맥락에서 설명하고, 인터벌/템포/롱런별 적응을 구분한다.
```

**B. Recovery & Readiness / 회복·컨디션**

```text
최근 7~28일 HRV, 수면, 안정시 심박, 스트레스, Body Battery 및 Training Readiness를 확인하고
훈련 부하·고강도 운동 시점과 시계열로 비교한다. 누락일과 수면의 날짜 귀속을 확인한다.
단기 수치 변화만으로 의학적 진단이나 컨디션 악화를 확정하지 않는다.
```

**C. Marathon & Race Planning / 레이스 전략**

```text
최근 8~12주의 레이스·롱런·템포·인터벌·주간 훈련량과 회복 상태를 결합한다.
실제 대회 기록과 코스·기온·보급·신발·당일 컨디션을 반영하여
보수적/기본/공격적인 페이스 및 기록 범위를 제시한다. 전제조건과 실패 위험을 명시한다.
```

**분석 질문 예시**

- “최근 28일의 활동 FIT와 HRV·수면 데이터를 결합해 훈련 부하와 회복 추세를 분석해줘.”
- “10월 18일 인터벌의 각 구간 페이스·심박·회복주 패턴을 비교해줘.”
- “최근 레이스 및 롱런 FIT를 기반으로 마라톤 목표 페이스 3가지 시나리오를 만들어줘.”

### 9. 보안·운영 고려사항

- **Private Repository 유지:** FIT에 위치·운동 동선·생체 정보가 포함될 수 있습니다.
- **권한 최소화:** 데이터 분석 프로젝트와 GitHub 연결은 허가된 사용자에게만 제공합니다.
- **자격증명 비공개:** `~/.garminconnect/`, `~/.ssh/`, `.collector.env`, 비밀번호·MFA 코드는 Repository/ChatGPT 분석 데이터에서 제외합니다.
- **단일 실행:** `run_sync.sh`의 `flock`을 우회하여 같은 저장소를 동시에 쓰지 않습니다.
- **백업 및 이력:** GitHub는 분석용 버전 저장소이며 별도 보안 백업을 대체하지 않습니다. Private 접근제어와 데이터 보존 정책을 운영자가 결정합니다.
- **비공식 API:** Garmin Connect의 내부 엔드포인트·응답 필드는 변경될 수 있습니다. 주기적으로 수집 로그와 데이터 신선도를 검사합니다.
- **문서와 서버 설정의 차이:** GitHub `systemd` 파일을 수정해도 설치된 `/etc/systemd/system/`에 자동 반영되지는 않습니다. drop-in 포함 실효 설정을 검증합니다.

---

## English guide

### 1. Project overview and purpose

This project provides a **general-purpose Garmin data collection and archival pipeline** designed for AI-assisted analysis in **web ChatGPT Projects**. It continuously collects activity files, wellness records and performance summaries into a private GitHub repository.

The same repository can support **multiple ChatGPT Projects with different Project instructions**: training analysis, recovery and readiness, marathon planning, or data-quality auditing. The collection layer is independent of the AI model and prompt.

**It is a data pipeline, not a continuously running ChatGPT agent.** Automatic GitHub Push does not automatically perform an AI analysis or give a private GitHub repository access to a ChatGPT Project.

### 2. System architecture

```text
Garmin Devices → Garmin Connect
                   │ Authenticated API access
                   ▼
              Linux (Rocky Linux 9)
                auth.py
                sync_fit.py
                sync_health.py
                sync_wellness_raw.py
                        ▲
                 run_sync.sh
                        ▲
          systemd timer: 00:00 KST daily
                        │
                        ▼
              GitHub Private Repository
        activities/  wellness/  wellness_raw/
                    performance/
                        │ authorized retrieval or file upload
                        ▼
              Web ChatGPT Projects
       Training | Recovery | Race Planning
```

**Workflow:** Garmin devices sync to Garmin Connect. A systemd timer launches the collection wrapper. It reuses stored Garmin tokens, fetches data into structured date folders, commits and pushes the changed files to GitHub. ChatGPT separately reads authorized, accessible files when requested.

### 3. Repository structure and source-code responsibilities

```text
repository/
├── README.md
├── requirements.txt
├── .gitignore
├── scripts/
│   ├── auth.py
│   ├── sync_fit.py
│   ├── sync_health.py
│   ├── sync_wellness_raw.py
│   └── run_sync.sh
├── systemd/
│   ├── garmin-fit-sync.service
│   └── garmin-fit-sync.timer
├── activities/YYYY/MM/DD/{activityId}.fit
├── wellness/YYYY/MM/DD/*.json
├── wellness_raw/YYYY/MM/DD/*.fit
└── performance/
    ├── YYYY/MM/DD/training_readiness.json
    └── snapshots/YYYY/MM/DD/*.json
```

| Component | Responsibility |
| --- | --- |
| `scripts/auth.py` | Interactive Garmin authentication and storage of reusable tokens **outside Git** |
| `scripts/sync_fit.py` | Download original Activity FIT, validate, avoid duplicate activity downloads, store by local activity start date |
| `scripts/sync_health.py` | Save daily sleep, HRV, heart-rate, stress, Body Battery, stats and Training Readiness JSON; store metric snapshots separately |
| `scripts/sync_wellness_raw.py` | Fetch a Wellness ZIP response and validate/extract **individual FIT files** without retaining the ZIP for new downloads |
| `scripts/run_sync.sh` | Lock concurrent runs, read `.collector.env`, fast-forward pull, execute collectors, Git commit and push |
| `systemd/garmin-fit-sync.timer` | Trigger collection at **00:00:00 Asia/Seoul daily** |
| `systemd/garmin-fit-sync.service` | Run the one-shot collector using the configured OS user and working directory |
| `requirements.txt` | Python libraries required by the collectors |

**Data semantics**

- **Activity FIT:** Captures recorded exercise sessions, laps and records; path date is the local exercise start date.
- **Wellness raw FIT:** May contain WELLNESS, HRV_STATUS, METRICS, SLEEP_DATA or SLEEP_DISRUPTIONS. The folder is based on the requested Wellness bundle date, which may differ from internal timestamps around midnight.
- **Wellness JSON:** Garmin-provided sleep, HRV, heart rate, stress and Body Battery values; partially overlaps raw FIT but is not necessarily semantically identical.
- **Performance:** Daily Training Readiness responses and capture-date **snapshots** for VO₂max, Training Status and Load Focus.
- A missing file is **missing/unavailable data, not a zero measurement**.

### 4. Prerequisites and installation (Rocky Linux 9)

**Requirements:** Rocky Linux 9 or an adapted Linux environment, Python 3.12 recommended, Git, unzip, systemd, outbound access to Garmin Connect/GitHub, a **private GitHub repository** and a write-enabled GitHub SSH Deploy Key.

The examples below use OS user `garmin` and install path `/garmin/garmin-fit-pipeline`. When deploying elsewhere, update the corresponding absolute paths in the service and runner scripts.

**Step 1 — Prepare the OS and account** (administrator):

```bash
sudo dnf install -y git openssh-clients unzip python3.12 python3.12-pip
sudo useradd -m -s /bin/bash garmin  # skip if already present
sudo mkdir -p /garmin
sudo chown garmin:garmin /garmin
```

Adjust the Python packages to those available in your Rocky Linux installation.

**Step 2 — Create a Deploy Key** (as the `garmin` user):

```bash
sudo -iu garmin
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/garmin_archive_ed25519 -C "garmin-data-pipeline"
chmod 600 ~/.ssh/garmin_archive_ed25519
cat ~/.ssh/garmin_archive_ed25519.pub
```

Register the **public** key in the target GitHub Repository's **Settings → Deploy keys**, allowing write access. Verify GitHub's SSH host key fingerprint before accepting it into `known_hosts`. Test authentication:

```bash
ssh -T -i ~/.ssh/garmin_archive_ed25519 -o IdentitiesOnly=yes git@github.com
```

The successful-authentication greeting does not itself prove Push permission.

**Step 3 — Clone and install Python dependencies** (as `garmin`):

```bash
cd /garmin
GIT_SSH_COMMAND='ssh -i /home/garmin/.ssh/garmin_archive_ed25519 -o IdentitiesOnly=yes' \
  git clone git@github.com:suh1027/garmin-fit-repository.git garmin-fit-pipeline
cd /garmin/garmin-fit-pipeline
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
chmod +x scripts/run_sync.sh
```

Substitute your repository URL when distributing this project. **Do not re-clone over an existing deployment.**

### 5. Authentication and collector configuration

**Authenticate Garmin** interactively:

```bash
cd /garmin/garmin-fit-pipeline
.venv/bin/python scripts/auth.py
```

Tokens are kept under `~/.garminconnect/` by default, outside the Git working tree. Never commit credentials.

**Create local runtime configuration**:

```bash
cat > /garmin/garmin-fit-pipeline/.collector.env <<'EOF'
ENABLE_HEALTH_JSON=1
HEALTH_DAYS=3
ENABLE_WELLNESS_RAW=1
WELLNESS_DAYS=3
EOF
chmod 600 /garmin/garmin-fit-pipeline/.collector.env
```

These are **recommended example settings**, not a claim about an individual server's active settings. `run_sync.sh` sources this local file each time, independent of any interactive SSH session.

Activity lookback uses the wrapper argument `--days N`. The committed service unit currently specifies **`run_sync.sh --days 30`**; you can override it at the systemd service level. Health/Wellness `--days 3` reprocesses three **previously completed local days**; Activity's `--days 3` includes today and the three-day-back boundary by its current implementation.

**Validate the collectors**:

```bash
cd /garmin/garmin-fit-pipeline
.venv/bin/python -m py_compile scripts/*.py
bash -n scripts/run_sync.sh
.venv/bin/python scripts/sync_fit.py --days 3
.venv/bin/python scripts/sync_health.py --days 3
.venv/bin/python scripts/sync_wellness_raw.py --mode api --days 3
```

The Wellness collector receives a ZIP transport payload, validates CRC and FIT structure, and saves only individual `.fit` files for newly downloaded data. Convert an existing ZIP using `--mode import --date YYYY-MM-DD --import-file /path/to/file.zip`. Garmin unofficial API endpoints may change.

### 6. Schedule with systemd (00:00 KST)

The committed timer contains:

```ini
[Timer]
OnCalendar=*-*-* 00:00:00 Asia/Seoul
AccuracySec=1s
RandomizedDelaySec=0
Persistent=true
Unit=garmin-fit-sync.service
```

Install and enable using an administrative account:

```bash
sudo cp /garmin/garmin-fit-pipeline/systemd/garmin-fit-sync.service /etc/systemd/system/
sudo cp /garmin/garmin-fit-pipeline/systemd/garmin-fit-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now garmin-fit-sync.timer
sudo systemctl list-timers --all garmin-fit-sync.timer
sudo systemctl cat garmin-fit-sync.timer
sudo systemctl cat garmin-fit-sync.service
```

**Optional three-day Activity lookback:** the committed service has `--days 30`. To override it on this example host:

```bash
sudo mkdir -p /etc/systemd/system/garmin-fit-sync.service.d
sudo tee /etc/systemd/system/garmin-fit-sync.service.d/lookback.conf >/dev/null <<'EOF'
[Service]
ExecStart=
ExecStart=/garmin/garmin-fit-pipeline/scripts/run_sync.sh --days 3
EOF
sudo systemctl daemon-reload
sudo systemctl show -p ExecStart garmin-fit-sync.service
```

Check all active drop-ins and effective values. With `Persistent=true`, enabling a timer after missing a scheduled run can trigger a catch-up execution. The timer operates **without an SSH session**.

### 7. Operations, backfill, Git, and troubleshooting

```bash
# Integrated collection and Git Push (as garmin)
cd /garmin/garmin-fit-pipeline
./scripts/run_sync.sh --days 3

# Activity historical backfill
.venv/bin/python scripts/sync_fit.py --since 2026-01-01 --until 2026-01-31

# Wellness lookback
.venv/bin/python scripts/sync_wellness_raw.py --mode api --days 7

# Data freshness and file counts
find activities -type f -name '*.fit' | wc -l
find wellness -type f -name '*.json' | wc -l
find wellness_raw -type f -name '*.fit' | wc -l
find performance -type f -name '*.json' | wc -l

# Repository synchronization
git fetch origin main
git status -sb

# Service logs (administrator)
sudo journalctl -u garmin-fit-sync.service -n 150 --no-pager
sudo systemctl status garmin-fit-sync.service
```

Running a single collector saves **local files only**; the integrated wrapper performs Git commit/push. The wrapper attempts a **fast-forward-only pull** first. If local and remote histories diverge, resolve them safely—do not use routine force pushes.

| Symptom | Investigation |
| --- | --- |
| Timer does not run | Inspect `is-active`, `list-timers`, `systemctl cat` and `journalctl` |
| Login failure | Inspect token store and rerun `scripts/auth.py` when required |
| Git permission denied | Verify Deploy Key, key selection, repository write permission, verified host key |
| Non-fast-forward Push | Fetch and inspect local/remote commit divergence; resolve conflicts |
| New Wellness data saved as ZIP | An outdated `sync_wellness_raw.py` may be installed; inspect actual deployed source |
| Missing days | Check device-to-Garmin sync, API availability, collector lookback and logs |
| FIT analysis unavailable | Use a compatible FIT decoder and supply faithful CSV/JSON output or original binary |

### 8. Web ChatGPT: project-specific AI analysis

Create separate **ChatGPT Projects** (not separate Git branches) for different analytical goals. A private GitHub repository must be explicitly authorized through supported integrations, or selected files must be uploaded manually. FIT data is binary; connected file browsers may not expose its content. When necessary, decode FIT files with a compatible parser and make the records available as CSV/JSON.

**Recommended source selection**

| Task | Primary sources | Secondary sources |
| --- | --- | --- |
| Workout/intervals | Activity FIT: session/lap/record | Adjacent sleep and HRV |
| Weekly load and training trend | 7–28 days of Activity FIT | Wellness and Training Readiness |
| Recovery and fatigue | Wellness JSON over 7–28 days | Raw Wellness FIT and recent workload |
| Marathon race planning | 8–12 weeks of workouts and race FIT | Weather, fueling, shoes and performance snapshots |
| Quality audits | Raw FIT + corresponding JSON | API-request date, internal timestamps, missing periods |

**Non-negotiable analysis safeguards:** Confirm actual source access and file freshness; never infer the contents of an unread binary FIT; use documented timestamp/units; avoid double-counting repeated HR samples; respect midnight-crossing sleep records; distinguish **Garmin-derived estimates** from measured data; inspect wrist optical HR or GPS artifacts; do not diagnose illness or promise race outcomes based on isolated metrics.

#### 8.1 Common Project instructions (copy/paste)

```text
You are a data-grounded Garmin running, endurance and recovery analyst.

Goal:
- Use Garmin activity FIT, wellness FIT and derived wellness/performance JSON to
  understand training, fitness trends, fatigue, recovery and conditional race readiness.
- Keep observations, calculations, interpretations and hypotheses separate.
- Do not issue medical diagnoses or guaranteed race outcomes.

Repository and paths:
- Private repository: suh1027/garmin-fit-repository (adjust as needed)
- Activity FIT: activities/YYYY/MM/DD/{activityId}.fit
- Raw wellness FIT: wellness_raw/YYYY/MM/DD/*.fit
- Wellness JSON: wellness/YYYY/MM/DD/*.json
- Daily performance JSON: performance/YYYY/MM/DD/*.json
- Metric snapshots: performance/snapshots/YYYY/MM/DD/*.json
- Local time zone: Asia/Seoul.

Access and data quality rules:
1. Inventory actual accessible files, dates and activity IDs before analysis.
2. Never claim to have read a file that the connected tools cannot access.
3. FIT is binary. Parse with a compatible FIT decoder or ask for source FIT /
   parser-generated CSV/JSON; never infer FIT contents from its filename.
4. Use only fields present in the decoded session/lap/record messages and
   documented units. Distinguish moving, timer and elapsed time.
5. Avoid double-counting overlap between Activity FIT, Wellness FIT and JSON.
6. Treat VO2max, Body Battery, Training Readiness and status labels as Garmin-derived metrics.
7. Performance snapshot paths describe collection dates, not necessarily measurement dates.
8. Missing files are not zero measurements. Check sensor/GPS artifacts, KST boundaries,
   delayed sync, pauses and sport type.
9. Interpret results against individual baselines, recent races, RPE, pain, shoes,
   weather, elevation, fueling and training goals.
10. Do not invent HR zones, lactate thresholds, power zones or unavailable data.
11. Present race-time estimates as conditional ranges, with assumptions and uncertainty.

Response format:
- Begin with concise takeaways.
- State date range, inspected file paths and actual activity IDs.
- Provide defensible calculations and comparisons when data support them.
- Explain main pace/HR/workload/recovery relationships and limitations.
- End with actionable, appropriately cautious recommendations.
- Respond in the language requested by the user.
```

#### 8.2 Add-on instructions by Project type

**A. Training Performance**

```text
Prioritize the last 7 and 28 days of Activity FIT data. Analyze training volume,
workout types, lap pacing, HR, cadence, power when available, intensity distribution,
interval recovery and change relative to the individual's baseline.
```

**B. Recovery & Readiness**

```text
Compare 7–28 days of HRV, sleep, resting HR, stress, Body Battery and Training
Readiness with exercise intensity and timing. Check missing dates and sleep-day
attribution. Do not infer disease or overtraining from one or two measurements.
```

**C. Marathon & Race Planning**

```text
Combine 8–12 weeks of workouts with actual races, long runs, tempo sessions,
intervals, training volume and recovery. Account for course elevation, weather,
fueling, shoes and subjective condition. Offer conservative, baseline and
aggressive pacing/time scenarios, with explicit assumptions and failure risks.
```

**Example questions**

- "Analyze my last 28 days of activities, HRV and sleep to assess training load and recovery."
- "Break down the intervals from my October 18 FIT by lap and compare the prior month."
- "Estimate conservative, baseline and aggressive marathon pacing from actual races and long runs."

### 9. Security and operational limitations

- Keep the repository **private**: FIT files may include GPS traces and sensitive physiological information.
- Use least-privilege GitHub access for AI-connected services.
- Never upload Garmin passwords/MFA codes, `.collector.env`, token-store contents or SSH private keys.
- Avoid concurrent processes writing the same repository; the runner uses `flock`.
- GitHub is the analysis/version archive, not a complete independent backup strategy.
- Garmin Connect unofficial API methods can change, so monitor collection errors and freshness.
- A change to `systemd/*.service` or `*.timer` in Git does **not** modify files already installed under `/etc/systemd/system/`. Verify actual effective overrides on each host.

---

## 기존 상세 운영 문서 / Preserved legacy documentation

> **보존 안내 / Preservation note:** The following is the previous README **in its original form**, retained for its complete installation, debugging and operational history as previously requested. Some historical statements refer to earlier FIT-only or ZIP-based collectors and old timer defaults. **For new deployments, follow the current Korean or English guide above.**
>
> **아래는 기존 README 원문을 삭제하거나 수정하지 않고 유지한 부분입니다.** 초기 도입 기록이나 당시의 코드/설정 안내가 포함될 수 있으므로 현재 구성을 적용할 때는 위 한·영 가이드를 우선하세요.

---

# Garmin Connect FIT Archive Pipeline — Rocky Linux 9

Garmin Connect에서 **원본 액티비티 FIT 파일을 자동 수집**하고, Rocky Linux 9 VM에서 일별 디렉터리로 분류한 뒤 **GitHub Private Repository에 매일 자동 Push**하는 파이프라인입니다. GPT를 이용한 분석은 별도의 단계로 분리합니다.

> **현재 운영 환경 (2026-10-19 기준)**
>
> | 구분 | 설정 |
> | --- | --- |
> | OS | Rocky Linux 9 |
> | Linux 실행 계정 | `garmin` |
> | 설치 / Git working tree | `/garmin/garmin-fit-pipeline` |
> | 원격 GitHub Repository | [`suh1027/garmin-fit-repository`](https://github.com/suh1027/garmin-fit-repository) — Private |
> | Git 원격 SSH URL | `git@github.com:suh1027/garmin-fit-repository.git` |
> | SSH Deploy Key | `/home/garmin/.ssh/garmin_archive_ed25519` |
> | FIT 저장 경로 | `activities/YYYY/MM/DD/{activityId}.fit` |
> | 정기 실행 목표 | **매일 00:00 KST (Asia/Seoul)** |
> | 정기 수집 범위 | 최근 30일 재조회, 이미 저장한 FIT는 건너뛰기 |
> | 분석 방식 | 필요한 FIT를 별도 GPT 분석 워크플로에서 사용 |

**확인된 완료 사항:** `garmin` 사용자와 `/garmin/garmin-fit-pipeline` 디렉터리는 이미 만들어졌고, 아래 명령으로 GitHub Deploy Key 인증에 성공했습니다.

```text
ssh -T -i ~/.ssh/garmin_archive_ed25519 git@github.com
Hi suh1027/garmin-fit-repository! You've successfully authenticated, but GitHub does not provide shell access.
```

따라서 **키를 다시 생성하거나 `/opt` 경로에 별도 설치할 필요는 없습니다.** 단, 위 결과는 SSH *인증* 성공이지 Git *Push* 권한 검증은 아닙니다.

> **중요 — 실제 적용 상태**
>
> 이 README만 GitHub에서 업데이트해도 Linux 서버의 서비스/타이머 설정은 자동 변경되지 않습니다. 현재 Repository에 있는 `systemd/garmin-fit-sync.timer` 소스 파일에는 **02:00 + 최대 10분 지연**이 남아 있습니다. 요구사항인 **00:00 KST**는 아래 **[10. systemd 설정](#10-systemd-정기-실행--매일-0000-kst)** 의 drop-in override를 서버에 적용해야 합니다. 이 문서 업데이트는 `README.md` 한 파일만 변경하며 스크립트 및 timer 소스는 수정하지 않습니다.

---

## 0. 전체 아키텍처와 처리 순서

```text
Garmin Connect
  │ HTTPS / 비공식 python-garminconnect API
  │ Activity 목록 + Activity ID + 원본 ZIP
  ▼
Rocky Linux 9 VM (garmin 계정)
  ├─ /home/garmin/.garminconnect/garmin_tokens.json  [민감 토큰 / Git 외부]
  └─ /garmin/garmin-fit-pipeline/
      ├─ scripts/auth.py          최초 대화형 로그인 및 토큰 저장
      ├─ scripts/sync_fit.py      활동 목록 조회 / 중복 확인 / FIT 추출·검증
      ├─ scripts/run_sync.sh     실행 잠금 / git pull / 수집 / commit / push
      ├─ systemd/                서비스·타이머 원본 정의
      ├─ .venv/                   Python 3.12 가상환경 (Git 제외)
      └─ activities/
          └─ 2026/
              └─ 10/
                  ├─ 18/
                  │   └─ 12345678901.fit
                  └─ 19/
                      ├─ 12345678902.fit
                      └─ 12345678903.fit
  │ git commit + git push (SSH Deploy Key)
  ▼
GitHub Private Repository: suh1027/garmin-fit-repository
  │
  └─ GPT 분석 단계 (별도 구축; 이 수집 배치에는 포함되지 않음)
```

**매일 자정의 단일 실행 흐름**

1. `garmin-fit-sync.timer`가 `garmin-fit-sync.service`를 활성화합니다.
2. 서비스가 `User=garmin`으로 `scripts/run_sync.sh --days 30`을 실행합니다.
3. `flock`으로 **중복 배치 실행을 차단**하고 `git pull --ff-only origin main`을 실행합니다.
4. Python 수집기가 지난 30일 활동을 날짜 구간별로 조회합니다.
5. 각 Garmin Activity ID에 대해 저장 파일의 유효성을 확인합니다.
6. 누락된 액티비티는 Garmin 원본 ZIP을 다운로드하고 내부 FIT 한 개를 추출합니다.
7. FIT를 `activities/YYYY/MM/DD/{activityId}.fit` 경로에 **원자적 저장(temporary → rename)** 합니다.
8. Git에 `activities` 변경분을 Stage하고 신규 변경이 있을 때만 Commit합니다.
9. 원격 `main` 브랜치로 Push합니다. 이전 Push 실패로 로컬에 남은 Commit도 다시 Push합니다.

> **00:00은 배치 시작 시각입니다.** FIT 수집과 Push 완료 시각은 Garmin 및 GitHub 응답 속도에 따라 달라집니다. Garmin에 업로드가 늦게 반영된 액티비티는 다음 실행의 최근 30일 재조회에서 보충됩니다.

### 디렉터리/원본 데이터 규칙

- **파일명:** Garmin의 고유 `activityId`. 하루에 여러 차례 러닝·사이클링을 기록해도 서로 덮어쓰지 않습니다.
- **분류 날짜:** `startTimeLocal`의 날짜가 우선이며, 값이 없다면 `startTimeGMT`를 **Asia/Seoul로 변환**합니다.
- **중복 처리:** 이미 존재하며 기본 FIT 형식 검사를 통과한 파일은 다시 다운로드하지 않습니다.
- **이전 버전 호환:** 기존 `activities/YYYY/MM/{activityId}.fit` 형식의 파일은 해당 활동이 API 조회 범위에 포함될 때 새 일별 폴더로 옮깁니다.
- **포맷:** 기본 `.fit`, 선택적으로 `--format zip`을 사용할 수 있습니다. 서로 다른 포맷은 개별 파일이며 운영에서는 **FIT 하나로 통일**하는 것을 권장합니다.
- **검증 수준:** 현재 코드의 FIT 검사는 헤더/파일 길이 중심의 **기본 유효성 검사**입니다. 모든 FIT 레코드의 CRC나 의미적 무결성을 완전히 검증하는 단계는 아닙니다.
- **백업 성격:** GitHub는 보조 보관소이며, Git 이력은 불변/대용량 백업 시스템을 대신하지 않습니다. 중요한 원본은 별도 주기적 백업도 권장합니다.

---

## 1. 사전 확인 및 네트워크 요구사항

### 1-1. Rocky Linux 9 시스템 정보

**실행: sudo 권한이 있는 관리자 계정**

```bash
cat /etc/rocky-release
uname -m
id garmin
timedatectl
sudo ls -ld /garmin /garmin/garmin-fit-pipeline
namei -l /garmin/garmin-fit-pipeline
```

이미 생성한 프로젝트 경로는 다음과 같은 소유권과 권한을 유지합니다.

```text
/garmin/garmin-fit-pipeline  →  garmin:garmin  / 0750
```

필요할 때에만 아래 명령으로 수정합니다. 전체 디스크나 `/garmin` 상위 경로까지 재귀적으로 소유권을 바꾸지 않습니다.

```bash
sudo chown garmin:garmin /garmin/garmin-fit-pipeline
sudo chmod 0750 /garmin/garmin-fit-pipeline
```

`/garmin` 상위 디렉터리에도 `garmin` 계정의 통과 권한(`x`)이 필요합니다. 접근 불가라면 `namei -l` 결과를 보고 해당 디렉터리의 ACL/권한을 조정합니다.

### 1-2. 패키지 설치

**실행: 관리자 계정**

```bash
sudo dnf makecache

sudo dnf install -y \
  git openssh-clients unzip util-linux tzdata \
  python3.12 python3.12-pip

python3.12 --version
git --version
flock --version
```

- Python은 **3.12 이상**이 필요하며, Rocky Linux 9의 시스템 기본 Python을 다른 버전으로 변경하지 않습니다.
- `python3.12` 패키지를 찾을 수 없다면 Rocky 9 마이너 버전 및 AppStream 활성화 상태를 확인합니다.

```bash
sudo dnf repolist
sudo dnf list --available 'python3.12*'
```

### 1-3. 네트워크 / 방화벽

| 출발지 | 목적지 | 포트 | 목적 |
| --- | --- | --- | --- |
| Rocky VM | Garmin 인증 및 Connect API | TCP 443 | 로그인·활동 목록·FIT 다운로드 |
| Rocky VM | `github.com` | TCP 22 | SSH Clone / Pull / Push |
| Rocky VM | DNS Resolver | UDP/TCP 53 또는 사내 지정 DNS | 이름 해석 |
| Rocky VM | NTP 서버 | 환경에 따라 다름 | 서버 시계 동기화 |

별도의 **인바운드 서비스 포트 개방은 필요하지 않습니다.** 회사 프록시 또는 Egress 보안정책이 있다면 별도로 허용이 필요합니다.

---

## 2. GitHub Deploy Key 설정 및 SSH 오류 해결

### 2-1. 현재 키 확인 — 재발급 불필요

**실행: garmin 계정**

```bash
sudo -iu garmin
whoami
ls -ld /home/garmin/.ssh
ls -l /home/garmin/.ssh/garmin_archive_ed25519*
```

현재 등록된 공개키가 GitHub 저장소의 **Settings → Deploy keys**에 등록되어 있어야 합니다. 새 키를 등록할 필요는 없고, 정기 Push를 위해 **Allow write access**가 체크되어 있는지만 확인합니다.

개인키 파일은 GitHub에 업로드하거나 README/로그에 기록하면 안 됩니다.

```bash
chmod 700 /home/garmin/.ssh
chmod 600 /home/garmin/.ssh/garmin_archive_ed25519
chmod 644 /home/garmin/.ssh/garmin_archive_ed25519.pub
```

### 2-2. 이미 성공한 SSH 인증 재확인

```bash
ssh -T -i /home/garmin/.ssh/garmin_archive_ed25519 \
  -o IdentitiesOnly=yes git@github.com
```

예상 메시지:

```text
Hi suh1027/garmin-fit-repository! You've successfully authenticated, but GitHub does not provide shell access.
```

이 문구가 출력되면 GitHub 인증 성공입니다. GitHub는 SSH 셸을 제공하지 않으므로 `ssh -T` 종료 코드가 1이어도 위 메시지가 나오면 정상일 수 있습니다.

### 2-3. `git clone`의 `Permission denied (publickey)` 해결

이전에 다음 상황이 발생했습니다.

- `ssh -T -i ~/.ssh/garmin_archive_ed25519 git@github.com` → 성공
- `git clone git@github.com:suh1027/garmin-fit-repository.git .` → `Permission denied (publickey)`

원인 후보 중 가장 유력한 것은 Git이 기본 SSH 키 탐색에서 사용자 지정 키를 선택하지 않은 것입니다. **최초 Clone에서는 다음처럼 키를 명시**합니다.

```bash
GIT_SSH_COMMAND="ssh -i /home/garmin/.ssh/garmin_archive_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes" \
  git ls-remote git@github.com:suh1027/garmin-fit-repository.git HEAD
```

위 명령이 성공하면 연결·Repository 읽기 권한을 확인한 것입니다.

`scripts/run_sync.sh`는 **이미 전용 SSH 개인키를 명시적으로 사용**하므로 자동 배치에서 `~/.ssh/config`가 필수는 아닙니다. 수동 `git pull`, `git push` 등에서도 같은 키를 사용하려면 현재 저장소에서 다음을 실행할 수 있습니다(`.git` 초기화 후).

```bash
git config --local core.sshCommand \
  'ssh -i /home/garmin/.ssh/garmin_archive_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes'
```

이 설정은 **해당 Git working tree에만** 적용됩니다. 공용 서버의 모든 Git 저장소에 영향을 주지 않습니다.

### 2-4. GitHub 호스트 키 검증

처음 SSH로 GitHub에 접속할 때 `known_hosts` 등록이 필요할 수 있습니다. 호스트 키는 GitHub [공식 공개 지문](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)과 비교하여 신뢰해야 합니다.

```bash
ssh-keygen -F github.com
ssh-keygen -lf /home/garmin/.ssh/known_hosts -E sha256
```

호스트 키가 누락됐다면 인증 전에 공식 지문을 대조해 등록합니다. `StrictHostKeyChecking=no`로 검증을 우회하지 않습니다.

---

## 3. Git 저장소를 기존 `/garmin/garmin-fit-pipeline`에 연결

**실행: garmin 계정**

```bash
cd /garmin/garmin-fit-pipeline
pwd
ls -la
test -d .git && echo "Git working tree already exists" || echo "No .git directory"
```

서버에 파일을 이미 업로드했다고 했으므로 **내용을 삭제하지 않고**, 다음 중 현재 상태와 일치하는 경우만 진행합니다.

### A. `.git`이 이미 있는 경우 — 가장 먼저 확인

```bash
cd /garmin/garmin-fit-pipeline
git status -sb
git remote -v
git branch -a
```

`origin`이 다르다면 아래 명령으로 원격 주소만 변경합니다.

```bash
git remote set-url origin git@github.com:suh1027/garmin-fit-repository.git
```

기존 작업 파일이 있다면 `git status --short` 결과를 확인한 후 보존합니다. **`git reset --hard`, 강제 Push는 사용하지 않습니다.**

### B. `.git`이 없고 현재 디렉터리가 비어 있는 경우

```bash
cd /garmin/garmin-fit-pipeline

GIT_SSH_COMMAND="ssh -i /home/garmin/.ssh/garmin_archive_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes" \
  git clone git@github.com:suh1027/garmin-fit-repository.git .

git remote -v
git status -sb
```

원격 Repository에는 이미 README와 소스가 있으므로 성공하면 해당 파일들이 설치 폴더에 생성됩니다.

### C. `.git`이 없지만 디렉터리에 기존 파일이 있는 경우

**바로 `git clone ... .`을 실행하지 않습니다.** 대상 디렉터리가 비어 있지 않으면 Clone이 실패하거나 수동 덮어쓰기가 필요해집니다. 우선 임시 위치에 별도 Clone해 기존 업로드 파일과 비교합니다.

```bash
GIT_SSH_COMMAND="ssh -i /home/garmin/.ssh/garmin_archive_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes" \
  git clone git@github.com:suh1027/garmin-fit-repository.git \
  /home/garmin/garmin-fit-repository-check

diff -qr /home/garmin/garmin-fit-repository-check/scripts \
         /garmin/garmin-fit-pipeline/scripts || true
```

기존 활동/스크립트가 있다면 백업 후 설치 경로를 하나의 Git working tree로 통합합니다. **자동으로 파일을 삭제하거나 `.git`만 임의 복사하지 않습니다.**

### D. 저장소 기본 동작 확인

```bash
cd /garmin/garmin-fit-pipeline
git remote -v
git branch --show-current
git status -sb
```

기준 브랜치는 `main`입니다. 정상적인 Push 주소는 `git@github.com:suh1027/garmin-fit-repository.git`이어야 합니다.

---

## 4. 프로젝트 소스 구조 및 코드 확인

GitHub Repository에 이미 다음 소스 파일이 있습니다.

```text
garmin-fit-repository/
├── README.md
├── requirements.txt
├── .gitignore
├── scripts/
│   ├── auth.py
│   ├── sync_fit.py
│   └── run_sync.sh
├── systemd/
│   ├── garmin-fit-sync.service
│   └── garmin-fit-sync.timer
├── tests/
└── activities/
    └── YYYY/MM/DD/{activityId}.fit
```

실제 서버에 파일이 존재하는지 확인합니다.

```bash
cd /garmin/garmin-fit-pipeline
ls -l README.md requirements.txt .gitignore
ls -l scripts/auth.py scripts/sync_fit.py scripts/run_sync.sh
ls -l systemd/garmin-fit-sync.service systemd/garmin-fit-sync.timer
```

필요한 경우 실행 권한을 부여합니다.

```bash
chmod 755 scripts/run_sync.sh
mkdir -p activities
```

`requirements.txt`에 정의된 패키지:

```text
garminconnect>=0.3,<0.4
curl_cffi
```

이 가이드는 위 **현재 GitHub 스크립트의 인자 및 실행 로직**을 기준으로 작성했습니다. Python 수집기는 파일 분류, 기본 유효성 검사, 원본 ZIP 처리, 구버전 월별 디렉터리 이동, 재시도 시 중복 방지를 제공합니다.

---

## 5. Python 3.12 가상환경 구성

**실행: garmin 계정**

```bash
cd /garmin/garmin-fit-pipeline

python3.12 -m venv .venv

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

.venv/bin/python --version
.venv/bin/python -c 'from garminconnect import Garmin; print("Garmin module import: OK")'
```

성공하면 `Garmin module import: OK`가 출력됩니다.

파이프라인에서는 `/garmin/garmin-fit-pipeline/.venv/bin/python`을 사용하므로 시스템 Python을 변경하거나 글로벌 `pip install`을 실행할 필요가 없습니다.

`.venv/`는 `.gitignore`로 Git에서 제외됩니다.

### 패키지 버전 확인

```bash
.venv/bin/python -m pip show garminconnect curl_cffi
.venv/bin/python -m pip freeze
```

운영에 성공한 버전은 별도로 기록하십시오. `garminconnect`는 비공식 API 클라이언트이므로 버전 변경 시 재검증이 필요합니다.

---

## 6. Garmin Connect 최초 인증 (대화형)

**실행: garmin 계정. root에서 실행하지 마십시오.**

```bash
cd /garmin/garmin-fit-pipeline

mkdir -p /home/garmin/.garminconnect
chmod 700 /home/garmin/.garminconnect

.venv/bin/python scripts/auth.py
```

인증 절차:

1. Garmin Connect 이메일을 입력합니다.
2. Garmin 계정 비밀번호를 입력합니다(`getpass` 사용, 화면에 노출되지 않음).
3. MFA가 활성화된 계정은 일회용 인증 코드를 입력합니다.
4. 라이브러리가 DI OAuth 토큰을 저장합니다.

저장 위치:

```text
/home/garmin/.garminconnect/garmin_tokens.json
```

인증 결과 확인(**토큰 본문 출력 금지**):

```bash
ls -ld /home/garmin/.garminconnect
stat -c '%a %U:%G %n' \
  /home/garmin/.garminconnect/garmin_tokens.json
```

권장 권한은 디렉터리 `700`, 토큰 파일 `600`입니다. 필요 시 파일 권한만 수정합니다.

```bash
chmod 600 /home/garmin/.garminconnect/garmin_tokens.json
```

토큰이 유효한 동안 정기 배치는 저장된 토큰으로 로그인하고 갱신할 수 있습니다. Refresh Token이 만료·폐기되는 경우 **다시 대화형 로그인**이 필요합니다. Garmin 비밀번호를 `.env`, GitHub Secrets, 스크립트, 셸 히스토리에 불필요하게 저장하지 마십시오.

이 프로그램은 Garmin의 **비공식 API**를 사용합니다. 공식 API 가용성 또는 계정별 로그인 성공은 보장되지 않습니다.

---

## 7. FIT 소량 다운로드 및 파일 구조 검증

**실행: garmin 계정**

먼저 최근 7일 중 **최대 3개**를 다운로드합니다. 이 단계는 FIT 다운로드만 테스트하므로 **Git Push를 하지 않습니다**.

```bash
cd /garmin/garmin-fit-pipeline

.venv/bin/python scripts/sync_fit.py \
  --days 7 \
  --max-downloads 3 \
  --pause 3
```

확인:

```bash
find activities -type f -name '*.fit' | sort
find activities -type f -name '*.fit' | wc -l
find activities -type f -name '*.fit' -printf '%TY-%Tm-%Td %p %s bytes\n' | sort
```

파일은 실제 활동 시작 날짜 기준으로 저장됩니다.

```text
activities/2026/10/18/12345678901.fit
activities/2026/10/19/12345678902.fit
activities/2026/10/19/12345678903.fit
```

위 Activity ID는 예시입니다. 동일 날짜에 여러 활동이 있으면 **같은 일별 폴더에 여러 FIT가 저장**됩니다.

### 증분 다운로드 동작

다음 명령을 다시 실행하면 기존 FIT는 기본 형식 검사 후 건너뛰고, 새 활동만 추가합니다.

```bash
.venv/bin/python scripts/sync_fit.py --days 7 --pause 3
```

### 현재 CLI 인자

| 인자 | 설명 |
| --- | --- |
| `--days 30` | 종료일 기준 최근 30일 재조회(기본값) |
| `--since YYYY-MM-DD` | 과거 수집 시작일 |
| `--until YYYY-MM-DD` | 수집 종료일(기본: 한국시간 오늘) |
| `--format fit` | ZIP 안의 원본 FIT 추출(기본값) |
| `--format zip` | Garmin 원본 ZIP 파일 그대로 보관 |
| `--max-downloads 3` | 신규 다운로드 개수 제한(테스트용) |
| `--pause 3` | 각 다운로드 후 대기 시간(초) |

`--days`의 경우 코드가 `종료일 - N일`부터 조회하므로 표기상 **경계일을 포함한 기간**이 됩니다. 테스트 시 계정 활동의 실제 목록과 비교해 누락 여부를 확인하십시오.

### ZIP 보관 옵션

```bash
.venv/bin/python scripts/sync_fit.py \
  --days 7 \
  --format zip \
  --max-downloads 2
```

ZIP과 FIT는 서로 다른 아카이브 파일로 관리됩니다. GPT에 개별 운동 FIT를 전달하기 쉽도록 **정기 운영은 기본 `fit` 유지**를 권장합니다.

---

## 8. GitHub에 최초 FIT Commit / Push 검증

**실행: garmin 계정**

배치 실행 전에 Git remote, 브랜치, 설정을 확인합니다.

```bash
cd /garmin/garmin-fit-pipeline

git config user.name 'Garmin FIT Collector'
git config user.email 'garmin-fit-collector@localhost'

git remote -v
git branch --show-current
git status --short
```

읽기/쓰기 SSH 인증은 `run_sync.sh`에서 아래와 같은 옵션을 명시적으로 사용합니다.

```text
GIT_SSH_COMMAND="ssh -i /home/garmin/.ssh/garmin_archive_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes"
```

이제 **FIT 수집 + Git Commit + Git Push** 전체를 실행합니다.

```bash
./scripts/run_sync.sh --days 7
```

완료 후 확인:

```bash
git status -sb
git log -3 --oneline
git ls-files activities | tail -30
git remote -v
```

GitHub 웹에서 [Repository의 activities 폴더](https://github.com/suh1027/garmin-fit-repository/tree/main/activities)에 업로드 파일이 보이는지 확인합니다.

**중요:** 수집 스크립트만 실행했을 때 다운로드된 기존 파일도 `run_sync.sh`의 `git add -A -- activities`에 포함되어 Push됩니다. 반면 `scripts`, `README.md`, `requirements.txt` 등은 배치가 자동 Stage하지 않습니다.

### Push 실패 시

`run_sync.sh`는 정상적인 새 데이터를 Commit한 후 Push합니다. Push 실패 시 로컬 Commit을 그대로 유지하므로 Git 이력을 임의로 재작성하지 않습니다.

```bash
git status -sb
git log --oneline origin/main..HEAD
```

원인(SSH 권한·원격 브랜치 변경·네트워크)을 해결한 뒤 재실행합니다.

```bash
./scripts/run_sync.sh --days 7
```

단, 원격과 로컬이 서로 다른 커밋으로 **분기(diverge)**하면 단순 재실행으로 해결되지 않을 수 있습니다. `git pull --ff-only`가 실패한 경우 원격/로컬 이력을 비교하고 충돌을 수동 정리합니다. `git push --force`로 덮어쓰지 않습니다.

---

## 9. 기존 Linux 서버의 서비스 배포 준비

**실행: sudo 권한이 있는 관리자 계정**

`garmin` 사용자 셸이었다면 `exit` 후 관리자 셸로 복귀합니다. 다음 두 파일을 **처음 설치할 때 또는 서비스 파일 변경이 있을 때만** 배포합니다.

```bash
sudo cp /garmin/garmin-fit-pipeline/systemd/garmin-fit-sync.service \
  /etc/systemd/system/

sudo cp /garmin/garmin-fit-pipeline/systemd/garmin-fit-sync.timer \
  /etc/systemd/system/
```

서비스 원본의 주요 값:

```ini
[Service]
Type=oneshot
User=garmin
WorkingDirectory=/garmin/garmin-fit-pipeline
Environment=HOME=/home/garmin
ExecStart=/garmin/garmin-fit-pipeline/scripts/run_sync.sh --days 30
TimeoutStartSec=45min
NoNewPrivileges=true
PrivateTmp=true
```

- `Type=oneshot`: 1회 실행하고 종료합니다.
- `User=garmin`: root가 아닌 전용 계정으로 다운로드와 Push를 수행합니다.
- `HOME=/home/garmin`: 토큰 및 SSH 키 경로를 맞춥니다.
- `TimeoutStartSec=45min`: 정기 배치 실행 시간 제한입니다. 과거 수년치 백필에는 정기 서비스 대신 **수동 배치**를 사용합니다.
- `PrivateTmp=true`: 서비스 전용 임시 디렉터리를 사용합니다.

---

## 10. systemd 정기 실행 — **매일 00:00 KST**

**요구사항: 매일 한국시간 자정에 FIT 다운로드 및 Git Push를 순차 실행**

현재 저장소의 `systemd/garmin-fit-sync.timer`는 **02:00 KST / RandomizedDelaySec=10min**으로 되어 있습니다. **이 문서는 README만 업데이트하므로 해당 원본 파일은 변경하지 않습니다.** 서버에는 아래 **drop-in override**를 설치해 실효 스케줄을 00:00 KST로 설정합니다. 기존 Linux 서버에 이미 타이머가 등록된 경우에도 동일하게 적용합니다.

### 10-1. Drop-in override 생성

**실행: 관리자 계정**

```bash
sudo mkdir -p /etc/systemd/system/garmin-fit-sync.timer.d

sudo tee /etc/systemd/system/garmin-fit-sync.timer.d/midnight-kst.conf >/dev/null <<'EOF'
[Timer]
OnCalendar=
OnCalendar=*-*-* 00:00:00 Asia/Seoul
AccuracySec=1s
RandomizedDelaySec=0
Persistent=true
EOF
```

설명:

- `OnCalendar=` 빈 값으로 원본의 **02:00 스케줄을 초기화**합니다.
- 새 `OnCalendar`에 `Asia/Seoul`을 명시하므로 시스템 시간대가 UTC이더라도 **00:00 KST**에 예약됩니다.
- `RandomizedDelaySec=0`은 기존의 최대 10분 무작위 지연을 제거합니다.
- `AccuracySec=1s`는 타이머 허용 정확도를 1초로 설정합니다. OS 스케줄링 및 부하 때문에 **정확히 00:00:00 실행을 보장하는 실시간 기능은 아닙니다.**
- `Persistent=true`는 서버 종료/타이머 비활성화로 놓친 일정을 활성화 후 보충할 수 있게 합니다. 여러 날짜를 놓쳤다고 그 횟수만큼 실행하지는 않습니다. 최근 30일 재조회가 누락 보충의 기본 수단입니다.

### 10-2. 설정 반영

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now garmin-fit-sync.timer
sudo systemctl restart garmin-fit-sync.timer
```

### 10-3. 동작 검증

```bash
sudo systemctl cat garmin-fit-sync.timer
sudo systemctl status garmin-fit-sync.timer --no-pager
sudo systemctl list-timers --all garmin-fit-sync.timer

systemd-analyze calendar '*-*-* 00:00:00 Asia/Seoul'
```

검증 사항:

1. `systemctl cat`에 `midnight-kst.conf`가 함께 출력되는지 확인합니다.
2. 최종 유효한 `OnCalendar`가 `00:00:00 Asia/Seoul`인지 확인합니다.
3. `list-timers`의 다음 예정 실행 시간이 **KST 자정**과 일치하는지 확인합니다.
4. 서버가 UTC라면 **전날 15:00 UTC = 다음 날 00:00 KST**로 표시될 수 있습니다.

### 10-4. 실제 서비스 수동 실행 및 로그 확인

```bash
sudo systemctl start garmin-fit-sync.service
sudo systemctl status garmin-fit-sync.service --no-pager
sudo journalctl -u garmin-fit-sync.service -n 100 --no-pager
```

`Type=oneshot` 서비스는 정상 종료 후 `inactive (dead)`로 표시될 수 있습니다. `Result=success`와 다운로드/Push 로그를 함께 확인합니다.

> **자정에 FIT와 Push가 모두 완료되는 것은 아닙니다.** 자정에 배치를 *시작*하고 `run_sync.sh`가 다운로드 후 Push를 수행합니다.

---

## 11. 과거 액티비티 전체 백필(Backfill)

최초에는 과거 FIT 데이터를 채워 넣는 별도 작업을 수행할 수 있습니다. 일일 배치와 충돌을 피하기 위해 타이머를 잠시 중지합니다.

**관리자 계정**

```bash
sudo systemctl stop garmin-fit-sync.timer
sudo -iu garmin
```

**garmin 계정**

```bash
cd /garmin/garmin-fit-pipeline

# 예: 2025년 전체
./scripts/run_sync.sh \
  --since 2025-01-01 \
  --until 2025-12-31 \
  --pause 3

# 예: 2026-01-01 ~ 2026-10-19
./scripts/run_sync.sh \
  --since 2026-01-01 \
  --until 2026-10-19 \
  --pause 3
```

대량 데이터는 **분기/월 단위**로 나눠 다운로드합니다. 수집기는 내부적으로 최대 30일 기간 단위로 API를 조회하지만, 실제 FIT 다운로드가 많으면 Garmin 제한 또는 인증 문제가 발생할 수 있습니다.

- `run_sync.sh`로 실행하면 백필 후 Git Commit/Push도 수행합니다.
- 백필 실행이 종료되면 정상 저장된 파일은 다음 배치에서 중복 다운로드하지 않습니다.
- 다운로드가 일부 실패해도 이미 저장된 FIT는 보존됩니다. 다시 범위를 조회해 누락을 보완할 수 있습니다.
- FIT 원본이 없는 일부 수동 액티비티는 원본 FIT 다운로드 자체가 불가능할 수 있습니다.
- 현재 코드에는 분기 전체를 고속 병렬 다운로드하는 기능이 없습니다. 계정 차단을 피하기 위해 요청 사이 간격을 유지합니다.

백필 종료 후 `exit`로 관리자 셸에 복귀:

```bash
sudo systemctl start garmin-fit-sync.timer
sudo systemctl list-timers --all garmin-fit-sync.timer
```

### 과거 월별 디렉터리 자동 이동

이전 구조에서 저장된 파일:

```text
activities/2026/10/12345678901.fit
```

해당 액티비티가 조회 범위에 있으면 다음처럼 이동합니다.

```text
activities/2026/10/19/12345678901.fit
```

API 조회 범위 밖에 있는 오래된 월별 파일은 자동으로 이동되지 않을 수 있으므로 필요한 과거 날짜를 백필해야 합니다.

---

## 12. 운영 모니터링과 유지보수

### 12-1. 자정 작업 실행 이력

**실행: sudo 권한이 있는 관리자 계정**

```bash
sudo systemctl list-timers --all garmin-fit-sync.timer
sudo systemctl show garmin-fit-sync.service -p Result -p ExecMainStatus
sudo journalctl -u garmin-fit-sync.service --since 'yesterday' --no-pager
sudo journalctl -u garmin-fit-sync.service -n 200 --no-pager
```

필요할 때 실시간 로그 확인:

```bash
sudo journalctl -u garmin-fit-sync.service -f
```

### 12-2. FIT 건수 및 사용량 확인

**실행: garmin 계정**

```bash
cd /garmin/garmin-fit-pipeline

find activities -type f -name '*.fit' | wc -l
du -sh activities .git
find activities -type f -name '*.fit' -printf '%p\n' | sort | tail -20
```

### 12-3. Git 상태/원격 동기화 확인

```bash
git status -sb
git log -5 --oneline
git log --oneline origin/main..HEAD
git remote -v
```

`git log origin/main..HEAD`에 커밋이 있으면 로컬에 원격으로 Push되지 않은 커밋이 남았을 가능성이 있습니다. `git fetch origin`으로 원격 상태를 갱신한 후 비교하면 더 정확합니다.

### 12-4. README 및 코드 업데이트 수신

GitHub의 파일은 Linux 서버에 자동 배포되지 않습니다. `garmin` 계정으로 **로컬 변경을 확인한 뒤** 안전하게 최신 내용을 가져옵니다.

```bash
cd /garmin/garmin-fit-pipeline
git status --short
git pull --ff-only origin main
git log -1 --oneline
```

`git pull` 전에 로컬에 미커밋 변경이 있다면 보존/커밋/스태시 여부를 먼저 판단합니다. `git reset --hard`로 작업물을 잃지 마십시오.

이번처럼 **README만 원격에서 수정한 경우**, `git pull`은 README만 반영합니다. **운영 타이머의 00:00 전환은 10장의 systemd drop-in 명령을 서버에서 별도로 적용해야 합니다.**

### 12-5. 타이머 일시 중지 / 재개

```bash
sudo systemctl stop garmin-fit-sync.timer
sudo systemctl start garmin-fit-sync.timer
```

### 12-6. Garmin 재인증

Garmin 세션 만료, 비밀번호 변경, Refresh Token 폐기 등으로 인증이 불가능해지면 `garmin` 계정에서 다음을 수행합니다.

```bash
cd /garmin/garmin-fit-pipeline
.venv/bin/python scripts/auth.py
```

토큰 파일을 로그나 채팅에 붙여 넣지 않습니다.

---

## 13. 장애 대응 매뉴얼

| 증상/오류 | 주요 원인 | 확인 및 조치 |
| --- | --- | --- |
| `Permission denied (publickey)` | Git이 사용자 지정 키를 선택하지 않음 | `ssh -T -i /home/garmin/.ssh/garmin_archive_ed25519 git@github.com` 검증 후 `GIT_SSH_COMMAND`로 Clone |
| SSH 테스트 성공, `git push` 실패 | Deploy Key 쓰기 권한/브랜치 보호 | GitHub **Settings → Deploy keys → Allow write access**, 브랜치 규칙 확인 |
| `fatal: not a git repository` | Clone 자체 실패 또는 다른 경로 | `pwd`, `ls -la .git`, `git status` 확인 |
| `destination path '.' already exists and is not an empty directory` | 기존 업로드 파일이 있는 폴더에 Clone | 3-C 절차로 별도 Clone 후 충돌 없는 통합 |
| `Host key verification failed` | `known_hosts` 누락/변경 | 공식 GitHub 호스트 키 지문을 확인하고 승인, 검증 우회 금지 |
| `fatal: Not possible to fast-forward` | 원격과 로컬 커밋 이력 분기 | `git fetch` / `git log`로 비교 후 수동 정리, 강제 Push 금지 |
| Python `ModuleNotFoundError` | `.venv` 의존성 설치 안 됨 | `.venv/bin/python -m pip install -r requirements.txt` |
| `Garmin token not found` | 최초 인증 누락 또는 다른 HOME | `sudo -iu garmin`으로 `scripts/auth.py` 재실행 |
| Garmin 401/403/429 | 토큰 만료, 인증 정책 변화, 요청 제한 | 로그/계정 확인, 재인증, 다운로드 빈도 조절 |
| FIT 다운로드 실패 | Garmin 원본 부재, API 변경, 네트워크 오류 | activityId 로그 확인 후 기간 재조회 |
| ZIP에 FIT 없음 | FIT가 없는 활동 또는 원본 구조 변화 | 원본 활동 형식 확인, 프로그램 오류 로그 확인 |
| 일별 폴더가 하루 차이 | 잘못된 Garmin 시간값/타임존 | `startTimeLocal` 및 GMT fallback 확인 |
| 자정 대신 02:00에 실행 | 서버에 override 미적용 | 10장의 `midnight-kst.conf` 적용, `systemctl cat` 확인 |
| 타이머가 실행되지 않음 | 비활성화/잘못된 경로/시계 오류 | `systemctl list-timers` / `journalctl` / `timedatectl` |
| 서비스 Timeout | 다운로드 과다, 응답 지연 | 정기 작업은 30일로 제한, 과거 전체는 수동 분할 백필 |
| `/garmin` 접근 거부 | Linux DAC/ACL 또는 SELinux | `namei -l`, `sudo ausearch -m AVC -ts recent` 검토 |

Rocky Linux 9에서 SELinux가 활성화되어 커스텀 `/garmin` 경로에 대한 실행/접근이 차단되면 **AVC 로그로 원인을 확인**합니다. 원인 분석 없이 `setenforce 0` 또는 `chmod -R 777`로 우회하지 않습니다.

---

## 14. 보안 및 운영 유의사항

1. **GitHub Repository는 Private로 유지**합니다. FIT에는 GPS 위치, 심박, 운동 시각 등 민감한 개인 정보가 포함될 수 있습니다.
2. **SSH Deploy Key의 개인키는 Git에 커밋하지 않습니다.** 권한은 `600`, 소유자는 `garmin`입니다.
3. Garmin Refresh Token은 `/home/garmin/.garminconnect`에만 보관합니다. `.gitignore`에 토큰 제외 규칙이 있어도 **리포지토리 외부 보관**이 기본입니다.
4. 배치의 Git Push는 단일 작성자 워크플로를 전제로 합니다. 같은 `main` 브랜치에 다른 작업이 동시에 Push되면 충돌할 수 있습니다.
5. GitHub의 일반 Git은 개별 파일 **100 MiB 초과를 차단**하고 50 MiB 초과부터 경고합니다. 누적 Repository 규모가 증가하면 Git LFS나 객체 스토리지를 검토합니다.
6. `git rm`으로 FIT를 삭제해도 기존 커밋 히스토리에는 파일이 남습니다. 저장소 공개 전환/협업자 추가 시 이 점을 고려합니다.
7. Garmin 연동 라이브러리는 공식 보장 API가 아닙니다. 로그인 방식 또는 응답 포맷 변경으로 언제든 동작이 중단될 수 있습니다.
8. 현재 프로젝트에는 서버 자체 알림·모니터링 서버가 포함되지 않습니다. 필요하면 systemd 실패 알림 또는 외부 모니터링을 추가할 수 있습니다.
9. GPT 분석을 위해서는 GitHub에 저장한 바이너리 FIT를 읽고 파싱하는 **별도의 조회/분석 경로**가 필요합니다. GitHub에 저장됐다는 사실만으로 채팅 모델이 FIT를 자동 파싱하는 것은 아닙니다.
10. **본 README만 변경한 현재 배포에서는 `systemd/garmin-fit-sync.timer` 원본이 그대로 02:00입니다.** 서버에서 drop-in override 적용 완료 여부를 운영 점검 항목으로 관리합니다.

---

## 15. 최종 설치·운영 검증 체크리스트

- [ ] Rocky Linux 9 / Python 3.12 설치 확인
- [x] `garmin` 실행 계정 생성
- [x] `/garmin/garmin-fit-pipeline` 디렉터리 생성
- [x] GitHub `suh1027/garmin-fit-repository` Deploy Key SSH 인증 성공
- [ ] GitHub Deploy Key의 **Allow write access** 확인
- [ ] `.git` 존재 및 `main`, `origin` 확인
- [ ] `scripts/auth.py` Garmin 최초 로그인 성공
- [ ] `/home/garmin/.garminconnect/garmin_tokens.json` 저장 확인
- [ ] FIT 1~3개 다운로드 성공
- [ ] `activities/YYYY/MM/DD/{activityId}.fit` 저장 확인
- [ ] 한 날짜의 다중 액티비티 FIT 파일 분리 확인
- [ ] 동일 기간 재실행 시 중복 다운로드 방지 확인
- [ ] `scripts/run_sync.sh`로 GitHub Commit/Push 성공
- [ ] `garmin-fit-sync.service` systemd 설치 및 수동 실행 성공
- [ ] **`midnight-kst.conf` 적용 후 00:00 KST 일정 확인**
- [ ] `journalctl`로 정기 배치 종료 및 오류 확인
- [ ] 과거 데이터 백필 필요 여부 판단

---

## 16. 핵심 명령 빠른 참조

```bash
# garmin 계정: 다운로드만 테스트
cd /garmin/garmin-fit-pipeline
.venv/bin/python scripts/sync_fit.py --days 7 --max-downloads 3

# garmin 계정: 수집 + Commit + Push
./scripts/run_sync.sh --days 30

# garmin 계정: 지정 기간 전체 백필
./scripts/run_sync.sh --since 2026-01-01 --until 2026-10-19

# 관리자 계정: 자정 자동 실행 상태 확인
sudo systemctl list-timers --all garmin-fit-sync.timer

# 관리자 계정: 수동 배치 실행
sudo systemctl start garmin-fit-sync.service

# 관리자 계정: 최근 100줄 로그
sudo journalctl -u garmin-fit-sync.service -n 100 --no-pager

# garmin 계정: FIT 파일 개수
find /garmin/garmin-fit-pipeline/activities -type f -name '*.fit' | wc -l
```

---

## 17. 참고 자료 및 변경 이력

**공식 / 프로젝트 문서**

- [python-garminconnect — 인증, Token Store 및 Activity API](https://github.com/cyberjunky/python-garminconnect)
- [GitHub — Managing deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys)
- [GitHub — SSH Host Key Fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)
- [systemd.timer — OnCalendar, AccuracySec, RandomizedDelaySec, Persistent](https://www.freedesktop.org/software/systemd/man/systemd.timer.html)
- [GitHub — File size limits](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)

**문서 변경 이력**

- **2026-10-19 / 전체 개정:** 실제 Rocky Linux 9, `garmin` 계정, `/garmin/garmin-fit-pipeline`, `suh1027/garmin-fit-repository` 기준으로 최초 구성부터 운영까지 통합.
- SSH 인증 성공 상태 및 일반 `git clone`에서 발생한 `publickey` 오류 해결 절차 반영.
- 날짜별 `YYYY/MM/DD` 다중 FIT 보관, Garmin 인증, 증분 다운로드, Git Push, 과거 백필/장애 복구 반영.
- **매일 00:00 KST** 운영을 위한 systemd drop-in 설정과 검증 절차 명시.
- **이 문서 배포 범위는 `README.md` 단일 파일**이며, 실제 Linux 서버 파일·서비스와 타이머 원본은 별도 변경하지 않음.


---

## 19. 현재 운영 구조와 ChatGPT 프로젝트 분석 가이드 (한국어)

> **이 섹션은 기존 README 본문을 보존하면서 추가한 최신 운영/분석 가이드입니다.** 과거 본문에 남아 있는 “Activity FIT만 수집”, “타이머 원본 02:00”, “Wellness 원본 ZIP을 저장” 등의 초기 구성 설명보다, 아래 **현재 코드 기준 설명을 우선**합니다. 기존 설치 기록과 문제 해결 이력은 삭제하지 않았습니다.
>
> **프로젝트 목적:** Garmin Connect의 운동 및 생체 데이터를 날짜별로 안전하게 축적한 뒤, **웹 ChatGPT의 GPT 프로젝트(Project)** 에서 GitHub 저장소 또는 필요한 파일을 참조하여 러닝 훈련, 회복, 피로, 레이스 퍼포먼스를 장기적으로 분석하기 위한 **개인 데이터 아카이브**입니다. 수집 자동화와 AI 분석은 분리되어 있습니다. **매일 자동 Push된다고 ChatGPT가 자동으로 분석을 실행하는 것은 아닙니다.**

### 19.1 실제 시스템 구성

```text
Garmin Device (Activity / Wellness / Performance)
       │ Garmin Connect sync
       ▼
Garmin Connect (authenticated session / stored tokens)
       │
       ▼
Rocky Linux 9 VM  [garmin user]
  /garmin/garmin-fit-pipeline/
       │
       ├── scripts/sync_fit.py           → activities/YYYY/MM/DD/{activityId}.fit
       ├── scripts/sync_health.py        → wellness/YYYY/MM/DD/*.json
       │                                → performance/YYYY/MM/DD/*.json
       │                                → performance/snapshots/YYYY/MM/DD/*.json
       ├── scripts/sync_wellness_raw.py  → wellness_raw/YYYY/MM/DD/*.fit
       │                                   (ZIP received/validated in memory,
       │                                    individual FIT files saved)
       └── scripts/run_sync.sh           → git pull → collectors → git commit/push
                   ▲
                   │
systemd: garmin-fit-sync.timer [00:00 Asia/Seoul, daily]
         → garmin-fit-sync.service (oneshot, User=garmin)
                   │
                   ▼
GitHub Private Repository: suh1027/garmin-fit-repository
                   │ permitted GitHub connection / file access
                   ▼
Web ChatGPT Project → FIT parsing + JSON alignment → AI running analysis
```

| 수집 영역 | 실제 파일 경로 | 분석 목적 |
| --- | --- | --- |
| Activity | `activities/YYYY/MM/DD/{activityId}.fit` | 페이스, 랩, 심박, 케이던스, 거리, 고도, 구간별 부하, 레이스 운영 |
| Wellness 원본 | `wellness_raw/YYYY/MM/DD/{id}_{type}.fit` | WELLNESS, HRV_STATUS, METRICS, SLEEP_DATA, SLEEP_DISRUPTIONS 등의 FIT 메시지·시계열 |
| Wellness API | `wellness/YYYY/MM/DD/{metric}.json` | 수면, HRV, 심박, 스트레스, Body Battery, 일별 요약 |
| Performance API | `performance/YYYY/MM/DD/training_readiness.json` | 해당 날짜의 Training Readiness 응답(가용한 경우) |
| Performance 스냅샷 | `performance/snapshots/YYYY/MM/DD/*.json` | VO₂max, Training Status, Load Focus 등의 **조회 시점** 스냅샷 |

**중요한 날짜 규칙**

- Activity FIT 폴더는 Garmin 활동의 현지 시작일(`startTimeLocal`, 없으면 GMT를 KST로 변환)을 사용합니다.
- Wellness JSON과 Wellness Raw의 일별 수집은 **오늘을 제외한 완료된 날짜**를 조회합니다. 자정을 지나는 수면·생체 FIT는 실제 내부 타임스탬프가 폴더의 API 요청 날짜와 다를 수 있습니다.
- `performance/snapshots/`는 측정일의 확정된 과거 값이 아니라 **스냅샷을 조회·수집한 날짜**입니다. 이를 과거 일별 VO₂max 실측치처럼 취급하지 않습니다.
- 비어 있거나 API가 제공하지 않는 지표는 저장되지 않을 수 있습니다. 폴더에 파일이 없다고 해서 측정값이 반드시 0인 것은 아닙니다.
- Wellness FIT와 Wellness JSON은 일부 값이 중복되지만 완전히 동일한 데이터가 아닙니다. **원본 FIT 보존 + Garmin 계산 지표 JSON 보존**을 원칙으로 합니다.

### 19.2 설치·설정 빠른 가이드 (Rocky Linux 9)

기존 README 앞부분의 운영 서버 구성 절차를 유지합니다. 새 서버에서는 아래 **최신 통합 수집 설정**도 적용해야 합니다. 환경별 권한과 패키지 설치 정책에 맞춰 조정하세요.

1. Rocky Linux 9에 `git`, `unzip` 및 **Python 3.12 권장** 환경을 준비합니다. `garmin` 사용자와 `/garmin/garmin-fit-pipeline` 작업 디렉터리를 생성합니다.
2. GitHub에서 **Private Repository**를 생성하거나 기존 저장소를 사용합니다. `garmin` 계정의 SSH Deploy Key 공개키를 해당 Repository에 등록하고 **쓰기 권한**을 허용합니다. 개인키는 `/home/garmin/.ssh/garmin_archive_ed25519`에 권한 600으로 보관합니다.
3. `garmin` 계정으로 소스를 Clone하고 venv 및 패키지를 설치합니다.

```bash
sudo -iu garmin
cd /garmin
GIT_SSH_COMMAND='ssh -i /home/garmin/.ssh/garmin_archive_ed25519 -o IdentitiesOnly=yes' \
  git clone git@github.com:suh1027/garmin-fit-repository.git garmin-fit-pipeline
cd /garmin/garmin-fit-pipeline
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/auth.py
```

이미 Clone된 서버에서는 다시 Clone하지 마세요. `scripts/auth.py`는 최초 Garmin 로그인/MFA를 대화형으로 수행하며, 인증 토큰은 기본적으로 `/home/garmin/.garminconnect/`에 저장됩니다. 토큰 파일·암호·개인키는 **절대 Git에 추가하지 않습니다.**

4. 프로젝트 루트에 Git에서 제외되는 `.collector.env`를 만들고 파일 접근을 제한합니다.

```bash
cd /garmin/garmin-fit-pipeline
cat > .collector.env <<'EOF'
ENABLE_HEALTH_JSON=1
HEALTH_DAYS=3
ENABLE_WELLNESS_RAW=1
WELLNESS_DAYS=3
EOF
chmod 600 .collector.env
```

- 위 값은 **권장 예시**입니다. 실제 서버 설정은 `cat .collector.env`로 확인하세요.
- `HEALTH_DAYS=3`과 `WELLNESS_DAYS=3`은 완료된 지난 3일을 다시 조회합니다. Garmin 동기화가 늦어지는 경우를 보완합니다.
- Activity 조회 기간은 `.collector.env`가 아니라 `run_sync.sh --days N` 인자로 제어합니다. GitHub의 `systemd/garmin-fit-sync.service` 원본은 **`--days 30`**입니다. 서버의 `ExecStart` drop-in Override로 `--days 3`을 설정한 경우 실제 적용값이 우선합니다.
- `sync_fit.py --days 3`은 기본 구현상 **오늘부터 3일 전까지 경계일 포함** 조회합니다. Wellness의 “완료된 3일”과 날짜 범위가 조금 다릅니다.

5. 수집기가 정상 동작하는지 먼저 수동 검증합니다.

```bash
cd /garmin/garmin-fit-pipeline
.venv/bin/python -m py_compile scripts/*.py
bash -n scripts/run_sync.sh
.venv/bin/python scripts/sync_fit.py --days 3
.venv/bin/python scripts/sync_health.py --days 3
.venv/bin/python scripts/sync_wellness_raw.py --mode api --days 3
find wellness_raw -type f -name '*.fit' -printf '%h\n' | sort | uniq -c
```

`sync_wellness_raw.py`는 Garmin API의 Wellness ZIP 응답을 **메모리에서 검증·해제한 뒤 개별 FIT로 저장**합니다. 기본 운영에서는 새 `wellness_original.zip`을 기록하지 않습니다. 과거 ZIP이 있다면 `--mode import --date YYYY-MM-DD --import-file <ZIP 경로>`로 변환할 수 있습니다.

6. systemd 서비스/타이머 파일을 적용합니다(관리자 권한).

```bash
sudo cp /garmin/garmin-fit-pipeline/systemd/garmin-fit-sync.service /etc/systemd/system/
sudo cp /garmin/garmin-fit-pipeline/systemd/garmin-fit-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now garmin-fit-sync.timer
sudo systemctl cat garmin-fit-sync.service
sudo systemctl cat garmin-fit-sync.timer
sudo systemctl list-timers --all garmin-fit-sync.timer
```

현재 GitHub 타이머 원본은 **`OnCalendar=*-*-* 00:00:00 Asia/Seoul`**, `AccuracySec=1s`, `RandomizedDelaySec=0`, `Persistent=true`입니다. 서버에 기존 drop-in이 있다면 `systemctl cat`과 `systemctl show -p ExecStart garmin-fit-sync.service`로 **실효 설정**을 검증하세요. systemd 방식은 SSH 세션을 종료해도 실행됩니다.

7. 전체 수집 및 GitHub Push를 즉시 시험할 때는 `garmin` 계정에서 다음을 실행합니다.

```bash
cd /garmin/garmin-fit-pipeline
./scripts/run_sync.sh --days 3
git status -sb
```

`run_sync.sh`는 `.collector.env`를 읽고, `flock`으로 중복 실행을 방지하며, Git Pull → 각 수집기 → 데이터 파일 Git Add/Commit → Push를 수행합니다. 원격 브랜치와 로컬의 커밋 이력이 갈라지면 `git pull --ff-only` 또는 Push가 실패할 수 있으며 **강제 Push하지 않습니다**. 실행 로그는 `sudo journalctl -u garmin-fit-sync.service -n 150 --no-pager`로 확인합니다.

> **보안:** FIT에는 GPS 이동 경로와 생체·운동 정보가 포함될 수 있습니다. GitHub Repository를 Private으로 유지하고 ChatGPT/GitHub 연결 범위를 최소화하세요. `.collector.env`, Garmin 토큰, SSH 개인키, 암호, MFA 코드는 AI 분석용 입력에 포함하지 않습니다.

### 19.3 웹 ChatGPT 프로젝트에 연결하는 방법

1. ChatGPT에서 예: **Garmin Running Performance Analysis** 프로젝트를 생성합니다.
2. 프로젝트의 **지침(Project instructions)** 에 아래 19.6의 한국어 지침을 그대로 붙여 넣습니다. 영어 기반 프로젝트라면 20.5의 영어 지침을 사용합니다. **둘 다 동시에 붙일 필요는 없습니다.**
3. GitHub 연동/연결 기능을 사용할 수 있는 환경이라면 **본인이 접근 권한을 가진** `suh1027/garmin-fit-repository`를 연결하여 필요한 파일을 읽습니다. 프로젝트 지침을 적는 것만으로 Private Repository 접근 권한이 생성되지는 않습니다. 기능 제공 범위와 실제 파일 접근 여부를 먼저 확인해야 합니다.
4. FIT 파일은 **바이너리**입니다. GitHub 텍스트 조회로 FIT를 읽지 못하면 파일을 다운로드해 프로젝트 대화에 첨부하거나, 신뢰할 수 있는 FIT 파서로 운동 데이터를 CSV/JSON으로 변환해 첨부합니다. FIT를 텍스트처럼 추측하여 해석하지 않습니다.
5. AI 분석은 사용자가 프로젝트에서 질문하거나 별도 실행 워크플로를 구성할 때 수행됩니다. **systemd 타이머는 수집/Push만 자동화합니다.** ChatGPT 프로젝트 자체가 매일 00:00에 자동으로 GitHub를 동기화·분석하는 것은 아닙니다.
6. 분석 전에 **분석 기간, 파일 접근 성공 여부, 최신 동기화 날짜**를 확인합니다. 연결 파일이 없거나 오래되었다면 그 사실을 밝히고 추가 자료를 요청합니다.

### 19.4 파일을 어떤 순서로 분석할 것인가

| 분석 질문 | 우선 파일 | 보조 파일 | 핵심 검증 |
| --- | --- | --- | --- |
| 오늘 훈련 강도/구간 분석 | `activities/.../*.fit` | `wellness/.../hrv.json`, `sleep.json` | 시간 순서, 이동/정지 구간, GPS 오류, 심박 센서 유형 |
| 주간 훈련량 및 강도 분포 | 최근 7~28일 Activity FIT | `performance/.../training_readiness.json` | 중복 운동 ID 제거, 종목 구분, 거리·시간·부하 일관성 |
| HRV·회복·피로 추세 | `wellness/.../hrv.json`, `sleep.json`, `body_battery.json` | `wellness_raw/.../*HRV_STATUS.fit` 및 `*SLEEP_DATA.fit` | 날짜 경계, 기준선, 누락일, 계산값/원본 차이 |
| 심박/스트레스 변화 | `wellness/.../heart_rate.json`, `stress.json` | `wellness_raw/.../*WELLNESS.fit` | 운동 중/휴식 중 구분, 손목 광학센서 오류 가능성 |
| VO₂max·레이스 준비도 변화 | `performance/snapshots/.../vo2max.json`, `training_status.json`, `load_focus.json` | Activity FIT 및 레이스 실적 | 스냅샷 날짜와 실제 추정치 갱신 시점 혼동 방지 |
| 목표 페이스·예상 기록 | 최근 레이스/템포/롱런 Activity FIT | HRV·수면·Readiness·훈련량 | 최근 기록·환경·고도·기온·신발·주관적 피로 함께 고려 |

**권장 분석 절차**

1. **기간 확정:** 요청일 기준 KST, 최근 7일(회복), 28일(훈련 추세), 8~12주(레이스 준비) 중 선택합니다. 분석 요청이 특정 활동이라면 해당 Activity FIT부터 열어봅니다.
2. **인벤토리:** 각 디렉터리의 날짜·파일·활동 ID를 확인합니다. 파일 부재를 `0`으로 보간하지 말고 “데이터 없음/미확인”으로 표시합니다.
3. **FIT 파싱:** 호환되는 FIT 디코더로 `session`, `lap`, `record` 등 메시지를 읽습니다. 시간(UTC→KST), 종목, 거리(m), 속도(m/s), 이동 시간과 경과 시간, 심박(bpm), 케이던스, 파워(W), 고도(m)를 필드 정의에 따라 변환합니다. **존재하지 않는 필드를 만들지 않습니다.**
4. **운동 분석:** 총/이동 거리·시간, 평균/구간 페이스, 랩별 심박·파워·케이던스, 심박 드리프트, 페이스 변동, 인터벌·회복 구간, 언덕 영향 등을 평가합니다. 기록된 값과 추정값을 구별합니다.
5. **Wellness 결합:** 각 활동의 현지 날짜 ±1일 및 최근 7/28일 HRV·수면·Body Battery·안정시 심박·스트레스 등을 살핍니다. 수면은 시작/종료일과 Garmin의 귀속 날짜를 확인합니다.
6. **Performance 결합:** VO₂max·Training Status·Readiness·Load Focus는 Garmin **알고리즘 결과**라는 점을 밝힙니다. 스냅샷을 임의로 과거 날짜에 소급 배치하지 않습니다.
7. **중복·품질 검사:** Activity FIT와 Wellness FIT/JSON에서 같은 원시 심박 샘플을 이중으로 더하지 않습니다. 이상치, 샘플 누락, 타임존 불일치, 센서 드롭아웃, 손목 심박의 케이던스 락(cadence lock) 가능성을 검토합니다.
8. **비교·해석:** 절대 수치뿐 아니라 개인 기준선·최근 훈련 맥락을 우선합니다. HRV/VO₂max 단기 변동만으로 컨디션·질환·실력을 단정하지 않습니다.
9. **출력:** 결론 → 근거가 되는 날짜/활동 ID/파일 경로 → 수치·추세 → 데이터 한계 → 구체적 훈련·회복 제안 순서로 답변합니다. 분석에 사용한 파일이 무엇인지 명시합니다.

**계산 규칙:** 속도가 `v` m/s일 때 페이스(min/km)는 `1000 / v / 60`입니다(`v > 0`). FIT의 거리와 속도가 다른 단위·스케일을 쓸 수 있으므로 디코더의 필드 정의를 적용합니다. 운동 시간이 경과 시간인지 실제 이동 시간인지 반드시 구분합니다.

### 19.5 권장 분석 결과 형식

- **분석 범위:** 기간/KST, 확인한 파일 수와 활동 ID, 수집 누락 여부
- **훈련 요약:** 총 거리·운동 시간·종목·주간 증가율·강도 분포(정의 명시)
- **주요 운동:** 페이스/심박/케이던스/구간별 패턴, 고강도 지속 능력, 회복 구간 질
- **회복 상태:** HRV 기준선 대비, 수면 시간/점수, 안정시 심박, Body Battery, Readiness(가용 항목만)
- **레이스 예측:** 조건부 기록 범위·전제 조건·근거 및 불확실성
- **실행 제안:** 3~7일 훈련/회복 계획, 추가로 확인할 정보
- **증거:** 각 결론의 원천 파일 경로(예: `activities/2026/10/18/123456789.fit`는 *경로 형식 예시*, 실제 파일 존재를 의미하지 않음)

### 19.6 ChatGPT 프로젝트 지침 — 한국어 복사용

아래 코드 블록을 **프로젝트 지침**에 그대로 붙여 넣을 수 있습니다.

```text
역할
당신은 Garmin Connect 데이터 기반 러닝·마라톤 퍼포먼스 분석가다.
목적은 개인의 활동 FIT, Wellness FIT, Wellness JSON, Performance JSON을 함께 분석하여
훈련 효과, 회복 상태, 부하 관리, 레이스 준비도와 예상 기록을 근거 중심으로 평가하는 것이다.
의료 진단이나 보장된 경기 기록 예측을 하지 않는다.

데이터 소스
- GitHub Private Repository: suh1027/garmin-fit-repository
- Activity: activities/YYYY/MM/DD/{activityId}.fit
- Wellness 원본: wellness_raw/YYYY/MM/DD/*.fit
- Wellness API: wellness/YYYY/MM/DD/*.json
- Performance API: performance/YYYY/MM/DD/*.json
- 현재 성과 스냅샷: performance/snapshots/YYYY/MM/DD/*.json
- 현지 시간대: Asia/Seoul (KST)
- GitHub 연결이 안 되거나 FIT 바이너리를 읽을 수 없으면, 접근 가능 여부를 정확히 보고하고
  사용자에게 필요한 원본 FIT 또는 파싱된 CSV/JSON을 요청한다.
- 프로젝트 지침에 파일 경로가 있다고 해서 실제 파일이 읽힌 것으로 간주하지 않는다.

자료 선정
1. 사용자가 지정한 날짜·종목·활동 ID·훈련 목적을 우선한다.
2. 단일 운동 분석은 해당 Activity FIT, 전후 1일 회복 데이터, 최근 7~28일 기준선을 우선 조회한다.
3. 주간 훈련 분석은 최근 7일과 이전 7일을 비교하고, 가능하면 28일 추세를 제공한다.
4. 레이스 예측은 최근 8~12주의 운동 데이터, 실전 레이스, 롱런, 템포·인터벌,
   수면·HRV·퍼포먼스 지표를 함께 검토한다.
5. 파일 목록을 먼저 확인하고, 실제로 읽은 파일의 경로·날짜·활동 ID를 명시한다.

분석 규칙
1. FIT는 호환 파서로 메시지를 해석한다. 바이너리 내용을 문자열로 추정하지 않는다.
2. FIT와 JSON의 단위, KST 날짜, 수면 귀속일, 정지/이동 시간, 종목 및 센서 종류를 확인한다.
3. 거리·시간·페이스·심박·케이던스·파워·고도·랩 정보는 존재하는 값만 사용한다.
4. 운동 강도와 훈련량은 개인 기준선, 목표 레이스, 최근 훈련량을 바탕으로 판단한다.
   임의의 심박 존·젖산역치·FTP·최대심박·VO2max 기준을 만들어 넣지 않는다.
5. Wellness FIT와 JSON 중복 시 같은 데이터의 중복 집계는 피한다.
   Garmin 계산 점수(수면 점수, Body Battery, Training Readiness, VO2max 등)는
   원본 측정치가 아니라 알고리즘 추정/가공 지표로 취급한다.
6. performance/snapshots는 '수집 날짜의 스냅샷'이며 과거 날짜의 실측치로 간주하지 않는다.
7. 데이터 누락, 손목 광학심박 오류, GPS 오류, 운동 중 수동 일시정지,
   트레일 고도·날씨·신발 차이 등을 검토한다.
8. 체감 강도, 통증, 더위, 보급, 수면, 심리 상태 등 사용자가 제공한 주관적 정보도 함께 반영한다.
9. 수치가 충돌하면 원본 파일의 정의와 날짜·샘플링을 대조하고, 결정할 수 없으면 불확실성을 밝힌다.
10. HRV 감소나 VO2max 변동만으로 과훈련·질병·심장 이상을 진단하지 않는다.
    지속적인 흉통·실신 등 위험 증상은 의료 평가를 권고한다.
11. 레이스 기록 예측은 단일 숫자 확정값 대신 조건부 범위와 전제조건을 제시한다.
12. 실제로 접근하거나 계산하지 않은 데이터의 수치, 파일, 분석 결과를 만들어내지 않는다.

답변 형식
- 먼저 핵심 결론 3~5개를 간결하게 제시한다.
- 이어서 분석 기간, 확인한 파일/활동 ID, 주요 수치를 표로 정리한다.
- 페이스·심박·회복·훈련량 간 관계를 근거와 함께 상세히 설명한다.
- 관측 사실, 해석, 가설을 구분한다.
- 레이스나 훈련 계획은 실천 가능한 페이스·거리·강도·회복 전략으로 제안한다.
- 마지막에 데이터 한계 및 추가로 필요한 자료를 명시한다.
- 사용자 요청이 한국어이면 한국어로 답변한다.
```

**프로젝트에서 사용할 질문 예시**

- “최근 28일 Activity FIT와 HRV·수면 데이터를 종합해서 훈련 부하와 피로 누적을 분석해줘.”
- “10월 18일 인터벌 FIT를 구간별로 분해하고 최근 4주 기록과 비교해줘.”
- “최근 레이스와 롱런 데이터를 바탕으로 풀마라톤 목표 페이스를 보수적/중립적/공격적으로 예측해줘.”
- “이번 주와 지난주 데이터를 비교해 심박 대비 페이스 효율, 회복 상태, 다음 주 훈련 수정안을 제시해줘.”

---

## 20. English — Current Architecture, Installation, and ChatGPT Project Guide

> **Preservation note:** All earlier README sections remain intact. This section documents the current integrated collector and supersedes older FIT-only, 02:00 timer, or ZIP-storage descriptions where they differ.
>
> **Purpose:** This is a **private Garmin Connect data archive for AI-assisted running and marathon analysis in a web ChatGPT Project**. A Rocky Linux host collects and pushes training, wellness, and performance files to GitHub. ChatGPT accesses the authorized repository or supplied files when asked to analyze them. **Automatic collection does not imply automatic AI analysis.**

### 20.1 Architecture and file layout

```text
Garmin Device → Garmin Connect → Rocky Linux 9 (garmin user)
  ├─ sync_fit.py         → activities/YYYY/MM/DD/{activityId}.fit
  ├─ sync_health.py      → wellness/YYYY/MM/DD/*.json
  │                       performance/YYYY/MM/DD/*.json
  │                       performance/snapshots/YYYY/MM/DD/*.json
  ├─ sync_wellness_raw.py → wellness_raw/YYYY/MM/DD/*.fit
  │                       (ZIP is an in-memory transport, not a saved artifact)
  └─ run_sync.sh         → fast-forward pull → collection → commit → push
         ▲
         └─ systemd timer: daily 00:00 Asia/Seoul
                               ↓
                GitHub private repository
                               ↓
                 Web ChatGPT Project analysis
```

| Source | What to inspect | Typical questions |
| --- | --- | --- |
| `activities/YYYY/MM/DD/{activityId}.fit` | Session, lap, record timestamps, pace, distance, HR, cadence, power, elevation | Workout execution, intervals, race pacing, weekly load |
| `wellness_raw/YYYY/MM/DD/*.fit` | WELLNESS, HRV_STATUS, METRICS, SLEEP_DATA, SLEEP_DISRUPTIONS when present | Raw wellness messages, timestamps, detailed physiological history |
| `wellness/YYYY/MM/DD/*.json` | Sleep, HRV, heart rates, stress, body battery, daily stats | Recovery, fatigue and baseline trends |
| `performance/YYYY/MM/DD/*.json` | Training Readiness when available | Daily readiness |
| `performance/snapshots/YYYY/MM/DD/*.json` | VO₂max, Training Status and Load Focus snapshots | Trends in Garmin's calculated metrics |

**Date semantics and limitations**

- Activity folders use the activity's local start date, falling back to GMT converted to KST.
- Health JSON and Wellness FIT are collected for previously completed local days. Sleep and raw FIT timestamps can cross midnight; use internal timestamps rather than assuming every sample belongs to the folder date.
- Performance snapshots reflect the **date they were fetched**, not necessarily when Garmin recalculated the metric.
- Missing files are missing/unsupported/unavailable data, **not zero-valued measurements**.
- Keep both Wellness FIT and JSON: they can overlap, but Garmin's derived scores are not necessarily reproducible from raw FIT messages.

### 20.2 Installation and daily operation

**Prerequisites:** Rocky Linux 9, `garmin` service account, Python 3.12 recommended, Git, an SSH write-enabled Deploy Key for a **private** GitHub repository, and interactive initial Garmin authentication.

```bash
# Run as garmin after OS/account/SSH key preparation
cd /garmin
GIT_SSH_COMMAND='ssh -i /home/garmin/.ssh/garmin_archive_ed25519 -o IdentitiesOnly=yes' \
  git clone git@github.com:suh1027/garmin-fit-repository.git garmin-fit-pipeline
cd /garmin/garmin-fit-pipeline
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/auth.py
```

On an already deployed host, **do not clone again**. The authentication script stores tokens outside the repository in `~/.garminconnect/`. Never commit tokens, passwords, MFA codes, SSH private keys, or `.collector.env`.

Create the local configuration:

```bash
cat > /garmin/garmin-fit-pipeline/.collector.env <<'EOF'
ENABLE_HEALTH_JSON=1
HEALTH_DAYS=3
ENABLE_WELLNESS_RAW=1
WELLNESS_DAYS=3
EOF
chmod 600 /garmin/garmin-fit-pipeline/.collector.env
```

**These are recommended example values, not a claim about the server's unseen current file.** The runner sources `.collector.env` at each execution, so SSH logout does not remove the settings. Health and Wellness look back over three **completed** days. Activity lookback is controlled by `run_sync.sh --days N`.

**Important actual-code detail:** `systemd/garmin-fit-sync.service` in GitHub currently calls `run_sync.sh --days 30`, not three days. To use a three-day Activity lookback on a particular host, configure and verify an `ExecStart` systemd drop-in override. The timer source itself is correctly set to **daily 00:00 KST**.

```bash
# Verify collectors as garmin
cd /garmin/garmin-fit-pipeline
.venv/bin/python scripts/sync_fit.py --days 3
.venv/bin/python scripts/sync_health.py --days 3
.venv/bin/python scripts/sync_wellness_raw.py --mode api --days 3
./scripts/run_sync.sh --days 3

# Install and enable systemd units as an administrator
sudo cp systemd/garmin-fit-sync.service /etc/systemd/system/
sudo cp systemd/garmin-fit-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now garmin-fit-sync.timer
sudo systemctl cat garmin-fit-sync.service
sudo systemctl cat garmin-fit-sync.timer
sudo systemctl list-timers --all garmin-fit-sync.timer
sudo journalctl -u garmin-fit-sync.service -n 150 --no-pager
```

The timer is a persistent systemd timer, not an interactive shell job. The runner locks against concurrent execution, attempts a fast-forward Git pull, runs the three collectors, commits changed data and pushes to `main`. If local and remote histories diverge, resolve the conflict; **never force-push as a routine recovery method**. For manual backfills, use `sync_fit.py --since YYYY-MM-DD --until YYYY-MM-DD` for Activity FIT, and supported `--days` or `--date` options for Wellness collectors.

Garmin Wellness raw collection uses an unofficial endpoint that may change. The program validates the downloaded ZIP and FIT payloads, extracts individual FIT files by requested day, and does not create new permanent Wellness ZIP files. Previously downloaded ZIPs can be converted via `--mode import --date YYYY-MM-DD --import-file <path>`.

### 20.3 Connecting the repository to a ChatGPT Project

1. Create a ChatGPT Project (e.g., **Garmin Running Performance Analysis**) and paste the instructions from **Section 20.5** into its **Project instructions**. For a Korean-language project, use Section 19.6 instead.
2. When GitHub integration is available and authorized, connect/access `suh1027/garmin-fit-repository`. Merely mentioning a private repository in project instructions **does not grant access**.
3. FIT files are binary. If the connected GitHub reader cannot retrieve binary FIT data, download and attach the FIT files, or upload a **faithful parser-generated CSV/JSON representation** of their records. Never pretend to have parsed an inaccessible FIT file.
4. State which file paths, dates and activity IDs were actually accessed. If fresh repository data is unavailable, request the relevant files rather than assuming automatic synchronization.
5. ChatGPT analysis is triggered by a user request or a separately configured supported workflow, **not by the Linux midnight timer**.

### 20.4 Recommended analytical workflow

1. **Select the interval:** Single activity; 7/28-day training and recovery trends; or 8–12 weeks before a marathon.
2. **Inventory the files:** Check dates, duplicate activity IDs, missing samples, source freshness and sport type.
3. **Parse FIT properly:** Decode session/lap/record messages, timestamps and documented units (m, s, m/s, bpm, W, etc.). Do not guess message fields or pretend binary files are text.
4. **Analyze workouts:** Compare lap pace, effort, heart rate, cadence, running power when available, elevation, speed/HR drift, recovery jogs and pauses. Distinguish elapsed, moving and timer time.
5. **Join wellness records:** Compare sleep, HRV, resting HR, stress and Body Battery around workout dates and to a multiweek personal baseline. Consider midnight-crossing sleep and actual FIT message timestamps.
6. **Join performance metrics:** Treat VO₂max, Training Status, Training Readiness and Load Focus as **Garmin-derived estimates**; snapshot paths are collection-date snapshots.
7. **Check quality:** Wrist optical HR artifacts, cadence lock, missing GPS points, rate limits, late device synchronization, duplicate HR streams and unit mismatches.
8. **Interpret conservatively:** Consider temperature, course elevation, shoes, fueling, subjective fatigue, pain, stress and prior races. A single HRV/VO₂max fluctuation does not prove fitness loss, overtraining or illness.
9. **Report with evidence:** Findings first, then actual source paths/activity IDs, metrics, uncertainty, conditional race estimates and practical next steps.

**Pace conversion:** For speed `v` in meters per second, `pace (min/km) = 1000 / v / 60` when `v > 0`. Confirm the decoder's FIT field scaling. Do not equate moving pace with total race elapsed pace.

### 20.5 ChatGPT Project instructions — English copy/paste

```text
Role
You are a data-grounded running and marathon performance analyst using Garmin Connect data.
Analyze training effectiveness, fatigue, recovery, workload management, race readiness
and conditional race-time estimates. Do not offer definitive medical diagnoses
or guarantee race outcomes.

Repository and sources
- Private GitHub repository: suh1027/garmin-fit-repository
- Activities: activities/YYYY/MM/DD/{activityId}.fit
- Raw wellness: wellness_raw/YYYY/MM/DD/*.fit
- Wellness API data: wellness/YYYY/MM/DD/*.json
- Daily performance: performance/YYYY/MM/DD/*.json
- Performance snapshots: performance/snapshots/YYYY/MM/DD/*.json
- Time zone: Asia/Seoul (KST).
- Verify actual repository/file access. Instructions alone do not grant access.
- FIT files are binary; use a real FIT parser or request original files or
  parser-generated CSV/JSON if the connector cannot read binary data.
- Never claim a source was read when it was not accessible.

Retrieval priorities
1. Honor user-specified dates, sport types, activity IDs and goals.
2. For a workout, inspect its Activity FIT, surrounding recovery data,
   and 7–28 days of training for context.
3. For weekly trends, compare the latest 7 days against the previous 7 days
   and use a 28-day baseline when available.
4. For race forecasts, use 8–12 weeks of running, actual races, long runs,
   threshold workouts, training volume, and available wellness/performance data.
5. Report which dates, paths and activity IDs were actually inspected.

Method and safeguards
1. Decode FIT session/lap/record messages with documented units and timestamps.
2. Distinguish elapsed time, timer time, moving time, stopped periods and sport types.
3. Analyze only available metrics: duration, distance, pace, HR, cadence,
   power, elevation and laps/intervals where supplied.
4. Interpret intensity using the user's known personal baseline and training goals;
   do not invent max HR, HR zones, lactate threshold, FTP or VO2max values.
5. Avoid double-counting overlapping measurements across Activity FIT,
   Wellness FIT and Wellness JSON.
6. Treat sleep scores, Body Battery, Readiness, VO2max and training-status labels
   as Garmin-calculated metrics, not direct physiological ground truth.
7. Performance snapshots are values captured on the collection date,
   not necessarily historical measurements for that calendar day.
8. Check missing data, late uploads, wrist optical HR artifacts, cadence lock,
   GPS outliers, pauses, weather, course elevation and shoe differences.
9. Integrate user-reported RPE, fatigue, sleep quality, pain, motivation and fueling.
10. Distinguish observations from interpretation and speculation; disclose gaps.
11. Do not diagnose overtraining, cardiac conditions or illness from isolated trends.
    Recommend medical evaluation for concerning persistent symptoms.
12. Provide race-time estimates as conditional ranges with assumptions, not certainties.
13. Never invent a file, value, chart, workout or analysis result.

Answer format
- Start with 3–5 concise findings.
- State date range, data freshness, accessed files and activity IDs.
- Show a compact metrics/trends table if data supports one.
- Analyze pace, HR, workload, recovery and race readiness with explicit evidence.
- Clearly separate observed measurements, interpretations and hypotheses.
- Give specific actionable training/recovery suggestions.
- End with uncertainty, missing information and recommended follow-up inputs.
- Use the user's requested language.
```

**Example Project questions**

- “Analyze my last 28 days of Activity FIT, HRV and sleep data for accumulated fatigue and training adaptations.”
- “Break down my October 18 interval session by lap and compare it to the previous four weeks.”
- “Estimate conservative/base/aggressive marathon pacing scenarios using recent races and long runs.”
- “Compare the current and previous weeks for pace-to-heart-rate efficiency, recovery and practical adjustments.”

### 20.6 Privacy, provenance, and limitations

This archive contains sensitive personal physiology and may contain GPS location history. Keep the repository private, grant GitHub/app access deliberately, and do not upload credentials. The unofficial Garmin Connect download methods and schema may change without notice. Do not assume all Garmin metrics are available every day or that the FIT and JSON values have identical definitions. Always verify the source and completeness before citing a figure.

**Documentation update (2026-10-19):** Added bilingual architecture, current FIT-only Wellness behavior, installation/operations reference, data selection and parsing rules, evidence/quality criteria, and reusable Korean/English ChatGPT Project instructions. Earlier README content has been preserved.
