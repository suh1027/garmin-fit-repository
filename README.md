# Garmin Connect → Rocky Linux 9 → GitHub FIT 파이프라인 (v3)

> 실환경 확정값: Linux 사용자 `garmin` · 설치 경로 `/garmin/garmin-fit-pipeline` · GitHub Private `suh1027/garmin-fit-repository` · SSH 키 `/home/garmin/.ssh/garmin_archive_ed25519` · 원본 FIT 경로 `activities/YYYY/MM/DD/{activityId}.fit`.
>
> SSH 키 인증은 `ssh -T -i ~/.ssh/garmin_archive_ed25519 git@github.com`으로 **이미 성공**한 상태다. **키를 새로 생성할 필요 없다.**

이 프로젝트는 Linux VM이 Garmin Connect에서 신규 액티비티를 원본 ZIP으로 다운로드해 FIT를 추출하고, 날짜별 폴더에 보관하고, GitHub에 자동 Push하도록 구현한다. **GPT 분석 기능은 별도 단계**이다. Garmin과의 연동에는 비공식 [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) 라이브러리를 사용하므로 서버/계정에서 실제 다운로드 성공 여부를 검증해야 한다.

## 0. 아키텍처 / 파일 규칙

```text
Garmin Connect (HTTPS: 활동 목록, 원본 ZIP)
  -> Rocky Linux 9 VM [User: garmin]
     ~/.garminconnect/garmin_tokens.json   # 인증 토큰: GitHub 업로드 금지
     /garmin/garmin-fit-pipeline/
       .venv/                              # Python 3.12 전용
       scripts/auth.py                     # 최초 로그인
       scripts/sync_fit.py                 # 최근 기간 조회 + FIT 다운로드
       scripts/run_sync.sh                 # 중복실행 잠금, git pull/commit/push
       systemd/garmin-fit-sync.{service,timer}
       activities/
         2026/10/19/24753988019.fit
         2026/10/19/24754001001.fit
         2026/10/20/24755003003.fit
  -> git@github.com:suh1027/garmin-fit-repository.git (Private)
  -> GPT 분석(별도)
```

- **다운로드일이 아니라 Garmin `startTimeLocal` 기준**으로 `YYYY/MM/DD`에 저장한다. `startTimeLocal` 누락 시 `startTimeGMT`를 Asia/Seoul로 변환한다.
- 하루에 여러 건이면 각각의 Garmin Activity ID를 파일명으로 한다.
- 정상적인 기존 FIT 파일은 재다운로드하지 않는다. 기존 월별 폴더 `activities/YYYY/MM/{activityId}.fit`에 파일이 있다면 **API 조회 기간에 해당하는 건에 한해** 자동으로 일별 폴더로 이전한다.
- 실행 중 새 파일을 추가해도, `git push`가 실패하면 로컬 커밋을 보관하고 다음 배치에서 Push를 다시 시도한다.
- 원본 ZIP을 그대로 저장하려면 `--format zip` 사용 가능. **운영 포맷은 FIT로 고정 권장**. 두 포맷 혼용 시 각 포맷별 별도 파일이 만들어진다.
- 기본 조회: `--days 30`; 매일 전체 백필하지 않는다. 초기 과거 데이터는 `--since YYYY-MM-DD --until YYYY-MM-DD` 사용.

## 1. 현재까지 완료된 것

- [x] GitHub 저장소 이름: `suh1027/garmin-fit-repository`
- [x] `garmin` 사용자로 SSH Deploy Key 생성
- [x] `ssh -T -i ~/.ssh/garmin_archive_ed25519 git@github.com` 인증 성공
- [x] `/garmin/garmin-fit-pipeline` 디렉터리 생성 (`garmin:garmin`, mode `0750`)

**다음 절부터 남은 설치를 수행한다.** 이미 디렉터리가 있는 만큼 `mkdir`를 반복하거나 `/opt` 경로에 새 복사본을 만들지 않는다. `git clone`을 기존의 **빈 디렉터리**에 실행할 수 있다.

## 2. 관리자 계정: Rocky Linux 9 패키지·권한 검증

```bash
cat /etc/rocky-release
id garmin
sudo dnf makecache
sudo dnf install -y git openssh-clients unzip util-linux tzdata python3.12 python3.12-pip
python3.12 --version
git --version
sudo ls -ld /garmin /garmin/garmin-fit-pipeline
namei -l /garmin/garmin-fit-pipeline
```

