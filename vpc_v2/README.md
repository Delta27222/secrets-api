# Tek Secrets — VPC v2

Reconstrucción de la infraestructura AWS (`vpc/`) hecha desde cero, por
grupos, corrigiendo los bugs que hacían fallar el `setup` original. Ver
`tek-secrets/vpc/README.md` para la arquitectura de referencia (misma
topología de red, mismo diseño de 3 tiers) — este documento cubre solo lo
que cambia y, sobre todo, **qué hacer una vez que ya corriste `terraform
apply`**.

---

## Estructura

```
vpc_v2/
├── terraform/
│   ├── 00-providers.tf   # aws, null, random
│   ├── 01-network.tf     # VPC, subredes, IGW, NAT, rutas
│   ├── 02-security.tf    # Security Groups + NACLs
│   ├── 02-iam.tf         # Roles IAM
│   ├── 03-ecr.tf         # Repos ECR + politicas IAM diferidas
│   ├── 03-endpoints.tf   # VPC Endpoints (ECR, SSM, SQS, etc.)
│   ├── 03-ami.tf         # AMI Docker (null_resource, sin script externo)
│   ├── 03-mirror.tf      # Mirror QuestDB/MongoDB a ECR
│   ├── 03-ec2-questdb.tf
│   ├── 03-ec2-mongodb.tf # Primary + Secondary + Arbiter + keyFile
│   ├── 04-secrets.tf     # Secrets Manager (generados por Terraform)
│   ├── 04-sqs.tf
│   ├── 04-alb.tf
│   ├── 04-api-image.tf   # build + push de la imagen API (null_resource)
│   ├── 04-ecs.tf
│   ├── 04-lambda.tf
│   ├── 05-backup.tf      # AWS Backup
│   ├── variables.tf / outputs.tf / terraform.tfvars
│
└── scripts/              # userdata (EC2) + helpers de los null_resource
```

**Diferencia clave con `vpc/`:** todo vive dentro del mismo `terraform
apply` — AMI, mirror de imágenes, build/push de la API y secretos ya no son
pasos previos de un script externo. Correr `terraform apply` de nuevo
alcanza para reconstruir o actualizar cualquier cosa.

---

## Después del `apply` — qué revisar primero

```bash
cd tek-secrets/vpc_v2/terraform
terraform output
```

Esto te da todo lo demás de esta guía: `alb_dns_name`, IDs de instancias,
nombres de cluster/servicio ECS, URLs de las colas SQS, etc. Ningún comando
de abajo debería necesitar un ID pegado a mano — sácalo de aquí.

### 1. La API responde

```bash
ALB=$(terraform output -raw alb_dns_name)
curl http://$ALB/health
# {"status":"ok"}
```

### 2. Docs interactivas (Swagger)

Abre en el navegador:

```
http://<alb_dns_name>/docs
```

Todos los endpoints reales viven bajo el prefijo `/v1/...`. Desde ahí
puedes probarlos a mano con "Try it out" sin necesitar el CLI ni Postman.

### 3. Logs de la API en vivo

```bash
aws logs tail /ecs/tek-secrets-v2-api --follow --region us-east-1
```

### 4. Estado del servicio ECS

```bash
aws ecs describe-services \
  --cluster $(terraform output -json ecs_cluster_name | tr -d '"') \
  --services $(terraform output -json ecs_service_name | tr -d '"') \
  --query 'services[0].{Status:status,Running:runningCount,Desired:desiredCount}'
```

### 5. Entrar a MongoDB o QuestDB sin SSH (SSM Session Manager)

```bash
MONGO_ID=$(terraform output -raw mongodb_primary_instance_id)
aws ssm start-session --target "$MONGO_ID"

# Dentro de la sesión:
docker exec -it mongodb-primary mongosh \
  -u admin -p <valor de mongodb_admin_password> \
  --authenticationDatabase admin \
  --eval "rs.status().members.forEach(m => print(m.name + ' ' + m.stateStr))"
```

`<valor de mongodb_admin_password>` = variable `mongodb_admin_password` en
`tek-secrets/vpc_v2/terraform/terraform.tfvars`:
```bash
grep '^mongodb_admin_password' tek-secrets/vpc_v2/terraform/terraform.tfvars
```

Estado esperado: un `PRIMARY`, un `SECONDARY`, un `ARBITER`, todos
`health=1`.

Para QuestDB (consola web en `localhost:9000`, sin abrir puertos):

