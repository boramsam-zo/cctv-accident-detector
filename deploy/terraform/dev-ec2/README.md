# 개발용 EC2 Terraform

기존 AWS VPC의 **퍼블릭 서브넷**에 Amazon Linux 2023 EC2 한 대를 준비합니다. Docker·Compose 플러그인·Git을 설치하고, SSM Session Manager로 접속하며, 인스턴스 역할에 영상 S3 버킷의 지정한 개발 prefix만 읽고 쓸 권한을 부여합니다. 모델 가중치 버킷은 Modal의 별도 Secret/권한으로 접근하므로 이 EC2 역할에는 포함하지 않습니다.

FastAPI·worker·Streamlit·PostgreSQL의 개발용 Compose는 [deploy/compose/README.md](../../compose/README.md)에 있습니다. 이 Terraform은 호스트 준비까지 담당하며, 앱 컨테이너는 EC2 접속 후 별도 명령으로 빌드·기동합니다. PostgreSQL 데이터 백업, HTTPS/도메인, 자동 배포는 별도 작업입니다.

## 준비할 값

| 입력 | 의미 |
| --- | --- |
| `subnet_id` | 기존 VPC의 퍼블릭 서브넷. 인터넷 게이트웨이 경로가 있어야 SSM/패키지 설치/외부 API에 접근할 수 있습니다. |
| `video_bucket_name` | 원본 영상과 Modal 추론 근거를 저장하는 기존 버킷 이름 (`s3://` 제외). |
| `video_key_prefix` | 이 개발 환경의 S3 경로. 앱 `.env`의 `S3_KEY_PREFIX`와 같게 설정합니다. 기본 `dev/ec2/`. |
| `aws_region` | 서브넷과 영상 버킷의 AWS 리전. 기본 `ap-northeast-2`. |
| `instance_type` | 기본 `t3.medium` (x86_64, 4 GiB). 작게 바꾸면 컨테이너와 PostgreSQL 메모리가 부족할 수 있습니다. |
| `streamlit_cidrs` | 직접 8501 포트를 열어야 할 때만 승인된 IP CIDR을 넣습니다. 기본값 `[]`이면 인바운드가 전혀 없습니다. |

AWS CLI와 Terraform을 설치하고, 실행할 AWS 프로필에 EC2/IAM/VPC 조회/SSM AMI 조회 권한을 설정합니다. 프로필이나 SSO로 인증하고 액세스 키를 tfvars에 넣지 않습니다. 서브넷, 영상 버킷, Modal의 모델 버킷 및 GPU 앱은 이 모듈이 만들지 않습니다.

## 계획 확인과 생성

저장소 루트에서 아래 명령을 실행합니다. `terraform.tfvars`는 Git에서 제외됩니다.

```bash
cd deploy/terraform/dev-ec2
cp terraform.tfvars.example terraform.tfvars
# terraform.tfvars의 subnet_id와 video_bucket_name을 실제 값으로 변경
terraform init
terraform fmt -check
terraform validate
terraform plan -out=dev.tfplan
terraform apply dev.tfplan
terraform output
```

기본 Terraform 상태 파일은 이 디렉터리에 로컬로 생성되고 Git에서 제외됩니다. 팀 공용으로 운영하기 전에는 **기존 인프라 저장소의 원격 state 정책**(예: S3 backend와 잠금)을 정해 이전하세요. state 파일을 분실하면 리소스 변경/삭제를 추적하기 어렵습니다. 저장한 plan 파일에도 값이 담길 수 있으므로 공유하지 마세요.

## 접속과 화면 확인

SSM Agent가 온라인이 될 때까지 기다립니다. 인스턴스에는 SSH 키와 22번 포트를 설정하지 않습니다. SSM에 접속하는 **사람의 IAM 권한**은 인스턴스의 SSM 역할과 별도로 필요합니다.

```bash
aws ssm start-session --region ap-northeast-2 --target "$(terraform output -raw instance_id)"
```

앱 컨테이너가 EC2 호스트의 `127.0.0.1:8501`에 Streamlit을 바인딩한 뒤, 로컬 PC에서 다음 포트 포워딩을 실행하면 `http://127.0.0.1:8501`로 볼 수 있습니다. AWS CLI용 Session Manager plugin이 필요합니다.

```bash
aws ssm start-session \
  --region ap-northeast-2 \
  --target "$(terraform output -raw instance_id)" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8501"],"localPortNumber":["8501"]}'
```

API도 필요하면 같은 방식으로 원격 `8000`을 로컬 `8000`에 포워딩합니다. 직접 접속을 위한 `streamlit_cidrs`를 지정했다면, 해당 CIDR에서만 `http://<public_ip>:8501`에 접근할 수 있습니다. 이 구성은 TLS를 제공하지 않으므로 실제 영상과 API 키를 다루는 화면은 SSM 포워딩을 우선 사용하세요.

EC2의 앱 환경은 별도로 주입해야 합니다. `S3_BUCKET=<video_bucket_name>`, `S3_KEY_PREFIX=<video_key_prefix>`, `AWS_REGION=<aws_region>`을 설정하고, EC2 역할을 사용할 때 `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`를 비웁니다. `.env`, Gemini API 키, Modal 토큰, PostgreSQL 비밀번호는 Terraform `user_data`나 Git에 넣지 않습니다. Modal의 `cctv-s3` Secret에는 가중치 버킷과 영상 버킷에 대한 별도 AWS 자격 증명이 필요합니다. 영상 버킷이 고객 관리 KMS 키로 암호화되어 있다면 EC2 역할에 해당 키의 최소 암·복호화 권한도 별도로 설정해야 합니다.

## 비용과 종료

EC2, EBS, 퍼블릭 IPv4, S3 요청/전송 등에 비용이 발생합니다. 사용하지 않을 때는 EC2를 중지하면 컴퓨팅 비용을 줄일 수 있지만 EBS와 퍼블릭 IPv4 주소 등의 비용/주소 변화가 남을 수 있습니다. 완전히 정리하려면 `terraform destroy` 계획을 확인한 뒤 실행합니다. 루트 볼륨은 인스턴스 삭제 시 삭제되므로 PostgreSQL을 그 안에 둘 경우 필요한 데이터는 먼저 백업해야 합니다.

참고: [AWS SSM Agent와 Amazon Linux 2023](https://docs.aws.amazon.com/systems-manager/latest/userguide/agent-install-al2.html), [SSM 포트 포워딩](https://docs.aws.amazon.com/en_en/systems-manager/latest/userguide/session-manager-working-with-sessions-start.html), [IMDSv2 설정](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-IMDS-new-instances.html).