`python3.12`는 Rocky 9의 AppStream 기반 버전(RHEL 9.4 이후 계열)에 제공된다. 시스템 기본 Python을 변경하지 않는다. 만약 설치 실패하면 `sudo dnf repolist`, `dnf list python3.12`를 확인하라. `/garmin` 상위 디렉터리에 garmin 사용자의 **x(통과) 권한**이 있어야 하며, 프로젝트 디렉터리는 이미 0750이다. 다른 사용자가 디렉터리에 접근하도록 넓은 0777 권한을 주지 않는다.

```bash
# 필요시에만 실행, 프로젝트 디렉터리는 기존 상태 유지
sudo chown garmin:garmin /garmin/garmin-fit-pipeline
sudo chmod 0750 /garmin/garmin-fit-pipeline
```

방화벽: VM에서 Garmin 로그인/데이터 서비스로 **아웃바운드 TCP 443**, GitHub로 **아웃바운드 TCP 22**가 필요. 인바운드 포트는 새로 열 필요가 없다.

## 3. garmin 계정: SSH 키를 Git 기본 연결에도 적용

사용자가 `ssh -T -i ...`에 성공했다고 해도, 일반 `git clone`은 `-i` 옵션이 없기 때문에 다른 SSH 키를 선택할 수 있다. 아래 `~/.ssh/config`를 설정한다.

```bash
sudo -iu garmin
whoami
mkdir -p ~/.ssh ~/.garminconnect
chmod 700 ~/.ssh ~/.garminconnect
chmod 600 ~/.ssh/garmin_archive_ed25519
cat > ~/.ssh/config <<'SSHEOF'
Host github.com
    HostName github.com
    User git
    IdentityFile /home/garmin/.ssh/garmin_archive_ed25519
    IdentitiesOnly yes
    StrictHostKeyChecking yes
SSHEOF
chmod 600 ~/.ssh/config
ssh -T git@github.com
```

기대 메시지: `Hi suh1027/garmin-fit-repository! You've successfully authenticated, but GitHub does not provide shell access.` (정상 인증에도 SSH 프로세스의 종료 코드가 1일 수 있음). 이번 계정은 이미 동일 호스트에 SSH 접속에 성공했으므로 `known_hosts`가 정상적으로 존재하는지 확인한다. SSH 호스트 키 오류 발생 시 `ssh-keygen -F github.com`, `ssh-keygen -lf ~/.ssh/known_hosts -E sha256`를 확인하고 GitHub 공식 지문과 비교한다. **`StrictHostKeyChecking=no`로 우회하지 않는다.**

추가로 GitHub 저장소 **Settings → Deploy keys**에 현재 공개키가 등록돼 있고 **Allow write access**가 체크되어 있는지 확인한다. `ssh -T`는 인증 성공만 의미하며 **Push 권한까지 증명하지는 않는다**.

## 4. ZIP을 VM으로 전송 (로컬 PC / 관리자 / garmin 구분)

1. 이 프로젝트 파일 `garmin-fit-pipeline-rocky9-v3.zip`을 로컬 PC로 다운로드한다.
2. 아래는 **로컬 PC PowerShell 또는 터미널**에서 실행한다.

```bash
scp garmin-fit-pipeline-rocky9-v3.zip ADMIN_USER@VM_IP:/tmp/
```

3. 아래는 **Rocky VM 관리자 셸**에서 실행한다.

```bash
sudo cp /tmp/garmin-fit-pipeline-rocky9-v3.zip /home/garmin/
sudo chown garmin:garmin /home/garmin/garmin-fit-pipeline-rocky9-v3.zip
sudo chmod 600 /home/garmin/garmin-fit-pipeline-rocky9-v3.zip
```

`ADMIN_USER`와 `VM_IP`만 실제 관리 계정과 주소로 바꾼다. 개인 SSH 키는 전송하지 않는다.

## 5. GitHub Repository를 기존 프로젝트 디렉터리에 Clone

**`garmin` 셸**에서 실행한다 (`sudo -iu garmin`). 먼저 빈 디렉터리인지 확인한다.

```bash
cd /garmin/garmin-fit-pipeline
pwd
ls -la
```

### 5-A. 빈 디렉터리이고 아직 `.git`이 없는 경우 (현재 초기 설치 예상)

```bash
cd /garmin/garmin-fit-pipeline
git clone git@github.com:suh1027/garmin-fit-repository.git .
git remote -v
git branch -a
```

