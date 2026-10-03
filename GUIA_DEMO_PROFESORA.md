# Guía de demostración — Tek Secrets

Guion para mostrar **en la plataforma funcionando** que cada objetivo de la
tesis está cumplido. No se muestra código: se muestran pantallas, resultados
y evidencia (la app, la consola de AWS, MongoDB y QuestDB).

- **App:** https://app.secretsapi.online
- **API:** https://api.secretsapi.online · Swagger en https://api.secretsapi.online/docs
- **Región AWS:** `us-east-1`

---

## Índice

0. [Preparación (antes de la presentación)](#0-preparación-antes-de-la-presentación)
1. [Mapa: objetivo → qué se muestra](#1-mapa-objetivo--qué-se-muestra)
2. [Objetivo 1 — Autenticación con autorización delegada](#objetivo-1--autenticación-con-autorización-delegada)
3. [Objetivo 2 — Generación, rotación y versionado de llaves](#objetivo-2--generación-rotación-y-versionado-de-llaves)
4. [Objetivo 3 — Tokens de acceso para servicios](#objetivo-3--tokens-de-acceso-para-servicios)
5. [Objetivo 4 — SDK oficial para Node.js](#objetivo-4--sdk-oficial-para-nodejs)
6. [Objetivo 5 — Arquitectura de red segmentada en AWS](#objetivo-5--arquitectura-de-red-segmentada-y-segura-en-aws)
7. [Objetivo 6 — Servicio de rotación de llaves criptográficas](#objetivo-6--servicio-de-rotación-de-llaves-criptográficas)
8. [Aporte tecnológico — Logs de auditoría basados en eventos](#aporte-tecnológico--arquitectura-basada-en-eventos-para-logs-de-auditoría)
9. [Aporte funcional — Gobernanza centralizada](#aporte-funcional--gobernanza-centralizada-automatizada-y-auditable)
10. [Orden sugerido de la demo (~25 min)](#10-orden-sugerido-de-la-demo-25-min)
11. [Plan B si algo falla](#11-plan-b-si-algo-falla)
12. [Checklist final](#12-checklist-final)

---

## 0. Preparación (antes de la presentación)

### 0.1 Verificar que todo está arriba

```bash
curl https://api.secretsapi.online/health        # debe dar {"status":"ok"}
```
Y abrir https://app.secretsapi.online → debe cargar la pantalla de login.

Si la API da 503, ver [Plan B](#11-plan-b-si-algo-falla).

### 0.2 Datos de prueba en la plataforma

Tener listo **un proyecto de demo** con 3 ambientes y variables cargadas:

| Ambiente | Contenido sugerido |
|---|---|
| `development` | ~12 variables con valores de dev (`localhost`, `sk_test_dev_…`, `LOG_LEVEL=debug`) |
| `staging` | las mismas keys con valores de staging (`staging-*.internal`, `LOG_LEVEL=info`) |
| `production` | las mismas keys con valores de prod (`sk_live_…`, `sslmode=require`, `LOG_LEVEL=warning`) |

Que las **mismas keys tengan valores distintos por ambiente** es lo que hace
visible la separación de ambientes durante la demo.

Anotar el **ID del proyecto** y el **ID de cada ambiente** (se ven en la app).

### 0.3 Tokens — cargarlos como variables, NO en pantalla

Los tokens ya creados en la plataforma:

| # | Nombre | Tipo | Scope / alcance |
|---|---|---|---|
| 1 | Solo staging | Service token (proyecto) | `secrets:read`, limitado al ambiente staging |
| 2 | Todos | Service token (proyecto) | `secrets:read`, todos los ambientes |
| 3 | Rotación de servicios | Token de sistema (organización) | `keys:rotate` |

En la terminal de la demo, **antes** de compartir pantalla:

```bash
export TOKEN_STAGING='tok_...'      # token 1
export TOKEN_TODOS='tok_...'        # token 2
export TOKEN_ROTACION='tok_...'     # token 3
export PROJECT_ID='...'
export ENV_STAGING='...'
export ENV_PROD='...'
export API=https://api.secretsapi.online
```

> ⚠️ Nunca mostrar un `tok_...` completo en pantalla ni en las diapositivas.
> Si se llega a mostrar, revocarlo después desde la app (eso además sirve
> como demo del objetivo 3).

### 0.4 Rotación automática configurada

El token 3 debe estar cargado en la Lambda worker. En
`vpc_v2/terraform/terraform.tfvars`:

```hcl
rotation_api_token = "tok_..."   # token 3
```
y luego `terraform apply` (solo cambia la configuración de la Lambda
`rotation-worker`). Sin esto, la rotación automática diaria recibe 401.

### 0.5 Abrir los túneles a las bases de datos (2 terminales extra)

**Terminal QuestDB** (consola web):
```bash
echo "🔗 Consola QuestDB → http://localhost:19000"
(sleep 5; open http://localhost:19000) &
aws ssm start-session --region us-east-1 \
  --target i-038e5b90836d2359e \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["9000"],"localPortNumber":["19000"]}'
```
> Se usa el puerto local 19000 para evitar el `VersionError` del navegador
> (datos guardados de un QuestDB local en el 9000).

**Terminal Mongo** (túnel):
```bash
aws ssm start-session --region us-east-1 \
  --target i-0f75d0efbb379c21d \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["27017"],"localPortNumber":["27017"]}'
```

**Terminal Mongo** (cliente — abrir Compass con la URL, no mostrar la URL en pantalla):
```bash
TFVARS=/Users/delta27222/Desktop/tesis/tek-secrets/vpc_v2/terraform/terraform.tfvars
RAW=$(grep '^mongodb_admin_password' "$TFVARS" | cut -d'"' -f2)
ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote_plus(sys.argv[1]))" "$RAW")
mongosh "mongodb://admin:$ENC@localhost:27017/secrets-27222?authSource=admin&directConnection=true"
```

> Las sesiones SSM se cierran tras ~20 min sin uso. Abrirlas justo antes de
> la presentación y, si se cierran, volver a correr el comando.

### 0.6 Pestañas del navegador listas

1. https://app.secretsapi.online (sesión **cerrada**, para mostrar el login)
2. https://app.secretsapi.online/sdk-demo
3. https://api.secretsapi.online/docs
4. http://localhost:19000 (QuestDB)
5. Consola AWS → **VPC → Your VPCs → `tek-secrets-v2` → Resource map**
6. Consola AWS → **EC2 → Instances**
7. Consola AWS → **EventBridge → Rules** y **Lambda → Functions**
8. Consola AWS → **SQS → Queues**
9. GitHub → **Settings → Developer settings → OAuth Apps** (la app del proyecto)

---

## 1. Mapa: objetivo → qué se muestra

| # | Objetivo | Evidencia principal en vivo | Estado |
|---|---|---|---|
| 1 | Autenticación con autorización delegada | Login con GitHub → sesión → acceso por roles | ✅ |
| 2 | Generación, rotación y versionado de llaves | Rotar llave → nueva versión en Mongo + auditoría en QuestDB → secretos siguen legibles | ✅ |
| 3 | Tokens de acceso para servicios | Crear token con scopes → usarlo → 403 fuera de su alcance → revocar → 401 | ✅ |
| 4 | SDK oficial Node.js | Página `/sdk-demo` + lectura en vivo de variables con el SDK | ✅ |
| 5 | Red segmentada y segura en AWS | Resource map de la VPC, subredes por zona, SGs, sin IPs públicas, HTTPS forzado, acceso solo por SSM | ✅ |
| 6 | Servicio de rotación de llaves | EventBridge diario → Lambda maestra → SQS → Lambda worker → API | ✅ |
| AT | Logs de auditoría basados en eventos | Acción en la app → SQS → Lambda → QuestDB → pestaña Logs | ✅ |
| AF | Gobernanza centralizada | Un solo lugar para editar → sync a Render/Vercel + SDK + log de todo | ✅ |

---

## Objetivo 1 — Autenticación con autorización delegada

> *Diseñar e implementar un sistema de autenticación que permita a los
> usuarios iniciar sesión de manera segura mediante la autorización delegada.*

**Idea a transmitir:** la plataforma **nunca ve ni guarda contraseñas**. El
usuario se autentica en GitHub (OAuth 2.0) y GitHub le confirma a la
plataforma quién es. Luego la API emite su propio JWT para las llamadas.

### Pasos

1. Abrir https://app.secretsapi.online con la sesión cerrada → redirige a la
   pantalla de **inicio de sesión**.
2. Click en **Iniciar sesión con GitHub** → se abre la pantalla de **GitHub**
   pidiendo autorizar la aplicación.
   - Señalar la URL del navegador: estamos en `github.com`, no en la
     plataforma. Ahí está la delegación.
3. Autorizar → vuelve a la app ya autenticado, con nombre y avatar de GitHub.
4. Mostrar en GitHub → **OAuth Apps** la app registrada:
   - Callback: `https://app.secretsapi.online/api/auth/callback/github`
   - Solo HTTPS.
5. **Control de acceso después del login:** entrar a una organización →
   pestaña **Miembros**. Mostrar los roles (owner / admin / miembro) y que
   ciertas acciones (crear tokens de sistema, sincronizar con Render/Vercel)
   solo están disponibles para admins.
6. **Prueba negativa (opcional):** llamar a la API sin sesión:
   ```bash
   curl -i $API/v1/me
   ```
   → la API rechaza la petición (`"GitHub token is required"`). Sin
   autenticación no hay acceso a los datos del usuario.

### Qué decir
- OAuth 2.0 con GitHub como proveedor de identidad (NextAuth en el front).
- Sesión en cookie segura (`httpOnly`); la API valida un JWT en cada request.
- Autenticación (quién eres) separada de autorización (qué puedes hacer: roles por organización y proyecto).

---

## Objetivo 2 — Generación, rotación y versionado de llaves

> *Diseñar e implementar un mecanismo automatizado para la generación,
> rotación y versionado de llaves de encriptación.*

**Idea a transmitir:** cada proyecto tiene **su propia llave**. Los secretos
se guardan **cifrados** en MongoDB. La llave se puede rotar, cada rotación
crea una **nueva versión** y los secretos se vuelven a cifrar sin que el
usuario note nada.

### Pasos

1. **Los secretos NO están en texto plano en la base.** En la terminal de
   `mongosh`:
   ```js
   db.environments.findOne({}, { name: 1, secrets: 1 })
   ```
   → los valores aparecen **cifrados** (ilegibles). En cambio, en la app
   (pestaña **Ver Variables**) se ven en claro para un usuario autorizado.
2. **Versiones de llaves existentes:**
   ```js
   db.encryption_key_versions.countDocuments()
   db.encryption_key_versions.find({}, { _id: 0, project_id: 1, version: 1, status: 1, created_at: 1 }).sort({ _id: -1 }).limit(5)
   ```
   > No mostrar el material de la llave: usar siempre la proyección. Si
   > algún campo tiene otro nombre, ajustar la proyección.
3. **Rotar la llave del proyecto en vivo:**
   ```bash
   curl -s -X POST -H "Authorization: Bearer $TOKEN_ROTACION" \
     $API/v1/internal/projects/$PROJECT_ID/rotate-encryption
   ```
4. Repetir la consulta del paso 2 → aparece **una versión nueva** para el
   proyecto, y la anterior queda registrada (versionado).
5. Volver a la app → **Ver Variables** del proyecto → los valores siguen
   **idénticos**. Los secretos se volvieron a cifrar con la llave nueva, sin
   interrupción.
6. **Auditoría de la rotación** en QuestDB (http://localhost:19000):
   ```sql
   SELECT * FROM encryption_key_audit LIMIT -10;
   ```
   → aparece el evento de rotación recién hecho, con fecha y proyecto.

### Qué decir
- Cifrado a nivel de campo (CSFLE de MongoDB) con una llave por proyecto.
- Las credenciales de Render/Vercel guardadas en un ambiente usan **la misma
  llave**: rotarla también protege esas credenciales.
- Cada rotación queda versionada y auditada.

---

## Objetivo 3 — Tokens de acceso para servicios

> *Diseñar e implementar un sistema de generación y administración de tokens
> de acceso para servicios, que permita la integración programática de
> sistemas externos.*

**Idea a transmitir:** un sistema externo (un servidor, un pipeline de CI) no
usa la cuenta de una persona. Usa un **service token** con permisos mínimos
(scopes), acotado a un proyecto o ambiente, que se puede revocar.

### Pasos

1. App → proyecto de demo → pestaña **Service Tokens**.
2. **Crear token en vivo** (por ejemplo, "Demo profesora"):
   - Mostrar el catálogo de **scopes** con su nivel de riesgo
     (`secrets:read` alto, `projects:read` bajo, etc.).
   - Elegir solo `secrets:read` y limitarlo a **staging**.
   - Mostrar que el `tok_...` se ve **una sola vez**. Después solo se guarda
     su hash.
3. Mostrar la lista de tokens: nombre, scopes, ambientes, fecha de creación y
   último uso.
4. **Usar el token** (con los tokens precargados en la terminal):
   ```bash
   # Token "Solo staging" leyendo staging → 200, devuelve las variables
   curl -s "$API/v1/service/secrets?environment=$ENV_STAGING" \
     -H "Authorization: Bearer $TOKEN_STAGING"

   # El mismo token intentando leer producción → 403
   curl -i "$API/v1/service/secrets?environment=$ENV_PROD" \
     -H "Authorization: Bearer $TOKEN_STAGING"

   # Token "Todos" leyendo producción → 200
   curl -s "$API/v1/service/secrets?environment=$ENV_PROD" \
     -H "Authorization: Bearer $TOKEN_TODOS"
   ```
   El **403** del segundo comando es la evidencia de mínimo privilegio.
5. **Revocar** el token creado en el paso 2 desde la app → usarlo de nuevo →
   **401**. El acceso se corta al instante.
6. **Tokens de sistema** (nivel organización): Organización → pestaña
   **Tokens**. Mostrar el token "Rotación de servicios" con scope
   `keys:rotate`, que es el que usa la Lambda de rotación (objetivo 6). Solo
   owners y admins pueden crearlos.

### Qué decir
- Dos niveles: **service tokens** (por proyecto, para apps) y **tokens de
  sistema** (por organización, para procesos internos).
- Scopes y alcance por ambiente: mínimo privilegio.
- Ciclo de vida completo: crear → usar → rotar → revocar.

---

## Objetivo 4 — SDK oficial para Node.js

> *Diseñar e implementar un SDK oficial para aplicaciones desarrolladas en
> Node.js, que facilite la consulta de variables de entorno en tiempo de
> ejecución.*

**Idea a transmitir:** una app Node.js ya no necesita un `.env` copiado a
mano. Con un token y el ID del ambiente, **lee sus variables en tiempo de
ejecución** desde Tek Secrets.

### Pasos

1. App → https://app.secretsapi.online/sdk-demo. Recorrer las pestañas:
   - **Instalación:** paquete privado `@secrets-27222633/sdk` en GitHub Packages.
   - **Uso / Ejemplos:** `createClient()`, `getSecrets()`, `getSecret()`,
     `getSecretOrDefault()`, `load()`.
   - **Caché:** TTL de 30 s, reintentos y "stale-on-error" (si la API cae, se
     sigue sirviendo el último valor conocido).
   - **Referencia:** errores tipados (`AuthenticationError`,
     `PermissionError`, `NotFoundError`…).
2. **Demo en vivo del cambio sin redeploy:**
   1. Con el SDK leyendo staging, mostrar el valor de una variable, por
      ejemplo `FEATURE_FLAGS`.
   2. En la app, editar esa variable en **staging** (pestaña **Editar Variables**).
   3. Volver a leer a los ~30 s (cuando vence la caché) → el SDK devuelve el
      **valor nuevo**, sin tocar ni redesplegar la app consumidora.
3. **Configuración que necesita una app** (mostrarla como tabla, no como código):

   | Variable | Para qué |
   |---|---|
   | `TEK_SECRETS_TOKEN` | service token del ambiente |
   | `TEK_SECRETS_ENVIRONMENT` | ID del ambiente |
   | `TEK_SECRETS_API_URL` | `https://api.secretsapi.online` |

   Cambiando solo esas 3 variables, la **misma app** corre en dev, staging o
   prod con sus propios valores.

### Qué decir
- Cero dependencias en runtime (usa el `fetch` nativo de Node 18+).
- Resiliencia: caché, reintentos con backoff, stale-on-error.
- Los permisos los controla el token (objetivo 3): el SDK no puede leer más de
  lo que su token permite.

---

## Objetivo 5 — Arquitectura de red segmentada y segura en AWS

> *Diseñar e implementar una arquitectura de red segmentada y segura en AWS,
> integrando mecanismos de control de acceso perimetral y aislamiento de
> recursos para garantizar la protección de la plataforma.*

**Idea a transmitir:** la red tiene **3 zonas** con distinto nivel de
exposición, repartidas en **2 zonas de disponibilidad**. Desde internet solo
se llega al balanceador. Las bases de datos no tienen ni IP pública ni salida
a internet.

```
Internet ──► ALB (subredes públicas, HTTPS) ──► ECS API / Front (subredes privadas de apps)
                                                     │
                                                     ▼
                                MongoDB RS + QuestDB (subredes privadas de datos, sin internet)
```

### Pasos (consola de AWS)

1. **VPC → `tek-secrets-v2` → Resource map:** se ven la VPC `10.0.0.0/16` y
   sus subredes por zona:

   | Zona | Subredes | Qué corre | Salida a internet |
   |---|---|---|---|
   | Pública | `10.0.1.0/24` (a), `10.0.2.0/24` (b) | ALB, NAT Gateway | Sí (Internet Gateway) |
   | Privada apps | `10.0.3.0/24` (a), `10.0.4.0/24` (b) | ECS (API, front), Lambdas, arbiter | Solo saliente, vía NAT |
   | Privada datos | `10.0.5.0/24` (a), `10.0.6.0/24` (b) | MongoDB primary/secondary, QuestDB | **No** |

2. **EC2 → Instances:** las 4 instancias de datos (Mongo primary, secondary y
   arbiter, y QuestDB) tienen la columna **Public IPv4 vacía**. No son
   alcanzables desde internet.
3. **Security Groups** (control de acceso perimetral e interno). Abrir las
   reglas de entrada:
   - `alb`: solo 80/443 desde internet.
   - `ecs`: solo desde el SG del ALB.
   - `mongodb`: 27017 **solo** desde los SG de ECS y Lambda (y entre los nodos
     del replica set).
   - `questdb`: solo desde ECS y Lambda.

   Cada capa solo acepta tráfico de la capa anterior: **mínimo privilegio en red**.
4. **HTTPS forzado:**
   ```bash
   curl -sI http://api.secretsapi.online/health | head -3   # → 301 hacia https
   curl -s https://api.secretsapi.online/health             # → {"status":"ok"}
   ```
   Mostrar el certificado ACM wildcard `*.secretsapi.online` (candado del
   navegador).
5. **Ruteo por dominio en el ALB:** EC2 → Load Balancers → listener 443 →
   reglas: `app.*` → front y `api.*` → API.
6. **Las bases no se alcanzan desde afuera:**
   ```bash
   nc -vz -G 3 10.0.5.10 27017    # falla: IP privada, inalcanzable desde internet
   ```
   La única forma de entrar es un **túnel SSM** autenticado con IAM (como el
   que está abierto para QuestDB). Sin SSH, sin puertos abiertos y sin bastión.
7. **VPC Endpoints** (VPC → Endpoints): ECR, S3, SSM, Secrets Manager, SQS y
   CloudWatch Logs. El tráfico hacia esos servicios de AWS **no sale a
   internet**.
8. **Secretos de infraestructura en Secrets Manager:** la URL de Mongo, la
   `SECRET_KEY` y la llave maestra CSFLE no están en el código ni en las
   imágenes. ECS las inyecta al contenedor al arrancar.
9. **Alta disponibilidad:** MongoDB en replica set (primary en zona a,
   secondary en zona b, arbiter en una tercera subred). Si cae una zona, el
   replica set elige un nuevo primary.
10. **Backups:** AWS Backup → plan `databases` sobre los volúmenes de datos.
11. **Deploy sin credenciales guardadas:** GitHub Actions asume un rol IAM vía
    **OIDC** (sin access keys de larga vida).

### Qué decir
- Defensa en profundidad: perímetro (ALB + HTTPS) → segmentación (subredes) →
  micro-segmentación (security groups) → identidad (IAM/SSM).
- Toda la infraestructura es código (Terraform) y se levanta con un solo
  `terraform apply`.

---

## Objetivo 6 — Servicio de rotación de llaves criptográficas

> *Diseñar e implementar un servicio de rotación de llaves criptográficas que
> mitigue la exposición prolongada de credenciales sensibles.*

**Idea a transmitir:** ninguna llave vive para siempre. Un proceso
**automático y diario** detecta las llaves con más de 90 días y las rota sin
intervención humana.

```
EventBridge (00:00 UTC) → λ rotation-master → lee Mongo → SQS rotation-queue
   → λ rotation-worker → POST /v1/internal/projects/{id}/rotate-encryption → API
                            (falla 3 veces → DLQ)
```

### Pasos (consola de AWS)

1. **EventBridge → Rules → `tek-secrets-v2-rotation-schedule`:** cron
   `cron(0 0 * * ? *)`, todos los días a medianoche UTC.
2. **Lambda → `tek-secrets-v2-rotation-master`:** variable
   `ROTATION_INTERVAL_DAYS = 90`. Revisa qué proyectos tienen una llave vencida.
3. **SQS → `tek-secrets-v2-rotation-queue`** y su **DLQ** (los mensajes que
   fallan 3 veces van a la cola de fallidos, para no perder rotaciones).
4. **Lambda → `tek-secrets-v2-rotation-worker`:** solo hace la llamada HTTP a
   la API con el token de sistema `keys:rotate` (objetivo 3). La criptografía
   la hace la API, nunca la Lambda.
5. **Ejecutarlo en vivo** (sin esperar al cron):
   ```bash
   aws lambda invoke --region us-east-1 \
     --function-name tek-secrets-v2-rotation-master /dev/stdout
   ```
   Luego, CloudWatch → Log groups → `/aws/lambda/tek-secrets-v2-rotation-master`
   y `/aws/lambda/tek-secrets-v2-rotation-worker` → se ve el chequeo y, si
   había llaves vencidas, el encolado y la rotación.
   > Para mostrar una rotación real en vivo, poner antes
   > `rotation_interval_days = 0` en `terraform.tfvars` y aplicar. Volver a
   > `90` después de la demo.
6. **Alarmas:** CloudWatch → Alarms → errores de las Lambdas de rotación.

### Qué decir
- Rotación periódica: reduce la ventana de exposición si una llave se filtra.
- Desacoplado con SQS: si la API está caída, los mensajes esperan y se
  reintentan. Nada se pierde (DLQ).
- Las Lambdas no manejan material criptográfico: separación de responsabilidades.

---

## Aporte tecnológico — Arquitectura basada en eventos para logs de auditoría

> *Diseñar e implementar una arquitectura basada en eventos para el registro y
> almacenamiento estructurado de logs de auditoría.*

**Idea a transmitir:** cada acción relevante genera un **evento**. El evento
viaja por una cola y se guarda estructurado en una base de series de tiempo.
La API no espera a que el log se escriba: si el sistema de logs se cae, la
plataforma sigue funcionando.

```
Acción del usuario → API publica evento → SQS logs-queue → λ logs-consumer → QuestDB → pestaña Logs
```

### Pasos

1. **Generar un evento en vivo:** en la app, editar una variable de staging (o
   crear o revocar un token).
2. **SQS → `tek-secrets-v2-logs-queue` → Monitoring:** se ve el mensaje que
   entró y salió de la cola.
3. **Lambda → `tek-secrets-v2-logs-consumer` → Monitor → CloudWatch logs:**
   se ve la invocación que procesó el evento.
4. **QuestDB** (http://localhost:19000):
   ```sql
   SELECT * FROM Logs LIMIT -10;          -- últimas acciones de auditoría
   SELECT * FROM system_logs LIMIT -10;   -- eventos internos de la API
   ```
   → aparece la acción del paso 1 con usuario, acción, recurso y fecha.
5. **En la plataforma:** proyecto → pestaña **Logs**, y Organización →
   pestaña **Logs** (filtros **INFO / ERROR**). Mostrar los filtros por
   usuario, acción y tipo de recurso. La misma acción del paso 1 aparece en
   la UI.

### Qué decir
- **Asíncrono y desacoplado:** la API publica en SQS y sigue. El log no frena
  la respuesta al usuario.
- **Resiliente:** si QuestDB o la Lambda fallan, los eventos esperan en la
  cola (con DLQ).
- **Estructurado:** QuestDB (series de tiempo) permite consultar por rango de
  fechas, usuario o acción con SQL.
- Tres tablas: `Logs` (auditoría de usuario), `system_logs` (API) y
  `encryption_key_audit` (rotaciones).

---

## Aporte funcional — Gobernanza centralizada, automatizada y auditable

> *Rediseñar el modelo operativo de gestión de variables de entorno: de un
> esquema manual y descentralizado a un ecosistema centralizado, automatizado
> y auditable.*

**Idea a transmitir (antes vs. después):**

| Antes (manual, descentralizado) | Después (Tek Secrets) |
|---|---|
| `.env` copiados por Slack o por correo | Un solo lugar, cifrado, con permisos |
| Variables pegadas a mano en Render y en Vercel | **Sync con un click** desde la plataforma |
| Cada app con su `.env` desactualizado | Las apps leen en runtime con el **SDK** |
| Nadie sabe quién cambió qué | **Log de auditoría** de cada acción |
| Llaves y credenciales eternas | **Rotación automática** |

La demo de este aporte junta las tres piezas que faltaban:

### A. Subida de credenciales directo a Render y Vercel

1. App → proyecto → ambiente (por ejemplo `production`) → tarjeta del
   ambiente → formulario **Render**: pegar el **Service ID** y el **API key**
   de Render → guardar.
   - Las credenciales de Render se guardan **cifradas** con la llave del
     proyecto (se puede mostrar en `mongosh`, igual que en el objetivo 2).
2. Click en **Sincronizar** → abrir el dashboard de **Render → servicio →
   Environment**: aparecen **todas** las variables del ambiente.
3. Lo mismo con **Vercel**: formulario → elegir proyecto y target
   (production / preview / development) → confirmar → **Sincronizar** → abrir
   Vercel → **Settings → Environment Variables**: ahí están.
4. **Cambio centralizado:** editar una variable en Tek Secrets → sincronizar →
   el valor nuevo aparece en Render y en Vercel. Nunca se tocó el dashboard de
   Render ni el de Vercel a mano.

> Render reemplaza el set completo de variables (PUT). Vercel hace upsert
> (solo agrega o actualiza lo enviado). Si preguntan, esa es la diferencia.

### B. SDK

La misma variable editada en el paso A.4 la lee una app Node.js con el SDK
**sin redeploy** (ver [objetivo 4](#objetivo-4--sdk-oficial-para-nodejs), paso 2).

### C. Log

Todo lo anterior (guardar credenciales de Render, sincronizar, editar la
variable) aparece en la pestaña **Logs** y en QuestDB (ver
[aporte tecnológico](#aporte-tecnológico--arquitectura-basada-en-eventos-para-logs-de-auditoría)).

**Cierre del aporte:** un cambio hecho **una vez**, en **un lugar**, llega a
Render, Vercel y las apps con SDK, y queda **auditado**.

---

## 10. Orden sugerido de la demo (~25 min)

Un recorrido continuo que pasa por todos los objetivos sin saltar de un lado
a otro:

| Min | Paso | Objetivos |
|---|---|---|
| 0–3 | Diagrama de arquitectura + Resource map de la VPC | 5 |
| 3–6 | Login con GitHub, organización, roles | 1 |
| 6–9 | Proyecto con 3 ambientes, mismas keys y valores distintos; secretos cifrados en Mongo | 2, AF |
| 9–13 | Crear service token → curl 200 / 403 → revocar → 401 | 3 |
| 13–16 | `/sdk-demo` + cambio de variable leído en vivo por el SDK | 4, AF |
| 16–19 | Sync a Render y Vercel con un click | AF |
| 19–22 | Rotación: curl manual + EventBridge/Lambdas/SQS + nueva versión en Mongo + auditoría en QuestDB | 2, 6 |
| 22–25 | Pestaña Logs + QuestDB: todo lo hecho en la demo quedó registrado | AT, AF |

El cierre en **Logs** funciona bien: todo lo que se hizo durante la demo
aparece registrado, y eso demuestra a la vez el aporte tecnológico y el
funcional.

---

## 11. Plan B si algo falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `api.../health` da **503** | La task de ECS de la API no está corriendo | `aws ecs update-service --region us-east-1 --cluster tek-secrets-v2-cluster --service tek-secrets-v2-api-service --force-new-deployment` y esperar 2–3 min |
| `app...` da **503** | La task del front no está corriendo o no hay imagen | Re-run del workflow de GitHub Actions del front, o forzar deploy de `tek-secrets-v2-front-service` |
| QuestDB: `VersionError ... (20) ... (30)` | Datos guardados en el navegador de otro QuestDB | Usar el puerto local 19000, o DevTools → Application → Clear site data |
| `ECONNREFUSED 127.0.0.1:27017` | El túnel SSM se cerró | Volver a correr el comando del túnel |
| `mongosh`: `Authentication failed` con URL `admin:@...` | No se leyó `terraform.tfvars` | Usar la versión con ruta absoluta (sección 0.5) |
| curl con token → **401** | Token revocado o mal copiado | Revisar `echo ${TOKEN_STAGING:0:8}` y la lista de tokens en la app |
| Rotación automática → 401 en los logs de la worker | `rotation_api_token` sigue con el placeholder | Sección 0.4 |
| Login con GitHub falla en el callback | Callback de la OAuth App mal configurado | Debe ser `https://app.secretsapi.online/api/auth/callback/github` |

**Respaldo sin conexión:** tener capturas de pantalla de cada paso, por si
falla internet en la sala.

---

## 12. Checklist final

Antes de empezar:

- [ ] `curl https://api.secretsapi.online/health` → `{"status":"ok"}`
- [ ] https://app.secretsapi.online carga el login
- [ ] Proyecto de demo con dev / staging / prod y variables cargadas
- [ ] IDs de proyecto y ambientes anotados
- [ ] Tokens exportados en la terminal (no visibles)
- [ ] `rotation_api_token` aplicado en Terraform
- [ ] Túnel QuestDB abierto (puerto 19000) y consola cargando
- [ ] Túnel Mongo abierto y `mongosh` conectado
- [ ] Credenciales de Render y Vercel a mano para el formulario de sync
- [ ] Dashboards de Render y Vercel abiertos (para mostrar el resultado del sync)
- [ ] Pestañas de la consola AWS abiertas (VPC, EC2, EventBridge, Lambda, SQS)
- [ ] Capturas de respaldo

Durante la demo, por objetivo:

- [ ] **1** Login con GitHub, roles y rechazo sin sesión
- [ ] **2** Secretos cifrados en Mongo, rotación con versión nueva y valores intactos
- [ ] **3** Token creado, 200 / 403 / revocado → 401
- [ ] **4** `/sdk-demo` y cambio leído en vivo
- [ ] **5** Subredes, SGs, sin IPs públicas, HTTPS forzado, solo SSM
- [ ] **6** EventBridge → Lambdas → SQS, invocación manual
- [ ] **AT** Acción → SQS → Lambda → QuestDB → pestaña Logs
- [ ] **AF** Sync a Render y Vercel + SDK + log del cambio
