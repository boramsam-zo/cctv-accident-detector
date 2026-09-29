data "aws_subnet" "selected" {
  id = var.subnet_id
}

data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "video_s3" {
  statement {
    sid       = "ReadWriteOnlyDevVideoObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["arn:aws:s3:::${var.video_bucket_name}/${var.video_key_prefix}*"]
  }
}

resource "aws_iam_role" "ec2" {
  name               = "${var.project_name}-dev-ec2"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "video_s3" {
  name   = "video-prefix-read-write"
  role   = aws_iam_role.ec2.id
  policy = data.aws_iam_policy_document.video_s3.json
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${var.project_name}-dev-ec2"
  role = aws_iam_role.ec2.name
}

resource "aws_security_group" "ec2" {
  name_prefix = "${var.project_name}-dev-ec2-"
  description = "Development EC2; no inbound access by default"
  vpc_id      = data.aws_subnet.selected.vpc_id

  dynamic "ingress" {
    for_each = var.streamlit_cidrs
    content {
      description = "Streamlit from approved developer network"
      from_port   = 8501
      to_port     = 8501
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }

  egress {
    description = "Package repositories, SSM, AWS APIs, Modal, and Gemini"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_instance" "dev" {
  ami                         = data.aws_ssm_parameter.al2023_ami.value
  instance_type               = var.instance_type
  subnet_id                   = data.aws_subnet.selected.id
  vpc_security_group_ids      = [aws_security_group.ec2.id]
  iam_instance_profile        = aws_iam_instance_profile.ec2.name
  associate_public_ip_address = true
  monitoring                  = false
  user_data                   = file("${path.module}/user_data.sh")
  user_data_replace_on_change = true

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gib
    encrypted             = true
    delete_on_termination = true
  }

  tags = {
    Name = "${var.project_name}-dev"
  }
}
