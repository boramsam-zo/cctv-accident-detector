"""Create the bucket used by the local S3 test server."""

import os

import boto3
from botocore.exceptions import ClientError


def main() -> None:
    bucket = os.environ["S3_BUCKET"]
    region = os.getenv("AWS_REGION", "ap-northeast-2")
    endpoint = os.environ["S3_ENDPOINT_URL"]
    client = boto3.client("s3", endpoint_url=endpoint, region_name=region)
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 404:
            raise
        client.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": region})
    print(f"Local S3 bucket ready: {bucket}")


if __name__ == "__main__":
    main()
