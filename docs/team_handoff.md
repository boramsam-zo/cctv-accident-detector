# 팀 개발 시작 안내 — 서비스 PRD v0.2

**현재 설계: Streamlit + FastAPI + S3 + Modal GPU 함수 + YOLO11s/X3D-S + Gemini VLM + 후속 RAG/보고 + 사람 검토.** GPU 함수와 백엔드 코드는 작성됐으며 실제 GPU·S3·Gemini E2E 검증은 아직 전이다.

## 새로 시작하는 팀원이 읽을 순서

1. [전체 PRD](../PROJECT_BRIEF.md): 무엇을 만들고 어디까지 포함하는지.
2. [공통 API·데이터 계약](contracts/service_contract.md)과 [Modal 연결 계약](contracts/modal-inference-v1.md): 팀 간 연결 규칙.
3. [역할별 안내](roles/README.md): FE·BE·모델·VLM/RAG·인프라·QA의 담당 문서.
4. [요구사항](requirements.md), [가상 응답](contracts/demo-analysis-cases-v0.2.json), [통합 확인](roles/validation.md).

## 팀에 그대로 보낼 소개문

> CCTV 사고 의심 분석 서비스의 PRD를 v0.2로 정리했습니다. 먼저 전체 PRD와 공통 API/데이터 계약을 읽고, 맡은 영역의 문서를 보시면 됩니다. 각 문서에는 입력·산출물·첫 작업·완료 기준을 적었습니다. API 필드나 작업 상태가 바뀌면 공통 계약부터 수정하고 연결 영역에 알려 주세요. 현재는 설계 문서이며 실제 모델 연결·클라우드 배포·품질 검증은 앞으로 확인할 작업입니다. Dynamic 클래스의 라벨 정의와 배포 설정 등 미확인 항목은 문서에 표시했습니다.

이 문구는 공유용 초안이다. 이 작업에서 팀 메시지 발송·외부 업로드는 하지 않았다.

## 나눠서 개발해도 연결되게 하는 기준

- 같은 `job_id/run_id/event_id`로 가상 응답부터 맞춘다.
- FE는 화면과 API 사용, BE는 상태·영구 저장·작업 회수, 모델은 영상 입력/결과 manifest를 준비한다.
- VLM/RAG는 후보·실제 장면·검증된 문서를 받고 출처 있는 결과를 반환한다.
- 인프라는 서비스 위치·권한·비용·로그를, QA는 중복/부분/실패/복구 인수를 맡는다.
- 개인 이름별 업무 배정은 없다. 역할 문서에 진행 기록을 중복 작성하지 않고 중앙 현황·계획·진행 기록을 갱신한다.

## 이전 그림에서 달라진 점

BE 작업 프로세스가 Modal 함수를 `spawn()`으로 제출하고 `modal_call_id`를 저장한다. 함수는 업로드 MP4를 오프라인으로 분석해 X3D-S 후보와 해당 장면의 YOLO 객체 정보를 만들고 clip·frame·manifest를 S3에 저장한다. BE가 완료 후 S3 결과를 검증해 event를 등록하고 Gemini에 전달한다. RAG/보고는 후속 연결 범위다. 사람 검토는 UI→API→DB로 저장한다. GPU 로그와 AWS 로그는 job/run/event/call ID로 대조한다.

## 전달 모델 확인

지정된 deployment_handoff의 11개 파일이 동봉 manifest의 크기·SHA256과 일치한다. YOLO는 0 Pedestrian, 1 Car, 2 Truck, 3 Bus, 4 Motorcycle, 5 Bicycle, 6 Dynamic의 **7개 클래스**다. 기존 그림의 6개 표기를 수정했다. Dynamic의 의미·성능·실시간 지연은 미확인이다.

받은 코드도 X3D 후보→후보 시각 한 프레임의 YOLO 순서다. 현재 Modal 함수에 근거 클립 추출과 S3 저장 코드를 연결했으며 실제 GPU·S3 통합 검증은 남아 있다. [모델 접수 근거](contracts/received-model-metadata-v0.2.json)는 모델 실행 없는 정적 확인 결과다.

## GitHub에서 공유·수정하기

이 저장소의 main에 병합된 문서가 팀의 최신 기준이다. 전체 PRD→공통 계약→담당 역할 문서 순서로 읽는다. ZIP은 시점별 전달본으로만 사용한다.

각자 작업 브랜치를 만들어 담당 문서를 수정하고 PR에서 변경 이유·연결 영역·실제 확인 결과를 설명한다. 공통 API·상태를 바꾸면 계약과 가상 응답을 같은 PR에서 수정하고 사용하는 영역의 검토를 받는다. 한 역할이 다른 역할의 계약을 모르게 변경하지 않는다.

기존 모델·학습 폴더 책임은 [프로젝트 폴더 구조](PROJECT_FOLDER_STRUCTURE.md)를 따른다. 실제 모델·영상·비밀 값은 이번 문서 변경에 포함하지 않는다.