```bash
QUESTDB_ID=$(terraform output -raw questdb_primary_instance_id)
aws ssm start-session \
  --target "$QUESTDB_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["9000"],"localPortNumber":["9000"]}'
# Abre http://localhost:9000 en el navegador
```

### 6. Probar con el CLI del proyecto

```bash
cd tek-secrets/cli
poetry run tek-secrets --help
```

Apunta la configuración del CLI (o `NEXT_PUBLIC_API_URL` del frontend) al
`alb_dns_name` de arriba.

### 7. Colas SQS y Lambdas

```bash
terraform output -json sqs_queue_urls
terraform output -json lambda_function_names

aws logs tail /aws/lambda/tek-secrets-v2-logs-consumer --follow --region us-east-1
aws logs tail /aws/lambda/tek-secrets-v2-rotation-master --follow --region us-east-1
```

### 8. Correr la API local contra la infra de AWS (sin desplegar nada)

MongoDB y QuestDB están en subredes privadas — para que `tek-secrets/api/`
corriendo en tu laptop (`fastapi dev`) les llegue, necesitas **2 túneles
SSM abiertos a la vez**, cada uno en su propia terminal (se quedan
colgados, eso es correcto — no los cierres mientras desarrollas):

```bash
cd tek-secrets/vpc_v2/terraform

# Terminal A — túnel a MongoDB Primary
aws ssm start-session --region us-east-1 \
  --target "$(terraform output -raw mongodb_primary_instance_id)" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["27017"],"localPortNumber":["27017"]}'

# Terminal B — túnel a QuestDB Primary
aws ssm start-session --region us-east-1 \
  --target "$(terraform output -raw questdb_primary_instance_id)" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["9000"],"localPortNumber":["9000"]}'
```

Luego edita **`tek-secrets/api/.env`** (archivo local, no lo toca
`terraform apply`) — tres variables que hay que alinear a mano, cada una
con la variable/archivo de origen del que sale el valor real:

**1. `EC2_INSTANCE_IP`** en `tek-secrets/api/.env`
```
EC2_INSTANCE_IP=localhost
```
Literal `localhost` — no la IP privada real (inalcanzable desde tu
laptop) ni una IP pública vieja de otro deploy.

**2. `MONGODB_URL`** en `tek-secrets/api/.env`
```
MONGODB_URL=mongodb://admin:<password-encodeado>@localhost:27017/?authSource=admin&directConnection=true
```
`<password-encodeado>` sale de la variable `mongodb_admin_password` en
`tek-secrets/vpc_v2/terraform/terraform.tfvars`, pero **URL-encodeado**
(un password `openssl rand -base64` casi siempre trae `/`, `+` o `=`, que
rompen la URI si van tal cual — mismo bug que tuvimos en Terraform sin
`urlencode()`):
```bash
RAW=$(grep '^mongodb_admin_password' tek-secrets/vpc_v2/terraform/terraform.tfvars | cut -d'"' -f2)
python3 -c "import urllib.parse,sys; print(urllib.parse.quote_plus(sys.argv[1]))" "$RAW"
```
Pega el resultado en el lugar de `<password-encodeado>`. `directConnection=true`
es obligatorio: sin eso, el driver intenta descubrir el resto del Replica
Set por sus IPs privadas reales, que tu laptop no alcanza.

**3. `MONGODB_CSFLE_MASTER_KEY`** en `tek-secrets/api/.env`

Esta NO sale de `terraform.tfvars` — Terraform la genera sola
(`random_password.csfle_master_key` en `04-secrets.tf`) y vive en Secrets
Manager. Debe ser la MISMA que usa la API desplegada en AWS, no la que
tengas guardada de una corrida anterior: local y AWS comparten la misma
MongoDB (vía el túnel), así que quien haya inicializado la llave de
encriptación (DEK) primero manda — si tu `.env` local tiene un valor
distinto al de Secrets Manager, cualquier `encrypt_field`/`decrypt_field`
(por ejemplo, crear un proyecto o guardar variables de entorno) truena con
`HMAC validation failure`. Sincronízala así:
```bash
aws secretsmanager get-secret-value \
  --secret-id tek-secrets-v2/csfle-master-key \
  --region us-east-1 --query SecretString --output text
```
y pega ese valor exacto en `MONGODB_CSFLE_MASTER_KEY` dentro de
`tek-secrets/api/.env`.

**4. `SQS_QUEUE_URL`** en `tek-secrets/api/.env`

