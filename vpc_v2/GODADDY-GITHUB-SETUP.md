# Configuración externa — GoDaddy + GitHub

Todo lo que **Terraform NO puede hacer solo** porque vive fuera de AWS:
DNS en GoDaddy y configuración de GitHub (OAuth App + Actions). Checklist
para dejar la arquitectura completa funcionando después de un
`terraform apply` en `vpc_v2/terraform`.

Dominio: `secretsapi.online`. Repo del front: `var.github_repo_front`
(`terraform.tfvars`).

---

## 1. GoDaddy — DNS

Panel: **GoDaddy → Mis Productos → secretsapi.online → DNS → DNS Records**.

### 1.1 Validar el certificado ACM (una vez por cada `apply` que recree el cert)

Corré esto parado en `vpc_v2/terraform` (ajustá el `cd` según desde dónde
arranques — ej. `cd tek-secrets/vpc_v2/terraform` si estás en la raíz del
repo):

```bash
terraform output acm_validation_records
```

Da algo así:
```
{
  "name"  = "_10b92720a119190a81bfce277414aede.secretsapi.online."
  "type"  = "CNAME"
  "value" = "_c627111623a41eb2cd66be0db4dce6bc.wzccmgtwzk.acm-validations.aws."
}
```

**Add New Record** (nuevo, no editar uno existente la primera vez) con
estos 4 campos. Con el ejemplo de arriba, quedaría así (con TU output
real, los valores van a ser distintos — cambian en cada `apply` que
recree el cert):

| Campo GoDaddy | Valor a pegar |
|---|---|
| Type | `CNAME` |
| Name | `_10b92720a119190a81bfce277414aede` |
| Value | `_c627111623a41eb2cd66be0db4dce6bc.wzccmgtwzk.acm-validations.aws.` |
| TTL | `1 Hora` |

El `name` del output SIEMPRE trae `.secretsapi.online.` pegado al final
— hay que cortarlo antes de pegar en el campo Name, porque GoDaddy
concatena el dominio solo (si lo dejás completo queda duplicado:
`..._aede.secretsapi.online.secretsapi.online`). El `value` sí va
completo y tal cual, sin tocar nada.

El `terraform apply` se queda esperando (timeout 45m) hasta que ACM
re-chequee el DNS — no hace falta reiniciarlo, solo esperar. Si `dig` da
`NXDOMAIN` justo después de guardar, es caché negativo del resolver
público; confirmá contra el nameserver autoritativo:

```bash
dig CNAME <nombre-del-record>.secretsapi.online @ns17.domaincontrol.com
```

### 1.2 CNAMEs de `app.` y `api.`

```bash
terraform output dns_records_needed
```

Da algo así:
```
{
  "api" = {
    "name"  = "api.secretsapi.online"
    "type"  = "CNAME"
    "value" = "tek-secrets-v2-alb-1145412810.us-east-1.elb.amazonaws.com"
  }
  "app" = {
    "name"  = "app.secretsapi.online"
    "type"  = "CNAME"
    "value" = "tek-secrets-v2-alb-1145412810.us-east-1.elb.amazonaws.com"
  }
}
```

Dos registros CNAME — con TU output real (cambia en cada `apply` que
recree el ALB):

| Campo GoDaddy | Registro `app` | Registro `api` |
|---|---|---|
| Type | `CNAME` | `CNAME` |
| Name | `app` (el `name` del output SIN `.secretsapi.online` — mismo motivo que en 1.1, GoDaddy concatena el dominio solo) | `api` |
| Value | `tek-secrets-v2-alb-1145412810.us-east-1.elb.amazonaws.com` | `tek-secrets-v2-alb-1145412810.us-east-1.elb.amazonaws.com` |
| TTL | `1 Hora` | `1 Hora` |

Ambos registros apuntan al MISMO `value` (mismo ALB) — lo que cambia es
el `Name`, que define a cuál target group los enruta el ALB (host-based
routing).

Si ya existen de un `apply` anterior: **editalos** (lápiz), no crees
nuevos — el DNS name del ALB cambia cada vez que Terraform lo recrea.

### 1.3 Forwarding del apex (solo la primera vez — esto sí sobrevive a un destroy)

Pestaña **Forwarding** (no es un registro DNS):

