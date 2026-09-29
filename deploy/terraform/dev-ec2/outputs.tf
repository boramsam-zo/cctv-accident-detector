output "instance_id" {
  description = "EC2 ID for SSM Session Manager and port forwarding."
  value       = aws_instance.dev.id
}

output "public_ip" {
  description = "Public IPv4 address. No inbound ports are open by default."
  value       = aws_instance.dev.public_ip
}

output "video_s3_prefix" {
  description = "S3_KEY_PREFIX to use in the backend environment."
  value       = var.video_key_prefix
}

output "ssm_start_session_command" {
  description = "Requires AWS CLI and the Session Manager plugin on your machine."
  value       = "aws ssm start-session --region ${var.aws_region} --target ${aws_instance.dev.id}"
}
