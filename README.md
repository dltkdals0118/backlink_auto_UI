# 백링크 침투기 v1

홈페이지 게시판 자동 등록 프로그램 (제작자_이상민)

홈페이지 글쓰기 링크를 입력하면 게시판 글쓰기 폼을 분석해 더미데이터를 채우고, OpenAI로 EEAT 구조의 본문을 작성한 뒤, 캡차를 AI 비전으로 풀어 문의글을 자동 등록합니다.

> 설계 상세는 [SPEC.md](SPEC.md) 참고.

## 지원 게시판 / 범용성

여러 게시판 시스템을 자동 지원합니다.

- **그누보드5(GNUBOARD5)**: `wr_name`, `wr_subject`, `wr_content` 등
- **구형 dae_board**: `b_name`, `b_pass`, `b_title`, `b_comment` 등
- 그 외 비슷한 구조의 게시판도 필드 키워드(이름/제목/내용/비밀번호 등) 휴리스틱으로 자동 탐지

**목록 페이지에서 시작해도 됩니다.** 글쓰기 폼이 바로 없으면 `글쓰기`/`쓰기` 버튼(링크·이미지 버튼 포함)을 자동으로 찾아 클릭한 뒤 폼을 분석합니다. 즉 `bbs.php?id=free`(목록) URL을 넣어도 동작합니다.

## 요구사항

- Python 3.12+
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) 설치 (캡차 인식용)
- OpenAI API 키

## 설치

```bash
pip install -r requirements.txt
playwright install chromium
```

Windows에서 `tesseract`가 PATH에 없다면 `.env`의 `TESSERACT_CMD`에 경로를 지정하세요.

## 설정

```bash
cp .env.example .env
```

`.env`에 `OPENAI_API_KEY`를 입력합니다.

## 실행 (웹 UI · 권장)

브라우저에서 폼 입력·실행·실시간 로그 확인이 가능합니다.

```bash
python web_app.py
```

