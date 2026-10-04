ARG MLFLOW_VERSION=v3.16.1
FROM ghcr.io/mlflow/mlflow:${MLFLOW_VERSION}-full

# The official image does not guarantee the PostgreSQL driver and AWS SDK
# versions needed by this deployment, so install them explicitly.
RUN pip install --no-cache-dir \
    "psycopg2-binary>=2.9,<3" \
    "boto3>=1.35,<2"
