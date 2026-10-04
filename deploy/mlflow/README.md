# EC2 MLflow Tracking Server

이 구성은 MLflow 메타데이터를 Compose의 PostgreSQL `mlflow` 데이터베이스에 저장하고,
모델·체크포인트·평가 결과 등의 아티팩트를 기존 S3 버킷의 전용 prefix에 저장합니다.
클라이언트는 MLflow 서버에만 연결하며 S3 업로드와 다운로드는 서버가 프록시합니다.

## 환경 변수

루트 `.env`에 다음 값을 설정합니다.

```dotenv
MLFLOW_ARTIFACT_PREFIX=dev/ec2/mlflow/
MLFLOW_ALLOWED_HOSTS=localhost:*,127.0.0.1:*,mlflow:5000
```

`MLFLOW_ARTIFACT_PREFIX`는 Terraform의 `mlflow_artifact_prefix`와 같아야 합니다.
EC2 인스턴스 역할을 사용할 때 AWS access key 환경 변수는 비워 둡니다.
MLflow 컨테이너에는 정적 AWS 키를 전달하지 않으며 EC2 instance profile만 사용합니다.

## 실행

```bash
docker compose --env-file .env -f deploy/compose/compose.yaml --profile mlflow up --build -d mlflow
docker compose --env-file .env -f deploy/compose/compose.yaml --profile mlflow ps
docker compose --env-file .env -f deploy/compose/compose.yaml --profile mlflow logs -f mlflow
```

`mlflow-db-init` 서비스가 기존 PostgreSQL 볼륨에서도 `mlflow` 데이터베이스를 멱등하게
생성합니다. MLflow 서버가 시작되면 필요한 MLflow 테이블은 자동으로 마이그레이션됩니다.

## EC2 접속

MLflow는 EC2의 loopback 포트에만 공개됩니다. 로컬 PC에서 Terraform 출력 명령을 실행합니다.

```bash
cd deploy/terraform/dev-ec2
$(terraform output -raw mlflow_port_forward_command)
```

Windows PowerShell에서는 다음 명령을 사용합니다.

```powershell
Set-Location deploy/terraform/dev-ec2
$instanceId = terraform output -raw instance_id
aws ssm start-session --region ap-northeast-2 --target $instanceId `
  --document-name AWS-StartPortForwardingSession `
  --parameters 'portNumber=5000,localPortNumber=5000'
```

포트 포워딩 세션이 열린 동안 브라우저에서 `http://127.0.0.1:5000`으로 접속합니다.
학습 코드에서는 다음처럼 설정합니다.

```python
import mlflow

mlflow.set_tracking_uri("http://127.0.0.1:5000")
mlflow.set_experiment("cctv-accident")
```

CLI 또는 원격 학습 머신도 동일한 tracking URI를 사용합니다. 포트를 인터넷에 직접 공개해야
한다면 먼저 HTTPS reverse proxy와 인증을 구성해야 합니다.

## 확인

```bash
curl --fail http://127.0.0.1:5000/health
curl --fail http://127.0.0.1:5000/api/2.0/mlflow/experiments/search \
  -H 'Content-Type: application/json' \
  -d '{"max_results":10}'
```
