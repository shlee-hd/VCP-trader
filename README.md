# VCP Trader 📈

마크 미너비니(Mark Minervini)의 VCP(Volatility Contraction Pattern) 전략을 기반으로 한 자동화 트레이딩 솔루션

## 🎯 핵심 기능

- **VCP 패턴 자동 탐지**: 변동성 수축 패턴을 실시간으로 감지
- **Trend Template 스크리너**: 미너비니의 8가지 기준으로 Stage 2 상승 추세 종목 필터링
- **자동 리스크 관리**: 다층 손절/트레일링 스탑 시스템
- **자동 매매**: 피벗 포인트 돌파 시 자동 진입, 조건 충족 시 자동 청산
- **실시간 알림**: Telegram을 통한 실시간 신호 알림

## 🏗️ 시스템 아키텍처

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Data Layer    │────▶│   Core Engine    │────▶│  Trading Layer  │
│  (Broker API)   │     │ (Pattern Detect) │     │ (Order Execute) │
└─────────────────┘     └──────────────────┘     └─────────────────┘
         │                       │                        │
         ▼                       ▼                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Monitoring & Alerts                         │
│              (Dashboard, Telegram, Trade Journal)                │
└─────────────────────────────────────────────────────────────────┘
```

## 📋 요구 사항

- Python 3.11+
- PostgreSQL 14+
- Redis 7+
- 한국투자증권 계좌 & KIS Developers API 키

## 🚀 시작하기

### 1. 저장소 클론 및 의존성 설치

```bash
cd VCP-trader
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e ".[dev]"
```

### 2. 환경 설정

```bash
cp .env.example .env
# .env 파일을 열어 API 키와 설정값 입력
```

### 3. 데이터베이스 설정

```bash
# PostgreSQL 데이터베이스 생성
createdb vcp_trader

# 마이그레이션 실행
python -m scripts.init_db
```

### 4. 실행

```bash
# VCP 패턴 스캐너 실행
python -m scripts.run_scanner

# 자동 트레이딩 봇 실행 (주의: 실제 거래 발생)
python -m scripts.run_trader
```

## 📊 미너비니 Trend Template (8가지 기준)

| # | 기준 | 설명 |
|---|------|------|
| 1 | 가격 > 150MA > 200MA | 장기 상승 추세 확인 |
| 2 | 가격 > 50MA | 중기 상승 추세 확인 |
| 3 | 50MA > 150MA > 200MA | 이동평균 정배열 |
| 4 | 200MA 상승 중 | 30일 전보다 높은 200MA |
| 5 | 52주 저점 대비 +30% | 강한 상승 모멘텀 |
| 6 | 52주 고점 대비 -25% 이내 | 고점 근접 |
| 7 | RS Rating > 70 | 시장 대비 강한 상대 강도 |
| 8 | 베이스 위에서 거래 | 지지 확인 |

## 🛡️ 리스크 관리

### 트레일링 스탑 시스템

```
진입 ─▶ 초기 손절(-7%) ─▶ 수익 5% ─▶ 트레일링 1(-5%)
                                    │
                               수익 10% ─▶ 트레일링 2(-8%)
                                    │
                               수익 20% ─▶ 트레일링 3(-10%)
                                    │
                               수익 50%+ ─▶ 트레일링 4(-15%)
```

## ⚠️ 주의사항

> **경고**: 이 소프트웨어는 실제 금융 거래를 수행합니다.
> - 반드시 모의투자로 충분히 테스트 후 사용하세요
> - 투자 손실에 대한 책임은 사용자에게 있습니다
> - 시스템 오류나 API 장애에 대비한 모니터링을 권장합니다

## 📁 프로젝트 구조

```
VCP-trader/
├── src/
│   ├── core/           # 핵심 설정 및 데이터베이스
│   ├── data/           # 데이터 수집 및 브로커 연동
│   ├── patterns/       # 패턴 탐지 엔진
│   ├── trading/        # 거래 실행 및 리스크 관리
│   ├── alerts/         # 알림 시스템
│   └── dashboard/      # 웹 대시보드
├── tests/              # 테스트 코드
├── scripts/            # 실행 스크립트
└── config/             # 설정 파일
```

## 📜 라이선스

MIT License
