variable "aws_region" {
  description = "AWS region containing the subnet and video bucket."
  type        = string
  default     = "ap-northeast-2"
}

variable "project_name" {
  description = "Prefix for named AWS resources."
  type        = string
  default     = "cctv-accident"

  validation {
    condition     = can(regex("^[a-z0-9-]{1,32}$", var.project_name))
    error_message = "project_name must be 1-32 lowercase letters, numbers, or hyphens."
  }
}

variable "subnet_id" {
  description = "Existing public subnet ID. It must have a route to an internet gateway for SSM, package installation, and external APIs."
  type        = string
}

variable "video_bucket_name" {
  description = "Existing S3 bucket used by FastAPI for uploads and inference evidence. The model weights bucket is accessed by Modal separately."
  type        = string
}

variable "video_key_prefix" {
  description = "Nonempty S3 key namespace assigned to this EC2 environment, including the trailing slash. Match S3_KEY_PREFIX in the application."
  type        = string
  default     = "dev/ec2/"

  validation {
    condition     = can(regex("^[A-Za-z0-9_./=-]+/$", var.video_key_prefix)) && !strcontains(var.video_key_prefix, "..") && !startswith(var.video_key_prefix, "/")
    error_message = "video_key_prefix must be a relative, nonempty S3 prefix ending in / and must not contain '..'."
  }
}

variable "instance_type" {
  description = "x86_64 instance size. t3.medium has enough memory for a small dev API, worker, Streamlit, and PostgreSQL stack."
  type        = string
  default     = "t3.medium"

  validation {
    condition     = contains(["t3.small", "t3.medium", "t3.large"], var.instance_type)
    error_message = "instance_type must be t3.small, t3.medium, or t3.large (x86_64)."
  }
}

variable "root_volume_gib" {
  description = "Encrypted gp3 root volume size."
  type        = number
  default     = 30

  validation {
    condition     = var.root_volume_gib >= 20 && var.root_volume_gib <= 100
    error_message = "root_volume_gib must be between 20 and 100."
  }
}

variable "streamlit_cidrs" {
  description = "Optional IPv4 CIDR ranges allowed to access Streamlit on port 8501. Empty by default; use SSM port forwarding."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for cidr in var.streamlit_cidrs : can(cidrhost(cidr, 0)) && cidr != "0.0.0.0/0"])
    error_message = "streamlit_cidrs entries must be valid IPv4 CIDR ranges and cannot be 0.0.0.0/0."
  }
}