실행 후 [http://127.0.0.1:8000](http://127.0.0.1:8000) 접속. URL/주제를 입력하고 옵션(브라우저 창 표시, Dry-run)을 선택한 뒤 "실행"을 누르면 진행 로그가 실시간으로 표시됩니다.

> `OPENAI_API_KEY`가 유효하지 않으면 상단에 경고가 뜨고 실행 버튼이 비활성화됩니다. 웹 UI에서는 캡차 수동 입력(`--manual`)은 지원하지 않고 OCR + 자동 재시도만 동작합니다.

## 실행 (CLI)

```bash
python main.py --url "http://seouljasu.com/bbs/write.php?bo_table=qa"
```

### 옵션

| 옵션 | 설명 |
| --- | --- |
| `--url` | 글쓰기 폼 URL (미지정 시 `.env`의 `TARGET_URL`) |
| `--topic` | AI 본문 주제 힌트 |
| `--backlink-url` | 본문에 삽입할 백링크 URL |
| `--backlink-text` | 백링크 앵커 텍스트 |
| `--repeat` | 반복 등록 횟수 |
| `--rotate-ip` | ADB로 유동 IP 변경 사용 |
| `--rotate-every` | 몇 글당 IP를 변경할지 |
| `--manual` | 캡차 OCR 실패 시 수동 입력 폴백 |
| `--no-headless` | 브라우저 창 표시(디버깅) |
| `--dry-run` | 폼 작성까지만 하고 최종 제출은 생략 |

## 사람처럼 행동 (안티봇 풋프린트)

실제 사람의 접속처럼 보이도록 다음을 랜덤화합니다.

- **User-Agent / Accept-Language / 뷰포트 / 타임존**: 데스크톱·모바일 UA 풀에서 랜덤 선택
- **Referer(유입경로)**: 검색 유입(네이버/구글/빙/다음) · 사이트 직접 · 없음 · 랜덤. `AI 검색어 생성`을 켜면 글 주제에 맞는 자연스러운 한국어 검색어를 만들어 검색 유입처럼 보이게 합니다.
- **휴먼 행동**: 마우스 이동, 스크롤, 머무름(지연)을 설정 범위 내에서 랜덤 수행
- **타이핑**: 폼 입력을 글자 단위로 입력

웹 UI의 `사람처럼 행동 (안티봇 풋프린트)` 섹션에서 디바이스/Referer/지연(ms)/스크롤·마우스 횟수 범위를 조절합니다. CLI는 `--human`으로 기본값 활성화합니다.

```bash
python main.py --human --topic "캠핑 장비 추천"
```

> 휴먼라이크를 켜면 지연 때문에 1건당 수십 초가 걸릴 수 있습니다. 모바일 디바이스는 사이트가 모바일 스킨으로 렌더링되어 폼 구조가 달라질 수 있으니, 문제가 있으면 데스크톱으로 사용하세요.

## 유동 IP 변경 (안드로이드 ADB 테더링)

여러 글을 등록할 때 IP 차단을 피하기 위해, 안드로이드 폰의 모바일 데이터를 껐다 켜서 유동 IP를 바꾸는 기능입니다.

**전제 조건**
1. PC가 해당 안드로이드 폰의 **테더링(USB 권장)** 으로 인터넷을 사용해야 합니다. (PC 트래픽이 폰을 경유해야 IP 변경이 PC 공인 IP에 반영됨)
2. [Android Platform Tools(ADB)](https://developer.android.com/tools/releases/platform-tools) 설치 + 폰에서 **USB 디버깅** 활성화.
3. `adb`가 PATH에 없으면 `.env`의 `ADB_CMD`에 `adb.exe` 경로 지정.

**동작**: `adb shell svc data disable` → 대기 → `adb shell svc data enable` → 재연결 후 공인 IP가 바뀔 때까지 확인.

웹 UI에서는 `IP 변경 사용` 체크, `반복 등록 횟수`, `IP 변경 주기(몇 글당)`를 설정합니다. `ADB 연결됨` 배지와 `현재 IP 확인` 버튼으로 상태를 점검할 수 있습니다.

```bash
# CLI: 5개 글을 2개마다 IP 바꿔가며 등록
python main.py --repeat 5 --rotate-ip --rotate-every 2
```

> 통신사 CGNAT 환경에서는 데이터를 토글해도 공인 IP가 안 바뀔 수 있습니다. 이때는 비행기모드 토글이나 다른 회선을 고려하세요. IP 변경에 실패해도 프로그램은 같은 IP로 계속 진행합니다.

### .env 추가 항목

| 키 | 설명 | 기본값 |
| --- | --- | --- |
| `ADB_CMD` | adb 실행 경로 | PATH의 `adb` |
| `IP_OFF_WAIT` | 데이터 끈 뒤 대기(초) | `4` |
| `IP_ON_WAIT` | 데이터 켠 뒤 대기(초) | `5` |
| `IP_VERIFY_TIMEOUT` | IP 변경 확인 최대 대기(초) | `40` |

### 예시

```bash
# 디버깅: 브라우저 띄우고 제출은 생략
python main.py --no-headless --dry-run

# 주제 지정 + 캡차 수동 폴백
python main.py --topic "단체 유니폼 자수 문의" --manual
```

## 구조

```
.
├── main.py                # CLI 진입점
├── web_app.py             # 웹 UI 서버(FastAPI)
├── config.py              # 설정 로딩(.env)
├── SPEC.md                # 설계 명세
├── requirements.txt
├── .env.example
├── web/
│   └── index.html         # 웹 UI 프론트엔드
└── src/
    ├── runner.py          # 공용 파이프라인(CLI/웹 공유)
    ├── form_analyzer.py   # 폼 필드 탐지
    ├── dummy_data.py      # Faker 더미데이터
    ├── scraper.py         # 사이트 스크래핑(EEAT 컨텍스트)
    ├── content_writer.py  # OpenAI EEAT 본문 생성
    ├── captcha_solver.py  # 캡차 OCR
    └── submitter.py       # Playwright 폼 작성/제출
```

## GitHub 연동

```bash
cd mecro
git init
git add .
git commit -m "Initial commit: 백링크 침투기 v1"

# GitHub에서 빈 저장소 생성 후 (예: backlink-penetrator)
git remote add origin https://github.com/<사용자명>/<저장소명>.git
git branch -M main
git push -u origin main
```

> `.env`는 `.gitignore`에 포함되어 **GitHub에 올라가지 않습니다.** 클라우드 서버에서는 환경변수로 `OPENAI_API_KEY` 등을 직접 설정하세요.

## 클라우드 서버 배포 (Docker)

Playwright(Chromium)가 필요하므로 **Docker 배포**를 권장합니다.

### 1) VPS(우분투 등)에서 Docker Compose

```bash
git clone https://github.com/<사용자명>/<저장소명>.git
cd <저장소명>
cp .env.example .env
# .env 편집: OPENAI_API_KEY, TARGET_URL 등

docker compose up -d --build
```

브라우저에서 `http://<서버IP>:8000` 접속.

### 2) 환경변수 (클라우드)

| 변수 | 설명 |
|------|------|
| `HOST` | `0.0.0.0` (외부 접속, Docker 기본값) |
| `PORT` | `8000` |
| `OPENAI_API_KEY` | OpenAI API 키 |
| `HEADLESS` | `true` (서버에서는 브라우저 숨김) |

### 3) Render / Railway 등 PaaS

- **Runtime**: Docker
- **Dockerfile** 사용 (저장소 루트)
- 환경변수 탭에서 `OPENAI_API_KEY`, `HEADLESS=true` 설정
- Playwright 이미지 용량이 커서 **Starter 이상 플랜**이 필요할 수 있습니다.

방화벽에서 **8000 포트**를 열어 두세요.

## 주의

자동 게시는 사이트 운영 정책·약관 및 관련 법규를 따릅니다. 본인 소유 홈페이지에서만 사용하세요. 과도한 반복 등록은 차단·스팸 처리 위험이 있습니다.
