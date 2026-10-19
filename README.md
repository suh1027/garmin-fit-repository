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