Suele quedar apuntando a la cola del proyecto viejo
(`tek-secrets-logs-queue`, sin el `-v2-`), que ya no existe — cualquier
log que la API intente mandar truena con
`AWS.SimpleQueueService.NonExistentQueue`. Sale de la variable de salida
`sqs_queue_urls` (grupo 4, `04-sqs.tf`):
```bash
terraform -chdir=tek-secrets/vpc_v2/terraform output -json sqs_queue_urls
```
y toma el valor de `"logs"`:
```
SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/<tu-account-id>/tek-secrets-v2-logs-queue
```

Después de tocar `.env`, reinicia el server (`Ctrl+C` y vuelve a correr
`fastapi dev`) — el `--reload` de uvicorn recarga código, **no** variables
de entorno.

### 9. Apuntar el frontend (`tek-secrets-app`) a la API de AWS

El frontend Next.js trae un fallback hardcodeado al Render viejo en
`tek-secrets-app/lib/api.ts:3`:
```ts
const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://tek-secrets.onrender.com"
```
Para que hable con la API de `vpc_v2` en vez de eso (o del `localhost:8000`
que uses para desarrollo local de la API), cambia una sola variable:

**`NEXT_PUBLIC_API_URL`** en `tek-secrets-app/.env.local`
```
NEXT_PUBLIC_API_URL=http://<alb_dns_name>
```
`<alb_dns_name>` sale de:
```bash
terraform -chdir=tek-secrets/vpc_v2/terraform output -raw alb_dns_name
```

Reinicia `npm run dev` después de tocar `.env.local` (mismo motivo que con
la API: las env vars no se recargan solas, `NEXT_PUBLIC_*` además quedan
inyectadas en el bundle del navegador en build-time).

⚠️ **No confundir con `NEXTAUTH_URL`** — esa es la URL del propio frontend
(dónde vive Next.js, para los callbacks de OAuth), no la de la API. No hay
que tocarla para este cambio.

⚠️ **GitHub OAuth**: `GITHUB_ID` en `tek-secrets-app/.env.local` y
`github_client_id`/`github_client_secret` en
`tek-secrets/vpc_v2/terraform/terraform.tfvars` deberían ser la MISMA
GitHub OAuth App (`tek-secrets-app/app/api/auth/[...nextauth]/route.ts`
usa `GithubProvider` con esas credenciales). Ahora mismo el backend de
`vpc_v2` tiene placeholders (`CHANGEME_...`) — si necesitas que el login
funcione contra la API desplegada, copia los valores reales del `.env.local`
del frontend a `terraform.tfvars` y corre `terraform apply` (ver tabla de
abajo).

### 10. Front dentro de la VPC (ECS Fargate + dominio propio)

El front (`secrets-app`) ya no va en Render — corre como servicio ECS
Fargate propio, en las mismas subredes privadas que la API (ambas AZ),
detrás del mismo ALB (host-based routing: `app.` / `api.`) y hablándole a
la API por Service Connect (interno, sin salir de la VPC). Dominio:
`secretsapi.online`, DNS en GoDaddy, cert ACM wildcard, deploy del front
vía GitHub Actions con OIDC, un solo ambiente (sin staging replicado).

### 10.1 Qué sobrevive a un `destroy` y qué no

Esto importa porque cambia qué pasos hay que repetir cada vez que se
destruye y se vuelve a levantar (ej. para no pagar de más — ver sección de
costos más abajo si existe, o la conversación que armó esto).

**Sobrevive** (no hay que tocarlo de nuevo):
- GitHub OAuth App (Client ID/Secret, Redirect URI) — vive en GitHub, ajeno a AWS.
- Secrets de GitHub Actions en `secrets-app` (`AWS_GITHUB_ACTIONS_ROLE_ARN`, `GH_PACKAGES_TOKEN`) — el ARN del rol IAM es determinístico (mismo nombre de rol = mismo ARN aunque Terraform lo recree), y el token de packages es ajeno a AWS.
- `github_client_id`/`secret`/`org_name`, contraseñas de Mongo/QuestDB en `terraform.tfvars` — son inputs, no outputs.
- El código: Dockerfile, `next.config.mjs` (`output: standalone`), `.github/workflows/deploy.yml`, el healthcheck (`wget` a `127.0.0.1`) — todo ya commiteado.

