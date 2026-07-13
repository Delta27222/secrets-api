# Infraestructura AWS (Terraform)

Este proyecto gestiona su infraestructura de AWS como código, en **módulos
independientes y separados**: cada uno vive en su propia carpeta, con su propio
`terraform/` y su propio estado. Así, aplicar o destruir uno **no afecta** al otro.

```
tek-secrets/
├── infra.sh      # Orquestador: crea/elimina ambos módulos
├── rotation/     # 1. Rotación automática de llaves (serverless)
└── logs/         # 2. Logs con QuestDB (EC2 + SQS)
```

---

## Script orquestador — `infra.sh`

Crea o elimina **todo** (logs + rotación) con un comando. Vive en la raíz del
backend (`tek-secrets/`).

```bash
cd tek-secrets

./infra.sh create [logs|rotation|all]   # build de los Lambdas + terraform apply
./infra.sh delete [logs|rotation|all]   # terraform destroy (pide confirmación)
```

| Comando | Qué hace |
|---------|----------|
| `./infra.sh create` | Crea **ambos** módulos (default `all`): empaqueta los Lambdas y hace `terraform init/apply` de `logs` y `rotation` |
| `./infra.sh create logs` | Solo logs: `build_consumer.sh` + `apply` |
| `./infra.sh create rotation` | Solo rotación: `build_master.sh` + `build_worker.sh` + `apply` |
| `./infra.sh delete all` | Destruye **ambos** (rotación primero, logs después) |
| `./infra.sh delete logs` | Solo logs (⚠️ borra el EBS → se pierden los logs) |

**Flags:**

| Flag | Efecto |
|------|--------|
| `logs` \| `rotation` \| `all` | Módulo objetivo (default `all`) |
| `-y`, `--yes` | En `delete`, no pide confirmación |
| `-h`, `--help` | Muestra la ayuda |

- **`create`** verifica que exista `terraform.tfvars` en cada módulo; si falta, avisa
  cómo crearlo desde el `.example` y no arranca.
- **`delete`** es destructivo: pide escribir `destroy` para confirmar (salvo `-y`).
- Al terminar, **recuerda hacer el build/deploy de la API en Render** para que tome
  los cambios de infraestructura (IPs, colas, Lambdas).

---

## 1. Rotación automática de llaves

📁 [`rotation/`](./rotation/README.md)

Subsistema **serverless** que rota la llave de cada proyecto y re-encripta sus
secretos cuando la llave cumple 90 días.

**Recursos:** EventBridge (cron) · 2 Lambdas (Maestro + Worker) · SQS + DLQ · IAM ·
CloudWatch. La criptografía la ejecuta la API (CSFLE), autenticada con un service
token de sistema (scope `keys:rotate`).

**Características:** efímero, por evento, **costo de centavos/mes**.

```bash
cd tek-secrets/rotation
./scripts/build_master.sh && ./scripts/build_worker.sh
cd terraform && terraform apply
```

Guía completa → [`rotation/README.md`](./rotation/README.md)

---

## 2. Logs (QuestDB)

📁 [`logs/`](./logs/README.md)

Infraestructura del **logging** con QuestDB: la base de datos de series de tiempo
donde la API registra las trazas de peticiones y servicios.

**Recursos:** EC2 con QuestDB (Docker) · volumen EBS persistente · Elastic IP (IP
fija) · Security Group · SQS + DLQ para ingesta asíncrona · **Lambda consumidora**
(SQS → `INSERT` en QuestDB por PG-wire 8812).

**Características:** **con estado y siempre encendido** → la EC2 es el costo real de
este módulo; hay que cuidar la **persistencia (EBS/snapshots)** y **restringir el
acceso** al puerto de QuestDB.

```bash
cd tek-secrets/logs
./scripts/build_consumer.sh                    # empaqueta la Lambda (zip)
cd terraform
cp terraform.tfvars.example terraform.tfvars   # editar
terraform init && terraform apply
```

Guía completa → [`logs/README.md`](./logs/README.md)

---

## Diferencias clave entre ambos módulos

| | Rotación | Logs (QuestDB) |
|---|----------|----------------|
| Modelo | Serverless (Lambda) | Con estado (EC2) |
| Ejecución | Por evento (segundos) | 24/7 encendido |
| Datos | No persiste | **Persistente (EBS)** |
| `terraform destroy` | Inofensivo | ⚠️ Cuidar backup del volumen |
| Costo | ~centavos/mes | Dominado por la EC2 |

> Cada módulo se aplica y destruye por separado desde su propia carpeta `terraform/`.
> No comparten `terraform.tfstate`.
