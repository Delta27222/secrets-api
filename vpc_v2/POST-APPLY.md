# Pasos después de `terraform apply`

Checklist corto de lo que hay que hacer cada vez que se corre
`terraform apply` en `vpc_v2/terraform`. El detalle completo de GoDaddy y
GitHub está en [`GODADDY-GITHUB-SETUP.md`](GODADDY-GITHUB-SETUP.md).

Todos los comandos se corren **parado en `vpc_v2/terraform`** — si no,
`terraform output` sale vacío y el `aws ssm start-session` falla con
`Invalid length for parameter Target`.

```bash
cd tek-secrets/vpc_v2/terraform
```

---

## 1. Actualizar los CNAME de `app` y `api` en GoDaddy

El DNS name del ALB cambia cada vez que Terraform lo recrea, así que hay
que volver a apuntar los subdominios.

```bash
terraform output dns_records_needed
```

Da algo así:
```
{
  "api" = { name = "api.secretsapi.online", type = "CNAME", value = "tek-secrets-v2-alb-XXXX.us-east-1.elb.amazonaws.com" }
  "app" = { name = "app.secretsapi.online", type = "CNAME", value = "tek-secrets-v2-alb-XXXX.us-east-1.elb.amazonaws.com" }
}
```

En **GoDaddy → Mis Productos → secretsapi.online → DNS → DNS Records**,
**editar** (lápiz) los dos registros existentes — no crear nuevos:

| Campo | Registro `app` | Registro `api` |
|---|---|---|
| Type | `CNAME` | `CNAME` |
| Name | `app` | `api` |
| Value | `value` del output | `value` del output (el mismo) |
| TTL | `1 Hora` | `1 Hora` |

En `Name` va solo `app` / `api`, **sin** `.secretsapi.online` — GoDaddy
concatena el dominio solo.

> Si el apply recreó el certificado ACM, antes hay que agregar el CNAME
> de validación (`terraform output acm_validation_records`). Ver sección
> 1.1 de `GODADDY-GITHUB-SETUP.md`.

Verificar (puede tardar unos minutos en propagar):
```bash
dig +short app.secretsapi.online
curl -s https://api.secretsapi.online/health
```

### 1.1 Si `app.secretsapi.online` da `503 Service Unavailable`: desplegar el front

Un 503 del ALB significa que el target group del front **no tiene tareas
sanas**. Después de un apply que recrea el repo ECR
`tek-secrets-v2-front`, el repo queda **vacío**: Terraform no construye la
imagen del front, la construye GitHub Actions (`deploy.yml` en
`Delta27222/secrets-app`), y ese workflow **solo se dispara con un push a
`main`**. Hasta que corra, el servicio ECS no puede arrancar tareas. La API
no tiene este problema porque su imagen la publica Terraform
(`04-api-image.tf`).

**Confirmar el diagnóstico:**
```bash
# El repo del front no debe tener tags (vacío = este problema)
aws ecr list-images --region us-east-1 \
  --repository-name tek-secrets-v2-front --query 'imageIds[].imageTag'

# El servicio muestra running 0 y el error de pull
aws ecs describe-services --region us-east-1 \
  --cluster tek-secrets-v2-cluster --services tek-secrets-v2-front-service \
  --query 'services[0].{desired:desiredCount,running:runningCount,events:events[0:3].message}'
```
Evento típico:
```
CannotPullContainerError: ... tek-secrets-v2-front:latest: not found
```

**Arreglo:** volver a correr el último deploy exitoso del front. Los
secrets de GitHub no se tocan: `AWS_GITHUB_ACTIONS_ROLE_ARN` es
determinístico (mismo nombre de rol, mismo ARN aunque se recree).

```bash
# Buscar el último run exitoso de "Deploy front a ECS"
gh run list -R Delta27222/secrets-app --workflow deploy.yml --status success -L 1

# Re-ejecutarlo (reemplazar por el ID de arriba; ej. 37103806476)
gh run rerun 37103806476 -R Delta27222/secrets-app

# Seguirlo en vivo
gh run watch -R Delta27222/secrets-app
```

Alternativa: hacer cualquier push a `main` del front, por ejemplo un commit
vacío (`git commit --allow-empty -m "chore: redeploy" && git push`).

