---
title: 인원 디렉토리
emoji: 👥
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
---

# 인원 디렉토리

동문/멤버 디렉토리 웹앱입니다.

## 기능
- 이름/직종/학과/경력으로 검색 및 필터
- 현직자 배지 표시
- 회원 카드 상세 모달

## 로컬 실행

```bash
pip install flask playwright
playwright install chromium
python build_site_structured.py members_structured.csv
python server.py
```

접속: http://localhost:5000

> **참고**: LinkedIn 스크래핑 기능은 로컬 환경에서만 동작합니다.