**NO sobrevive** (Terraform lo recrea con valores nuevos, hay que re-tomarlos):
- **DNS name del ALB** (cambia — es un recurso nuevo con nombre asignado por AWS). Los CNAME `app.`/`api.` en GoDaddy hay que **editarlos** (no agregar nuevos) con el valor nuevo de `terraform output dns_records_needed`.
- **Certificado ACM + su CNAME de validación** (cert nuevo cada vez → hash de validación nuevo). Hay que repetir el paso de pegar el CNAME en GoDaddy con el valor nuevo de `terraform output acm_validation_records`. El CNAME viejo en GoDaddy queda huérfano — no rompe nada si lo dejás, pero se puede borrar.
- Datos: Mongo, QuestDB, y los secrets generados solos (`SECRET_KEY`, `CSFLE_MASTER_KEY`, `NEXTAUTH_SECRET`) — todo nuevo, sin nada que migrar (es el diseño: "ambiente nuevo").
- El repo ECR del front queda vacío — el servicio arranca con 0 tasks sanas hasta el primer deploy de GitHub Actions.

### 10.2 Runbook completo — de cero a andando

1. **`terraform apply`** en `vpc_v2/terraform`. Tarda ~15-20 min (EC2, NAT, ECS, Lambdas). Si salta `Create service is not idempotent` (ECS tarda unos minutos en liberar el nombre de un service recién borrado) o `ResourceAlreadyExistsException` en un log group huérfano, ver 10.4 — no son bugs, se resuelven solos o con un `import`.

2. **Validar el cert ACM**: `terraform output acm_validation_records` → pegar ese CNAME en **GoDaddy → secretsapi.online → DNS → DNS Records → Add New Record** (nuevo registro, no editar uno viejo).

   ⚠️ Campo **Name**: SOLO el prefijo (ej. `_10b92720a119190a81bfce277414aede`), **sin** `.secretsapi.online` al final — GoDaddy concatena el dominio solo.

   ⚠️ Lápiz = editar el registro de esa fila, no crear uno nuevo. Usá "Add New Record" para uno nuevo.

   ⚠️ Si `dig` da `NXDOMAIN` justo después de guardar, puede ser caché negativo del SOA de GoDaddy (600s en resolvers tipo 8.8.8.8). Confirmá sin caché contra el nameserver autoritativo:
   ```bash
   dig CNAME <nombre-del-record>.secretsapi.online @ns17.domaincontrol.com
   ```
   El apply se queda esperando (timeout 45m) hasta que el cert valide — no hace falta reiniciarlo, solo esperar a que ACM re-chequee (poll periódico, no instantáneo, puede tardar 5-15 min extra después de que el DNS ya esté bien).

3. **CNAMEs de app/api**: `terraform output dns_records_needed` → en GoDaddy, **editá** (o creá si es la primera vez) los CNAME `app` y `api` con el DNS name nuevo del ALB.

4. **Domain forwarding del apex** (solo la primera vez, esto sí sobrevive): `secretsapi.online` (pelado) → `https://app.secretsapi.online`, pestaña **Forwarding** en GoDaddy (no es un registro DNS).

5. **Primer deploy del front**: push a `main` en `secrets-app` (o "Re-run all jobs" en Actions si ya hay un commit en main) — dispara `deploy.yml`: build con el `GH_PACKAGES_TOKEN` (paquete privado `@secrets-27222633/sdk`) y `NEXT_PUBLIC_API_URL=https://api.secretsapi.online` horneado en build-time, push a ECR, registra task definition, actualiza el servicio. `AWS_GITHUB_ACTIONS_ROLE_ARN` y `GH_PACKAGES_TOKEN` ya están guardados como secrets del repo — no hace falta tocarlos de nuevo.

6. **Verificar**: `https://app.secretsapi.online` (front) y `https://api.secretsapi.online/health` (API) deberían responder. Login de GitHub OAuth ya apunta al callback correcto (`https://app.secretsapi.online/api/auth/callback/github`) — no hace falta tocar la OAuth App de GitHub de nuevo.

### 10.3 Bugs reales que ya están arreglados en el código (no deberían volver a aparecer)