El deploy tarda ~8–12 min. Al terminar, verificar:
```bash
aws ecs describe-services --region us-east-1 \
  --cluster tek-secrets-v2-cluster --services tek-secrets-v2-front-service \
  --query 'services[0].{desired:desiredCount,running:runningCount}'
curl -sI https://app.secretsapi.online | head -1
```
Debe quedar `running: 1` y el `curl` debe devolver `200` (o un `307` hacia
el login).

Si el rerun falla:
- **En `Configure AWS credentials`** (`AssumeRoleWithWebIdentity`): falta
  el secret `AWS_GITHUB_ACTIONS_ROLE_ARN` o `github_repo_front` no coincide
  con el repo. Ver sección 3 de `GODADDY-GITHUB-SETUP.md`.
- **En `Build y push de la imagen`** con `npm ci` y `E401` (ver abajo).

#### Error `E401 Unauthorized` en `npm ci` (token de paquetes vencido)

En el log del paso `Build y push de la imagen` se ve algo así:
```
ERROR: failed to build: failed to solve: process "/bin/sh -c npm ci" did not complete successfully: exit code: 1
```
Ese mensaje no dice la causa. Para verla:
```bash
ID=$(gh run list -R Delta27222/secrets-app --workflow deploy.yml -L 1 \
  --json databaseId -q '.[0].databaseId')
gh run view $ID -R Delta27222/secrets-app --log-failed | grep -iE "npm error|E40[0-9]"
```
Si aparece:
```
npm error code E401
npm error 401 Unauthorized - GET https://npm.pkg.github.com/download/@secrets-27222633/sdk/...
unauthenticated: User cannot be authenticated with the token provided.
```
el build no puede bajar el paquete privado `@secrets-27222633/sdk` porque
el secret `GH_PACKAGES_TOKEN` del repo **venció o fue revocado**. El paso
de AWS (OIDC) no tiene que ver con este error.

**Arreglo:**

1. **Crear un token nuevo:** GitHub → **Settings → Developer settings →
   Personal access tokens → Tokens (classic) → Generate new token
   (classic)**.
   - Scope: solo **`read:packages`**.
   - Expiration: una fecha posterior a la defensa, para que no vuelva a
     vencer en el medio.
   - Si la org `secrets-27222633` usa SSO: **Configure SSO → Authorize**
     para esa org.
2. **Actualizar el secret.** Con `gh` lo pide por stdin, así el token no
   queda en el historial de la terminal:
   ```bash
   gh secret set GH_PACKAGES_TOKEN -R Delta27222/secrets-app
   ```
   O en la web: repo → **Settings → Secrets and variables → Actions →
   `GH_PACKAGES_TOKEN` → Update**.
3. **Relanzar el run fallido**, que construye el último commit de `main`:
   ```bash
   gh run rerun $ID -R Delta27222/secrets-app
   gh run watch -R Delta27222/secrets-app
   ```

Si después de cambiar el token sigue dando `403` en lugar de `401`, el
token es válido pero no tiene acceso al paquete. Revisar que tenga
`read:packages` y que esté autorizado en la org (SSO).

---

## 2. Entrar a QuestDB

QuestDB vive en una subred privada, sin SSH ni puertos abiertos. Se entra
con un túnel de SSM Session Manager.

**Requisito (una vez):** `brew install --cask session-manager-plugin`

```bash
aws ssm start-session --region us-east-1 \
  --target "$(terraform output -raw questdb_primary_instance_id)" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["9000"],"localPortNumber":["9000"]}'
```

Cuando diga `Waiting for connections...`, **dejar esa terminal abierta**
y abrir <http://localhost:9000>. Deben verse 3 tablas: `Logs`,
`system_logs` y `encryption_key_audit`. Para cerrarlo: `Ctrl+C` en esa
terminal (ver sección 4).

### Problemas comunes

