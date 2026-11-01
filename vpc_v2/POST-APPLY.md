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
     python3 ../rotation/scripts/relax_service_token_validator.py \
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

## Con ambos túneles abiertos

Con QuestDB (9000) y MongoDB (27017) tunelizados a la vez se puede correr
la API local contra la infra de AWS. Ver `README.md` sección 8 para las
variables de `tek-secrets/api/.env` que hay que ajustar.
