# China Robotics/AI News Clipping (Max Coverage)

**목표:** 중국 내 공신력 있는 매체/플랫폼의 로보틱스·AI 뉴스를 **키워드 필터**로 자동 수집 → **정리된 HTML/JSON**을 **GitHub Pages**로 배포.

> 이 템플릿은 **저작권 문제가 없는 100% 자작 코드**이며 MIT License로 공개됩니다. 원문은 각 매체 링크로 연결만 하며, 본문 전문을 저장/재배포하지 않습니다(요약/발췌는 trafilatura가 추출한 텍스트 일부). 각 사이트의 이용약관·robots.txt를 준수하세요.

## 빠른 시작
1. 이 레포를 GitHub에 업로드합니다.
2. **Settings → Pages → Build and deployment = GitHub Actions**로 설정합니다.
3. `feeds.yml`(소스)과 `keywords.yml`(키워드)만 수정해도 동작합니다.
4. Actions 탭에서 **Run workflow**로 첫 실행 → Pages URL에서 결과 확인.

## 구성
- `feeds.yml` : 소스 목록. `type: rss` 우선, 없으면 `type: html` + `link_pattern`으로 보완
- `keywords.yml` : 포함/제외 정규식(대소문자 무시)
- `src/fetch.py` : 수집/필터/요약/HTML+JSON 생성 (RSS + HTML 동시 지원)
- `docs/` : GitHub Pages 산출물
- `.github/workflows/china-robotics-news.yml` : 4시간마다 자동 실행 + Pages 배포

## 운영 가이드
- **키워드 튜닝:** 사람형/双足/具身 + 기업명(중·영·약칭)을 넉넉히. 스팸(채용/광고)은 `exclude`에 추가.
- **소스 확장:** RSS가 있으면 `type: rss`. 없으면 `type: html`에 `link_pattern`을 가급적 구체적으로.
- **요약 추출:** 가능할 때만 일부 텍스트를 단순 요약으로 포함. 원문 열람을 기본 원칙으로 합니다.
- **스케줄:** 기본 4시간(UTC). 한국은 UTC+9입니다. 필요 시 cron만 수정.
- **법적 유의:** 본 템플릿은 **링크+짧은 요약**만 제공합니다. 각 출처의 저작권·약관·robots 규정을 준수하세요.

## 감사/출처 힌트
- RSSHub 라우트와 공식 RSS를 혼용하여 커버리지를 넓혔습니다.
- 일부 매체는 공식 RSS가 없어 HTML 링크를 키워드로 선별합니다.