`git clone ... .` 구문은 이미 만들어 둔 빈 설치 폴더 **그 자체**에 저장소를 Clone한다. GitHub 저장소가 완전히 비어 있으면 `You appear to have cloned an empty repository`는 오류가 아니다. 만약 GitHub에서 README를 먼저 생성했다면 파일들이 Clone된다.

### 5-B. `.git`이 이미 존재한다면

```bash
cd /garmin/garmin-fit-pipeline
git remote -v
git status -sb
```

정상 Git 저장소라면 **다시 Clone하지 않는다.** 원격 주소가 다르면 우선 다음과 같이 수정한다.

```bash
git remote set-url origin git@github.com:suh1027/garmin-fit-repository.git
```

**주의:** 설치 폴더에 `.git` 없이 기존 데이터나 파일이 이미 있다면 곧바로 Clone하지 말고 먼저 백업/파일 구조를 확인한다. 사용자의 기존 데이터를 덮어쓰지 않는다.

## 6. 파이프라인 소스 적용과 초기 Git Push

`garmin` 셸에서 ZIP을 임시 위치에 압축 해제하고, 프로젝트의 코드만 기존 Git working tree에 복사한다. `activities` 안에 기존 파일이 존재하면 이 단계에서 삭제하거나 덮어쓰지 않는다.

```bash
mkdir -p /home/garmin/garmin-v3-extract
unzip -o -q /home/garmin/garmin-fit-pipeline-rocky9-v3.zip -d /home/garmin/garmin-v3-extract
cd /garmin/garmin-fit-pipeline
cp -a /home/garmin/garmin-v3-extract/garmin-fit-pipeline/scripts .
cp -a /home/garmin/garmin-v3-extract/garmin-fit-pipeline/systemd .
cp /home/garmin/garmin-v3-extract/garmin-fit-pipeline/requirements.txt .
cp /home/garmin/garmin-v3-extract/garmin-fit-pipeline/.gitignore .
cp /home/garmin/garmin-v3-extract/garmin-fit-pipeline/README.md .
cp -a /home/garmin/garmin-v3-extract/garmin-fit-pipeline/tests .
mkdir -p activities
# 기존에 이 경로에 .gitkeep이 없을 때만 추가
touch activities/.gitkeep
chmod +x scripts/run_sync.sh
```

GitHub 저장소에 이미 작업물이 있다면 변경 내용을 확인한다. 자동 수집기는 `main` 브랜치 사용을 가정한다.

```bash
git config user.name 'Garmin FIT Collector'
git config user.email 'garmin-fit-collector@localhost'
git status --short
git diff --stat
git add .gitignore README.md requirements.txt scripts systemd tests activities/.gitkeep
git commit -m 'Configure Rocky 9 Garmin FIT pipeline with daily folders'
git branch -M main
git push -u origin main
git remote -v
```

`nothing to commit, working tree clean`은 변경분이 없을 때 정상적이다. **이미 커밋이 있다면** 불필요한 `git branch -M` 재실행은 피하고 현재 브랜치를 확인한다. 타인이 작성한 원격 커밋을 덮어쓰려는 `--force` Push를 하지 않는다.

초기 Push가 성공해야 Deploy Key 쓰기 권한이 검증된다.

## 7. Python 가상환경 설치 및 의존성 확인

```bash
cd /garmin/garmin-fit-pipeline
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -c 'from garminconnect import Garmin; print("Garmin library import: OK")'
```

GitHub 저장소에 `.venv/`가 올라가지 않았는지 `git status --short`로 확인한다. 프로젝트는 0.3 계열의 `garminconnect`와 `curl_cffi`를 설치한다. 실제 운영에 성공한 뒤에는 `pip freeze`로 검증된 버전을 별도 기록하고 패키지 업데이트를 통제한다.

## 8. Garmin Connect 최초 인증

**`garmin` 셸**에서 대화형으로 로그인한다.

```bash
cd /garmin/garmin-fit-pipeline
.venv/bin/python scripts/auth.py
```

Garmin 이메일과 암호를 입력한다. MFA가 활성화되어 있으면 코드를 입력한다. `scripts/auth.py`는 `~/.garminconnect` 경로에 저장할 토큰을 사용하며 이 파일을 Git에 올리지 않는다.

```bash
ls -ld /home/garmin/.garminconnect
ls -l /home/garmin/.garminconnect/garmin_tokens.json
```

