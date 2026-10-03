# ============================================================================
# Grupo 4 — OIDC de GitHub Actions (deploy del front, sin credenciales de
# larga vida)
#
# El trust policy restringe el sub al branch main del repo del front
# (var.github_repo_front) — un workflow corriendo desde otro repo o otro
# branch no puede asumir este rol.
# ============================================================================

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # Thumbprint fijo de la CA raiz de GitHub, documentado por AWS/GitHub
  # para este provider — no cambia por repo ni por cuenta.
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]

  tags = { Name = "${var.project_name}-github-oidc" }
}

resource "aws_iam_role" "github_actions_front" {
  name        = "${var.project_name}-github-actions-front"
  description = "Asumido por GitHub Actions del repo del front para build+push a ECR y deploy a ECS"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo_front}:ref:refs/heads/main"
        }
      }
    }]
  })

  tags = { Name = "${var.project_name}-github-actions-front-role" }
}

resource "aws_iam_role_policy" "github_actions_front_ecr" {
  name = "ecr-push-front"
  role = aws_iam_role.github_actions_front.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ECRAuthToken"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Sid    = "ECRPushFront"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
        ]
        Resource = aws_ecr_repository.front.arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "github_actions_front_ecs" {
  name = "ecs-deploy-front"
  role = aws_iam_role.github_actions_front.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # ecs:RegisterTaskDefinition no soporta restriccion por Resource
        # (limitacion de AWS, no un descuido) — el scope real lo da que
        # este rol solo puede hacer PassRole de los 2 roles de abajo.
        Sid      = "RegisterTaskDefinition"
        Effect   = "Allow"
        Action   = ["ecs:RegisterTaskDefinition", "ecs:DescribeTaskDefinition"]
        Resource = "*"
      },
      {
        Sid      = "UpdateFrontService"
        Effect   = "Allow"
        Action   = ["ecs:UpdateService", "ecs:DescribeServices"]
        Resource = "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:service/${aws_ecs_cluster.main.name}/${aws_ecs_service.front.name}"
      },
      {
        Sid      = "PassRolesToECS"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = [aws_iam_role.ecs_execution.arn, aws_iam_role.ecs_task_front.arn]
      }
    ]
  })
}
