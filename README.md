# Gigapixel Heritage Viewer (MVP)

PRD 기반 기능(업로드, 자동 스티칭, DZI 생성, 웹 뷰어, 주석, 공유 URL)을 로컬에서 실행 가능한 형태로 구현한 프로젝트입니다.

## 구현 기능
- 다중 이미지 업로드
- OpenCV 기반 자동 스티칭
- DeepZoom(DZI) 타일 생성 (`pyvips` 우선, Pillow 폴백)
- OpenSeadragon 기반 확대/축소 뷰어
- Annotation 생성/조회/삭제
- 세션 공유 URL (`/viewer/{session_id}`)
- 최종 결과물 ZIP 다운로드 (`/api/sessions/{session_id}/download`)
- 연속 작업을 위한 다음 세션 빠른 시작 버튼

## 실행 방법
1. 의존성 설치
```bash
pip install -r requirements.txt
```

2. 서버 실행
```bash
uvicorn app.main:app --reload
```

근데 잘 안되면 아래 명령어 써보셈 (컴마다 다른듯)
py -3 -m pip install -r requirements.txt
py -3 -m uvicorn app.main:app --reload

3. 접속
- 메인: http://127.0.0.1:8000/
- 세션 뷰어: http://127.0.0.1:8000/viewer/{session_id}

## 주의 사항
- OpenCV 스티칭 품질은 입력 이미지의 중첩 영역에 크게 의존합니다.
- 대형 입력(수백~수천장, 수십 GB 이상)은 별도 워커(Celery/Redis) 분리와 스토리지 튜닝이 필요합니다.
- 현재 MVP는 단일 프로세스 백그라운드 작업으로 동작합니다.
- 기본 최대 입력 픽셀 제한은 `10,000,000,000`이며, 환경 변수 `MAX_SOURCE_PIXELS`로 조정할 수 있습니다.

## 디렉터리 구조
```text
gigapixel-heritage-viewer/
  app/
    main.py
    models.py
    schemas.py
    services/
  data/                    # 런타임 데이터 (업로드/결과/DB)
  requirements.txt
```