- `secretsapi.online` (pelado) → `https://app.secretsapi.online`

---

## 2. GitHub — OAuth App (login de la app)

**GitHub → Settings → Developer settings → OAuth Apps** (la app que ya
tengan creada para el proyecto, o una nueva).

| Campo | Valor |
|---|---|
| Homepage URL | `https://app.secretsapi.online` |
| Authorization callback URL | `https://app.secretsapi.online/api/auth/callback/github` |

⚠️ El callback va con `app.`, **no** `api.` — el flujo OAuth de NextAuth
vive en el front, no en la API.

Copiar **Client ID** y **Client Secret** a:
- `tek-secrets-app/.env.local` → `GITHUB_ID`, `GITHUB_SECRET`
- `vpc_v2/terraform/terraform.tfvars` → `github_client_id`,
  `github_client_secret` (por defecto trae placeholders `CHANGEME_...` —
  sin esto el login contra la API de AWS no funciona). Después de
  cambiarlos: `terraform apply` (solo esos 2 secrets se actualizan en
  Secrets Manager).

Ambos (front y backend) deben usar la **misma** OAuth App.

---

## 3. GitHub Actions — deploy del front (OIDC, sin access keys)

Repo del front (`var.github_repo_front`, formato `owner/repo`) →
**Settings → Secrets and variables → Actions → New repository secret**.

```bash
terraform output github_actions_role_arn
```

| Secret | Valor |
|---|---|
| `AWS_GITHUB_ACTIONS_ROLE_ARN` | output de arriba |
| `GH_PACKAGES_TOKEN` | Personal Access Token con scope `read:packages`, para bajar el paquete privado `@secrets-27222633/sdk` en el build |

Verificar que `var.github_repo_front` en `terraform.tfvars` matchea EXACTO
`owner/repo` del repo real — el trust policy del rol IAM solo permite
`sub: repo:<ese valor>:ref:refs/heads/main`; si no matchea, el workflow
no puede asumir el rol (`AssumeRoleWithWebIdentity` falla).

El workflow (`deploy.yml` en el repo del front) usa
`aws-actions/configure-aws-credentials` con
`role-to-assume: ${{ secrets.AWS_GITHUB_ACTIONS_ROLE_ARN }}` — sin
credenciales de larga vida.

**Disparar el primer deploy**: push a `main` (o "Re-run all jobs" en
Actions si ya hay un commit en main). El repo ECR del front queda vacío
hasta este primer deploy — el servicio ECS arranca con 0 tasks sanas
mientras tanto, es esperado.

---

## 4. Orden recomendado, de cero

1. `terraform apply` en `vpc_v2/terraform`.
2. GoDaddy 1.1 (CNAME validación ACM) — esperar a que el apply valide el cert.
3. GoDaddy 1.2 (CNAMEs app/api).
4. GoDaddy 1.3 (forwarding del apex) — solo si es la primera vez.
5. GitHub OAuth App (sección 2) — solo si es la primera vez o cambiaron las credenciales.
6. GitHub Actions secrets (sección 3) — solo si es la primera vez.
7. Push a `main` del repo front → dispara el deploy.
8. Verificar: `https://app.secretsapi.online` y `https://api.secretsapi.online/health`.

## 5. Qué sobrevive a un `terraform destroy` y qué no

**Sobrevive** (no repetir):
- OAuth App de GitHub (Client ID/Secret, callback URL).
- Secrets de Actions (`AWS_GITHUB_ACTIONS_ROLE_ARN` es determinístico — mismo nombre de rol, mismo ARN aunque se recree; `GH_PACKAGES_TOKEN` es ajeno a AWS).
- `github_client_id`/`secret` en `terraform.tfvars` (son inputs).
- Forwarding del apex en GoDaddy.

**NO sobrevive** (Terraform genera valores nuevos, hay que repetir el paso):
- DNS name del ALB → CNAMEs `app.`/`api.` en GoDaddy (sección 1.2).
- Certificado ACM y su CNAME de validación (sección 1.1) — el viejo queda huérfano en GoDaddy, no rompe nada si se deja.
- Contenido del ECR del front → primer deploy de GitHub Actions (sección 3, último paso).

Ver `vpc_v2/README.md` sección 10 para el detalle completo de bugs ya
arreglados y el resto del runbook de infraestructura.