- **Solo aparece `Logs` / versión 9.x / "Materialized views"** → estás
  viendo un QuestDB **local**, no el de AWS (el de la VPC es 8.1.1;
  confirmar con `SELECT build();`). Revisar quién ocupa el puerto:
  ```bash
  lsof -nP -iTCP:9000 -sTCP:LISTEN
  ```
  Si es un `java` de Homebrew: `brew services stop questdb`. O dejarlo y
  usar otro puerto local para el túnel (`"localPortNumber":["19000"]` →
  <http://localhost:19000>).
- **`VersionError ... requested version (20) is less than the existing
  version (30)`** en la consola del navegador → quedó guardado el estado
  de una consola más nueva en `localhost:9000`. DevTools → Application →
  **Clear site data**, o usar incógnito / otro puerto local.
- **Cliente Postgres** (`psql`, DBeaver) en vez de la consola web → mismo
  túnel con `8812` en ambos puertos; usuario, base y password en
  `questdb_pg_user`, `questdb_pg_database`, `questdb_pg_password` de
  `terraform.tfvars`.

---

## 3. Entrar a MongoDB

Mismo mecanismo: túnel SSM al **Primary** del replica set.

### 3.1 Abrir el túnel (terminal A — dejarla abierta)

```bash
cd tek-secrets/vpc_v2/terraform

aws ssm start-session --region us-east-1 \
  --target "$(terraform output -raw mongodb_primary_instance_id)" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["27017"],"localPortNumber":["27017"]}'
```

Esperar a que diga:
```
Port 27017 opened for sessionId ...
Waiting for connections...
```

Esa terminal se queda "colgada" — es lo correcto. El túnel solo existe
mientras ese comando corre: si se cierra la terminal, se hace `Ctrl+C` o
la sesión SSM expira por inactividad (~20 min por defecto), cualquier
cliente devuelve:
```
connect ECONNREFUSED 127.0.0.1:27017
```
y hay que volver a correr el comando.

### 3.2 Obtener la password y armar la URL (terminal B)

La password es la variable `mongodb_admin_password` de
`vpc_v2/terraform/terraform.tfvars`. Para verla tal cual (sirve para la
shell dentro de la instancia, 3.4):
```bash
grep '^mongodb_admin_password' terraform.tfvars | cut -d'"' -f2
```

Para la URL de conexión hay que **URL-encodearla** (suele traer `/`, `+`
o `=`, que rompen la URI). Esto imprime la URL completa lista para pegar
en Compass o `mongosh`:
```bash
RAW=$(grep '^mongodb_admin_password' terraform.tfvars | cut -d'"' -f2)
ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote_plus(sys.argv[1]))" "$RAW")
echo "mongodb://admin:$ENC@localhost:27017/secrets-27222?authSource=admin&directConnection=true"
```

Formato resultante:
```
mongodb://admin:<password-encodeado>@localhost:27017/secrets-27222?authSource=admin&directConnection=true
```

⚠️ La URL lleva la password real del admin — no pegarla en archivos que
se commiteen.

### 3.3 Conectar

```bash
mongosh "<url de 3.2>"
```
o pegarla en MongoDB Compass → **New connection**.

- `directConnection=true` es **obligatorio**: sin eso el driver intenta
  descubrir el resto del replica set por sus IPs privadas, que tu laptop
  no alcanza.
- Si tenés un MongoDB local en el 27017, detenerlo antes
  (`brew services stop mongodb-community`) o usar otro puerto local
  (`"localPortNumber":["27018"]` y `localhost:27018` en la URI).

### 3.4 Alternativa: shell dentro de la instancia

```bash
aws ssm start-session --region us-east-1 \
  --target "$(terraform output -raw mongodb_primary_instance_id)"

# Dentro de la sesión:
sudo docker exec -it mongodb-primary mongosh \
  -u admin -p '<mongodb_admin_password>' --authenticationDatabase admin
```
Para salir: `exit` en mongosh y luego `exit` en la sesión SSM.

---

## 4. Cerrar las conexiones (QuestDB y MongoDB)

**Lo normal:** ir a la terminal donde corre el túnel y presionar
**`Ctrl+C`**. Eso cierra la sesión SSM y libera el puerto local (9000 o
27017). Cerrar la ventana de la terminal tiene el mismo efecto.

**Si quedó algún túnel perdido** (terminal cerrada a medias, corrido en
segundo plano, etc.):

```bash
# Ver qué túneles hay abiertos
pgrep -fl session-manager-plugin
lsof -nP -iTCP:9000 -iTCP:27017 -sTCP:LISTEN

# Matar uno en particular
pkill -f "session-manager-plugin.*27017"   # MongoDB
pkill -f "session-manager-plugin.*9000"    # QuestDB

# O todos los túneles SSM de una vez
pkill -f session-manager-plugin
```

Opcional — cerrar también la sesión del lado de AWS (si no, expira sola):
```bash
aws ssm describe-sessions --state Active --region us-east-1 \
  --query 'Sessions[].[SessionId,Target]' --output table
aws ssm terminate-session --session-id <SessionId> --region us-east-1
```

Verificar que quedó cerrado — no debe imprimir nada:
```bash
lsof -nP -iTCP:9000 -iTCP:27017 -sTCP:LISTEN
```

---

## 5. Probar la rotación de llaves (simulando las Lambdas)

Flujo real en producción:

```
EventBridge (cron diario) → rotation-master → SQS rotation-queue → rotation-worker
  → POST /v1/internal/projects/{id}/rotate-encryption (API) → nueva llave + re-encripta secretos
```

⚠️ **No es un simulacro:** cualquiera de las opciones de abajo rota la
llave y re-encripta los secretos **reales** del proyecto en AWS. Probar
primero con un proyecto de prueba.

### 5.1 Requisito: token de sistema con scope `keys:rotate` (una vez)

La worker se autentica contra la API con un service token. Por defecto
`rotation_api_token` vale `tok_placeholder_update_after_deploy`, y con eso
la worker falla con:
```
API rotación falló (HTTP 401): {"detail":"Token not found or revoked"}
```

Para ver qué token tiene la Lambda hoy (solo el prefijo):
```bash
T=$(aws lambda get-function-configuration --region us-east-1 \
  --function-name tek-secrets-v2-rotation-worker \
  --query 'Environment.Variables.ROTATION_API_TOKEN' --output text); echo "${T:0:16}..."
```
Si imprime `tok_placeholder_...`, hacer estos pasos:

1. **Crear el token** en `https://app.secretsapi.online` → **Organización
   → tab Tokens → Crear Token** → scope **`keys:rotate`**. Copiar el
   `tok_...` completo (se muestra **una sola vez**). Solo owners/admins
   de la organización pueden crearlo.
   - Si falla con `Document failed validation`: el validador de Mongo
     exige `project_id` y los tokens de sistema van con `null`. Con el
     túnel de Mongo abierto (sección 3), correr una vez:
     ```bash
     python3 ~/Desktop/tesis/tek-secrets/rotation/scripts/relax_service_token_validator.py \
       --mongodb-url "<url de 3.2>" --db secrets-27222
     ```
2. **Guardarlo** en `vpc_v2/terraform/terraform.tfvars`:
   ```hcl
   rotation_api_token = "tok_..."
   ```
3. **Aplicar solo a la worker:**
   ```bash
   terraform apply -target=aws_lambda_function.rotation_worker
   ```
   No usar `aws lambda update-function-configuration --environment`:
   reemplaza **todas** las variables de entorno y borra `API_BASE_URL`.

Como vive en `terraform.tfvars`, el token sobrevive a futuros `apply`.
Solo hay que recrearlo si la MongoDB es nueva (destroy completo), porque
el token se guarda en la colección `service_tokens`.

### 5.2 Obtener el `project_id`

Con el túnel de Mongo abierto (sección 3):
```bash
mongosh "<url de 3.2>" --eval 'db.projects.find({}, {name:1}).forEach(p => print(p._id + "  " + p.name))'
```

```bash
PROJECT_ID=<_id del proyecto>
```

### 5.3 Disparar la rotación

| Opción | ¿Necesita `project_id`? | Qué hace |
|---|---|---|
| A · invocar master | No | Encola solo los proyectos **vencidos** (≥ 90 días o nunca rotados) |
| B · mensaje a SQS | Sí | Simula la salida de la master; la worker real lo procesa |
| C · invocar worker | Sí | Llama a la worker directo, sin cola; respuesta en la terminal |
| D · curl a la API | Sí (+ token) | Lo que hace la worker por dentro, sin Lambda |

**A — Flujo completo, como el cron:**
```bash
aws lambda invoke --region us-east-1 \
  --function-name tek-secrets-v2-rotation-master /dev/stdout
```
Si todos los proyectos están al día responde `projects_queued: 0` y no
rota nada — sirve para probar el cron, no para forzar un proyecto.

**B — Mensaje a la cola (recomendada para simular el flujo real):**
```bash
aws sqs send-message --region us-east-1 \
  --queue-url "$(terraform output -json sqs_queue_urls | python3 -c 'import json,sys; print(json.load(sys.stdin)["rotation"])')" \
  --message-body "{\"project_id\":\"$PROJECT_ID\",\"action\":\"rotate_and_reencrypt\"}"
```

**C — Invocar la worker con un evento SQS falso:**
```bash
aws lambda invoke --region us-east-1 \
  --function-name tek-secrets-v2-rotation-worker \
  --cli-binary-format raw-in-base64-out \
  --payload "{\"Records\":[{\"body\":\"{\\\"project_id\\\":\\\"$PROJECT_ID\\\"}\"}]}" \
  /dev/stdout
```
O con el ID pegado a mano (comillas simples, sin escapes dobles):
```bash
aws lambda invoke --region us-east-1 \
  --function-name tek-secrets-v2-rotation-worker \
  --cli-binary-format raw-in-base64-out \
  --payload '{"Records":[{"body":"{\"project_id\":\"<project_id>\"}"}]}' \
  /dev/stdout
```
Si la terminal queda en `dquote>`, faltó cerrar una comilla: `Ctrl+C` y
usar la versión con comillas simples.

**D — Directo al endpoint (para aislar problemas):**
```bash
curl -X POST "https://api.secretsapi.online/v1/internal/projects/$PROJECT_ID/rotate-encryption" \
  -H "Authorization: Bearer tok_..."
```
Si D funciona y C no, el problema está en la Lambda o en el token de
`terraform.tfvars`.

### 5.4 Ver el resultado

Logs de las Lambdas:
```bash
aws logs tail /aws/lambda/tek-secrets-v2-rotation-worker --follow --region us-east-1
aws logs tail /aws/lambda/tek-secrets-v2-rotation-master --follow --region us-east-1
```

Respuesta esperada (C): `"statusCode": 200` con `"status": "success"` y
**sin** `"FunctionError"`. En los logs:
`✅ Proyecto <id>: success (N OK, 0 fallos)`.

Verificar que re-encriptó:
- **MongoDB** — en `environments`, `secrets_encryption.encrypted_at` con
  la fecha de ahora; en `encryption_key_versions`, una llave nueva
  `active` y la anterior `deprecated`.
- **QuestDB** (sección 2):
  ```sql
  SELECT * FROM encryption_key_audit ORDER BY timestamp DESC LIMIT 10;
  ```
- **App** — los secretos del proyecto se siguen leyendo bien.

### 5.5 Errores comunes

| Error | Causa | Solución |
|---|---|---|
| `HTTP 401 ... Token not found or revoked` | Token placeholder o borrado | 5.1 |
| `HTTP 403` | El token no tiene scope `keys:rotate` | Recrear el token con ese scope (5.1) |
| `HTTP 404` / `422` | `PROJECT_ID` vacío o incorrecto | Revisar `echo $PROJECT_ID` (5.2) |
| `dquote>` en la terminal | Comillas sin cerrar en `--payload` | `Ctrl+C`, usar la versión con comillas simples |
| Master responde `projects_queued: 0` | Ningún proyecto vencido | Usar B o C para forzar uno |

---

## 6. Cargar datos de demo (organización + 2 proyectos + variables)

Script: `tek-secrets/api/scripts/seed_via_api.py`. Va por la API pública,
así que **no necesita túneles** y los secretos quedan cifrados con la llave
de cada proyecto, como si se cargaran desde la app. Usa solo la librería
estándar de Python, sin venv.

Qué crea:
- La organización `Avila Tek`. Tu usuario queda como owner.
- Dos proyectos, `Tienda Online` y `Servicio de Pagos`. La API les genera
  `dev`/`stg`/`prd` y la llave de encriptación.
- Cinco variables por ambiente.
- Las credenciales de **Render y Vercel**, solo en el ambiente **Staging**
  (`stg`) de cada proyecto. Vercel queda con target `preview`.

Las credenciales de Render y Vercel **no van en el script**. Se leen de
`tek-secrets/api/scripts/.seed.env`, que git ignora (`*.env`):
```
RENDER_SERVICE_ID=srv-...
RENDER_API_TOKEN=rnd_...
VERCEL_PROJECT_ID=prj_...
VERCEL_TOKEN=vcp_...
VERCEL_TARGET=preview
```
**Tokens de sistema:** el script también crea 4 tokens de sistema, que se
ven en **Organización → Tokens**:

| Token | Scopes | Expira | Uso al crearlo |
|---|---|---|---|
| `lambda-rotation-xxxx` | `keys:rotate` | 365 d | No se usa (rotaría llaves) |
| `ci-deploy-reader-xxxx` | `projects:list`, `projects:read`, `environments:list` | 90 d | 3 llamadas |
| `auditoria-org-xxxx` | `org:read`, `projects:list` | 180 d | 2 llamadas |
| `monitoreo-inventario-xxxx` | `projects:list`, `projects:read`, `environments:list` | 30 d | 2 llamadas |

Los tres que se usan hacen llamadas de prueba a `/v1/service/*`, así que en
la app aparecen con su **último uso**. Los secretos se guardan en
`tek-secrets/api/scripts/.seed-tokens.env`, con permisos `600` e ignorado
por git; es la única copia. El de `lambda-rotation` sirve como
`rotation_api_token` (sección 5.1).

**Tokens de proyecto:** además, en **cada proyecto** se crean 4 tokens, que
se ven en la pestaña Tokens del proyecto:

| Token | Ambiente | Scopes | Expira | Llamadas de prueba |
|---|---|---|---|---|
| `backend-produccion-xxxx` | `prd` | `secrets:read` | 90 d | lee los secretos de prd |
| `backend-staging-xxxx` | `stg` | `secrets:read`, `environments:read` | 60 d | lee secretos y datos de stg |
| `dev-local-xxxx` | `dev` | `secrets:read` | 30 d | lee los secretos de dev |
| `ci-pipeline-xxxx` | todos | `projects:read`, `environments:list` | 180 d | lee el proyecto y lista sus ambientes |

Sus secretos van al mismo `.seed-tokens.env`, agrupados por proyecto.

```bash
python3 scripts/seed_via_api.py --no-project-tokens    # sin tokens de proyecto
python3 scripts/seed_via_api.py --no-system-tokens     # sin tokens de sistema
python3 scripts/seed_via_api.py --only-system-tokens   # solo tokens
```
Con `--only-system-tokens` no se crea nada más, pero tu usuario ya tiene
que ser owner o admin de alguna organización. Si da `Document failed
validation`, hay que relajar el validador de Mongo una vez (ver 5.1).

Si el archivo de credenciales no existe o le faltan las de un proveedor, el
script avisa y saltea ese proveedor. Las variables de entorno con el mismo nombre pisan al
archivo.

Para autenticarse usa tu token de GitHub, el mismo usuario que entra a la
app. La API lee tu email primario, así que el token de `gh` necesita el
scope `user:email`. Se agrega una sola vez:
```bash
gh auth refresh -h github.com -s user:email
```

Correrlo:
```bash
cd tek-secrets/api
python3 scripts/seed_via_api.py                         # contra https://api.secretsapi.online
python3 scripts/seed_via_api.py --org-name "Demo Defensa"
python3 scripts/seed_via_api.py -p "Portal Clientes" -p "API Inventario"   # nombres propios
python3 scripts/seed_via_api.py --api-url http://localhost:8000   # API local
python3 scripts/seed_via_api.py --help                  # todas las opciones con ejemplos
```

Todas las opciones:

| Flag | Qué hace | Default |
|---|---|---|
| `--org-name`, `-o NOMBRE` | Nombre de la organización | `Avila Tek` |
| `--project`, `-p NOMBRE` | Nombre de un proyecto; repetirlo para varios (`-p "A" -p "B"`). Toman en orden las plantillas de variables | `Tienda Online` y `Servicio de Pagos` |
| `--api-url URL` | URL de la API | `TEK_API_URL` o `https://api.secretsapi.online` |
| `--token TOKEN` | Token de GitHub (con scope `user:email`) | `GITHUB_TOKEN` o `gh auth token` |
| `--no-project-tokens` | No crea los 4 tokens de cada proyecto | se crean |
| `--no-system-tokens` | No crea los 4 tokens de sistema | se crean |
| `--only-system-tokens` | Solo crea los tokens de sistema, sin org ni proyectos | — |

`--no-system-tokens` y `--only-system-tokens` no se pueden combinar.

Ejemplo con todo personalizado:
```bash
python3 scripts/seed_via_api.py -o "Demo Defensa" \
  -p "Portal Clientes" -p "API Inventario" -p "App Móvil"
```

Los slugs llevan un sufijo aleatorio, así que se puede correr varias veces;
cada corrida crea una organización nueva. Para cambiar los proyectos o las
variables, editar la lista `PROJECTS` al inicio del script.

Si da `HTTP 401 Token inválido`, falta el scope `user:email` (ver arriba) o
el token venció (`gh auth login`).

---

## Con ambos túneles abiertos

Con QuestDB (9000) y MongoDB (27017) tunelizados a la vez se puede correr
la API local contra la infra de AWS. Ver `README.md` sección 8 para las
variables de `tek-secrets/api/.env` que hay que ajustar.