기대 권한: 토큰 저장소 `0700`, 토큰 파일 `0600`. **`cat`으로 토큰 내용을 출력하거나 스크린샷 공유하지 않는다.** 토큰 만료 또는 폐기 후 재로그인이 필요하다면 `scripts/auth.py`를 다시 실행한다.

## 9. 소량 FIT 다운로드 및 일별 폴더 검증

```bash
cd /garmin/garmin-fit-pipeline
.venv/bin/python scripts/sync_fit.py --days 7 --max-downloads 3 --pause 3
find activities -type f -name '*.fit' | sort
```

예상 경로: `activities/2026/10/19/24753988019.fit`. 실제 Activity ID와 날짜는 계정에 따라 달라진다. 날짜별 파일이 여러 건인 경우 다음처럼 확인한다.

```bash
find activities/2026/10 -type f -name '*.fit' | sort
find activities -type f -name '*.fit' | wc -l
```

그다음 **Git Push까지 함께 실행**해 본다.

```bash
./scripts/run_sync.sh --days 7
git status -sb
git log -1 --oneline
git ls-files 'activities/*.fit' | tail -20
```

마지막 `git ls-files` 패턴은 하위 디렉터리에서도 Git pathspec과 매칭될 수 있으나, 더 확실하게 전체 확인하려면 `git ls-files activities | tail -20`을 쓴다.

**중요:** `run_sync.sh`는 `git pull --ff-only origin main`으로 시작하고, 조회/다운로드 후 `git add -A -- activities`, `git commit`, `git push origin main`을 수행한다. **GitHub에서 같은 브랜치를 동시에 편집하지 않는 단일 작성자 구조**를 권장한다. 수집 오류가 일부 발생하더라도 다운로드에 성공한 파일은 가능한 범위 내에서 Commit/Push한다.

## 10. systemd Timer로 자동 실행 (관리자 셸)

현재 `garmin` 셸이면 `exit`로 관리자 셸에 돌아간다.

```bash
sudo cp /garmin/garmin-fit-pipeline/systemd/garmin-fit-sync.service /etc/systemd/system/
sudo cp /garmin/garmin-fit-pipeline/systemd/garmin-fit-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now garmin-fit-sync.timer
sudo systemctl cat garmin-fit-sync.service
sudo systemctl list-timers --all garmin-fit-sync.timer
```

서비스 파일에 다음 값이 적용돼야 한다.

```ini
[Service]
Type=oneshot
User=garmin
WorkingDirectory=/garmin/garmin-fit-pipeline
Environment=HOME=/home/garmin
ExecStart=/garmin/garmin-fit-pipeline/scripts/run_sync.sh --days 30
```

타이머는 **매일 Asia/Seoul 02:00경(최대 10분 랜덤 지연)**에 실행된다. `Persistent=true`이므로 서버가 정지되어 일정이 누락된 경우 타이머 재활성화 때 보충 실행된다. 시간대 확인은 `systemctl cat garmin-fit-sync.timer`로 한다.

```bash
sudo systemctl start garmin-fit-sync.service
sudo systemctl status garmin-fit-sync.service --no-pager
sudo journalctl -u garmin-fit-sync.service -n 100 --no-pager
```

`oneshot` 서비스는 정상 수행 후 `inactive (dead)`로 보일 수 있으므로 `Result: success` 및 로그에 실패가 없는지 확인한다.

## 11. 최초 전체 백필 / 중복 방지 / 기존 월별 파일 이전

과거 데이터를 다운로드할 때 일일 타이머와 충돌하지 않도록 관리자 셸에서 일단 타이머를 중지한다.

```bash
sudo systemctl stop garmin-fit-sync.timer
sudo -iu garmin
cd /garmin/garmin-fit-pipeline
./scripts/run_sync.sh --since 2025-01-01 --until 2025-12-31
./scripts/run_sync.sh --since 2026-01-01 --until 2026-10-19
```

**주의:** 과거 전체 FIT를 한 번에 수천 개 내려받으면 Garmin API 제한이 발생할 수 있으므로 사용량이 많다면 연도/분기로 나눠 실행하고 `--pause 3` 이상을 유지한다. Garmin 정책을 우회하기 위해 재시도를 과도하게 반복하지 않는다. 원본 FIT가 존재하지 않는 수동 액티비티는 다운로드 실패할 수 있다.

기존 월별 파일이 있을 경우 Activity ID와 활동 날짜가 조회되면 서버에서 파일 이동(재다운로드 없음)한다. 조회 범위 밖의 오래된 월별 파일은 남을 수 있으므로 필요하면 추가 백필 또는 별도 마이그레이션을 수행한다.