- **`gid '1000' in use`** al buildear la imagen del front: `node:20-alpine` ya trae un usuario `node` en uid/gid 1000 — el Dockerfile lo reusa, no crea uno nuevo.
- **`npm error 401` bajando `@secrets-27222633/sdk`**: paquete privado de GitHub Packages en un org distinto al del repo — el `GITHUB_TOKEN` automático de Actions no alcanza. El build usa `GH_PACKAGES_TOKEN` (PAT con `read:packages`) vía secret mount de BuildKit (`--secret id=github_token,env=GITHUB_TOKEN`), nunca queda en una capa de la imagen.
- **Login roto con "the redirect_uri is not associated with this application"**: el Redirect URI de la OAuth App de GitHub apuntaba a `api.secretsapi.online` — el callback de NextAuth vive en el **front**, tiene que ser `https://app.secretsapi.online/api/auth/callback/github`.
- **El front seguía llamando a `tek-secrets.onrender.com` (CORS) aunque `NEXT_PUBLIC_API_URL` estaba seteado en la task definition**: `NEXT_PUBLIC_*` se hornea en el bundle del navegador durante `next build`, no en runtime — un env var de ECS no sirve para el código que corre en el browser. Se pasa como `--build-arg` en el `docker build` del workflow (ver `Dockerfile`, `ARG NEXT_PUBLIC_API_URL`).
- **`aws_ecs_service.api/front: does not have an associated load balancer`**: el `depends_on` de los services no incluía el listener/listener rule que realmente asocia cada target group al ALB (con dominio configurado, `http_redirect` deja de hacer forward a la API). Ver `depends_on` en `04-ecs.tf`.
- **Task del front matado por "failed container health checks" pese a loguear "Ready" casi al instante**: el healthcheck original (`node -e fetch(...)`) levanta un proceso Node/V8 entero cada 30s — en 0.25 vCPU eso compite por CPU con el propio server y puede pasarse del timeout bajo throttling real. Se cambió a `wget` (BusyBox, ~10x más liviano) contra `127.0.0.1` explícito (no `localhost`: musl/Alpine lo resuelve a `::1` primero y el server solo escucha IPv4).

### 10.4 Hiccups transitorios (no son bugs, solo timing de AWS)

- **`aws_ecs_service.api: Create service is not idempotent`**: AWS ECS tarda unos minutos en liberar el nombre de un service recién borrado. Se resuelve solo reintentando `terraform apply` un rato después.
- **`aws_cloudwatch_log_group.*: ResourceAlreadyExistsException`**: si un log group sobrevivió al destroy (huérfano, no quedó en el state), se importa en vez de recrear:
  ```bash
  terraform import aws_cloudwatch_log_group.<nombre> /ruta/del/log/group
  ```

Ninguno de los dos bloquea que el resto del `apply` avance — Terraform sigue con lo demás y solo reintentás lo que falló.

### 10.5 Costo — apagar cuando no se usa

Todo esto es infraestructura *always-on* que cobra por hora exista o no
tráfico (EC2, NAT Gateway, ALB, Fargate, 7 VPC Interface Endpoints). Estimado
en cero uso: **~$280-300/mes**. Si no se necesita corriendo todo el tiempo,
`terraform destroy` cuando no se usa y `terraform apply` (siguiendo este
runbook) cuando sí — evita pagar semanas muertas.

---

## Qué NO va a funcionar todavía

Todas las variables de esta tabla viven en
**`tek-secrets/vpc_v2/terraform/terraform.tfvars`**.

| Variable | Por qué | Cómo arreglarlo |
|---|---|---|
| `github_client_id`, `github_client_secret` | Placeholders (`CHANGEME_...`) | Pon las credenciales reales de tu GitHub OAuth App en `terraform.tfvars` y corre `terraform apply` (solo esos 2 secretos se actualizan) |
| `rotation_api_token` | Placeholder (`tok_placeholder_update_after_deploy`) | Emite un token real desde la API ya corriendo, ponlo en `terraform.tfvars`, `terraform apply` |
| Front (`aws_ecs_service.front`) | El repo ECR `tek-secrets-v2-front` esta vacio hasta el primer push a `main` de `secrets-app` | Ver sección 10 — orden: `terraform apply` primero, GitHub Actions después |

Ninguno bloquea que el resto de la infraestructura funcione.

---

## Redesplegar tras un cambio de código

```bash
cd tek-secrets/vpc_v2/terraform
terraform apply
```

Nada más. El hash del código de `tek-secrets/api/` se recalcula solo — si
cambió, Terraform reconstruye la imagen, la sube a ECR y fuerza el redeploy
de ECS como parte del mismo `apply`. No hay un comando `image` aparte.

## Destruir todo

Pendiente: script de destroy dedicado (ver conversación — AWS Backup,
NAT Gateways y ENIs de Lambda necesitan limpieza manual antes de
`terraform destroy` solo, igual que en `vpc/`).
