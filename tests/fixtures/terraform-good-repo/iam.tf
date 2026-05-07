data "aws_iam_policy_document" "least_privilege" {
  statement {
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["arn:aws:s3:::my-bucket/*"]
  }
}

resource "aws_iam_role_policy" "scoped" {
  name   = "scoped-policy"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.least_privilege.json
}

resource "aws_iam_role" "app" {
  name = "app-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}
