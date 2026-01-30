# VCP Trader 개발자 안내

## 프로젝트 구조 파악

```
VCP-trader/
├── pyproject.toml          # 프로젝트 메타데이터
├── requirements.txt        # 의존성 목록
├── .env.example           # 환경 변수 템플릿
├── README.md              # 프로젝트 소개
│
├── src/                   # 소스 코드
│   ├── core/              # 핵심 설정 및 DB
│   │   ├── config.py      # Pydantic Settings 기반 설정
│   │   └── database.py    # SQLAlchemy 모델
│   │
│   ├── data/              # 데이터 수집
│   │   ├── broker_client.py   # 한국투자증권 API
│   │   └── data_fetcher.py    # 데이터 수집기
│   │
│   ├── patterns/          # 패턴 탐지
│   │   ├── trend_template.py  # 8점 Trend Template
│   │   ├── vcp_detector.py    # VCP 패턴 탐지
│   │   └── rs_calculator.py   # RS Rating 계산
│   │
│   ├── trading/           # 거래 로직
│   │   ├── stop_loss.py       # 트레일링 스탑
│   │   ├── risk_manager.py    # 포지션 사이징
│   │   └── order_executor.py  # 주문 실행
│   │
│   ├── alerts/            # 알림
│   │   └── notifier.py        # Telegram/Console 알림
│   │
│   └── dashboard/         # 웹 대시보드
│       └── app.py             # FastAPI 앱
│
├── scripts/              # 실행 스크립트
│   ├── run_scanner.py    # VCP 스캐너
│   └── run_trader.py     # 자동 트레이더
│
└── tests/                # 테스트
    └── test_patterns.py
```

## 개발 환경 설정

```bash
# 1. 가상 환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # Windows: venv\\Scripts\\activate

# 2. 의존성 설치
pip install -e ".[dev]"

# 3. 환경 변수 설정
cp .env.example .env
# .env 파일 편집하여 API 키 입력

# 4. 데이터베이스 초기화 (PostgreSQL 필요)
# createdb vcp_trader
# python -c "from src.core.database import init_db; import asyncio; asyncio.run(init_db())"
```

## 실행 방법

```bash
# VCP 스캐너 (1회)
python -m scripts.run_scanner --once

# VCP 스캐너 (스케줄러)
python -m scripts.run_scanner

# 자동 트레이더 (dry-run)
python -m scripts.run_trader --dry-run

# 대시보드
uvicorn src.dashboard.app:app --reload
```

## 테스트

```bash
# 전체 테스트
pytest tests/ -v

# 커버리지
pytest tests/ -v --cov=src --cov-report=html
```

## 주요 설정 파라미터

| 파라미터 | 기본값 | 설명 |
|---------|--------|------|
| `MAX_RISK_PER_TRADE` | 2% | 거래당 최대 리스크 |
| `MAX_POSITIONS` | 8 | 최대 동시 보유 포지션 |
| `INITIAL_STOP_LOSS` | 7% | 초기 손절 비율 |
| `MIN_RS_RATING` | 70 | 최소 RS Rating |
| `MIN_VCP_SCORE` | 70 | 최소 VCP 점수 |

## 트레일링 스탑 레벨

| 레벨 | 수익률 조건 | 손절 기준 |
|------|------------|-----------|
| 0 | - | 진입가 -7% |
| 1 | 5%+ | 고점 -5% |
| 2 | 10%+ | 고점 -8% |
| 3 | 20%+ | 고점 -10% |
| 4 | 50%+ | 고점 -15% |

## 향후 개발 계획

1. **US 시장 확장**: 미국 증권사 API 연동 (Alpaca, IBKR)
2. **암호화폐 시장**: 바이낸스/업비트 API 연동
3. **백테스팅 엔진**: 전략 검증 시스템
4. **ML 기반 패턴 인식**: 더 정교한 VCP 탐지