백필 후 `exit`로 관리자 셸로 돌아와 타이머를 다시 시작한다.

```bash
sudo systemctl start garmin-fit-sync.timer
```

## 12. 장애 대응

| 증상 | 점검 / 대응 |
|---|---|
| `Permission denied (publickey)` | `garmin` 사용자에서 `ssh -T git@github.com`, `~/.ssh/config` 및 개인키 권한 0600 확인. `/home/garmin/.ssh/known_hosts` 확인 |
| SSH 인증 성공, Push 실패 | GitHub `Settings → Deploy keys → Allow write access` 및 브랜치 보호 규칙 확인 |
| `fatal: destination path ... already exists` | 기존 프로젝트 디렉터리가 비어 있지 않음. 삭제하지 말고 `ls -la`와 `.git` 존재 여부 확인 |
| `/garmin` 접근 불가 | `namei -l /garmin/garmin-fit-pipeline`, 권한/소유자 확인. 필요 시 SELinux AVC 로그 조사 |
| `python3.12` 설치 실패 | `dnf repolist`, `dnf list python3.12`; AppStream 활성화 점검 |
| Garmin 토큰 없음/인증 오류 | `sudo -iu garmin`으로 `.venv/bin/python scripts/auth.py` 재실행. MFA 요구 시 대화형 로그인 |
| 일부 FIT 다운로드 실패 | `journalctl`에서 활동 ID와 오류 유형 확인, 추가 일수 재조회. 비공식 API 변경 가능성 검토 |
| 타이머 동작 안 함 | `systemctl list-timers --all`, `systemctl status garmin-fit-sync.timer` |
| `git pull --ff-only` 실패 | 단일 writer 정책 확인. Remote 이력과 local 미Push 커밋 분기 여부 확인, 강제 Push 금지 |
| 날짜가 하루 어긋남 | Garmin `startTimeLocal` 및 VM timezone 점검. GMT fallback은 서울시간으로 변환 |

SELinux가 활성화된 Rocky Linux 9의 `/garmin` 커스텀 경로에서 접근이 거부되면 `sudo ausearch -m AVC -ts recent`, `sudo journalctl -xe`로 원인을 확인한다. **원인 확인 없이 `setenforce 0`, `chmod -R 777`을 수행하지 않는다.**

## 13. 검증 체크리스트

- [ ] `/garmin/garmin-fit-pipeline` 소유자는 `garmin:garmin`
- [ ] `ssh -T git@github.com`에 명시적 `-i` 없어도 인증 성공
- [ ] Git 원격: `git@github.com:suh1027/garmin-fit-repository.git`
- [ ] `scripts`와 `systemd` 파일 내부에 `/opt` 경로가 남아 있지 않음
- [ ] `.venv/bin/python`으로 Garmin 라이브러리 import 성공
- [ ] Garmin 토큰은 `/home/garmin/.garminconnect`에 보관, `.gitignore`에 의해 무시됨
- [ ] `activities/YYYY/MM/DD/{activityId}.fit` 생성
- [ ] 한 날짜에 여러 FIT 파일 저장 및 재실행 중복 방지
- [ ] 원격 GitHub Private 저장소에 Push 성공
- [ ] systemd timer 활성화, 수동 service 정상 실행

## 14. 보안 / 데이터 접근

- FIT 파일에는 **GPS 위치와 생체정보**가 포함될 수 있다. 저장소 Private 상태, Deploy Key 쓰기 권한, GitHub 조직/협업자 접근 권한을 정기 점검한다.
- Git 히스토리에 포함된 FIT는 파일을 삭제해도 과거 커밋에 남는다. 특히 사용자명·암호·토큰·개인키를 절대 Commit하지 않는다.
- GitHub 일반 Git 파일의 최대 100 MiB 제한(50 MiB 초과 경고)이 있으며, 장기간 수집 시 저장소 크기를 추적한다. 대형 파일이 누적되면 Git LFS 또는 별도 객체 스토리지 도입을 검토한다.
- MCP는 이 수집 파이프라인에 필수가 아니다. GPT 분석 시에는 GitHub 파일 조회 → FIT 다운로드/파싱 → AI 분석을 별도 워크플로로 연결하면 된다.

참고: [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) · [GitHub Deploy Key](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys) · [RHEL 9 Python](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/epub/installing_and_using_dynamic_programming_languages/proc_using-python_assembly_installing-and-using-python) · [GitHub 파일 제한](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)
