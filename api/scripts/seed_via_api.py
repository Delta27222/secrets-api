#!/usr/bin/env python3
"""
Carga datos de demo en Tek Secrets a través de la API (no toca MongoDB directo).

Crea:
  1. Una organización (el usuario del token queda como owner).
  2. Dos proyectos. La API genera sola los ambientes dev / stg / prd y la
     llave de encriptación de cada proyecto.
  3. Variables de entorno en cada ambiente. La API las cifra con la llave
     del proyecto, igual que si se cargaran desde la app.
  4. Credenciales de Render y Vercel, solo en el ambiente Staging (stg) de
     cada proyecto.
  5. Cuatro tokens de sistema (SYSTEM_TOKENS) con distintos scopes. Tres se
     usan con un par de llamadas de prueba a /v1/service/* para que aparezca
     su último uso; el de keys:rotate no se usa (rotaría llaves). Los secretos
     se guardan en `scripts/.seed-tokens.env` (ignorado por git).
     `--no-system-tokens` los omite; `--only-system-tokens` crea solo esos.
  6. Cuatro tokens por proyecto (PROJECT_TOKENS): backend-produccion (prd),
     backend-staging (stg), dev-local (dev) y ci-pipeline (todos). Cada uno
     hace llamadas de prueba (leer secretos de su ambiente, etc.) para que
     aparezca su último uso. `--no-project-tokens` los omite.

Credenciales de Render/Vercel: se leen de `scripts/.seed.env` (ignorado por
git, formato KEY=VALUE) o de variables de entorno con el mismo nombre. Las
variables de entorno pisan al archivo:

    RENDER_SERVICE_ID=srv-...
    RENDER_API_TOKEN=rnd_...
    VERCEL_PROJECT_ID=prj_...
    VERCEL_TOKEN=vcp_...
    VERCEL_TARGET=preview        # opcional, separado por comas

Si faltan las de un proveedor, ese proveedor se saltea con un aviso.

Autenticación: la API valida un token de GitHub (header X-GitHub-Token) y
necesita leer el email primario de la cuenta, así que el token debe tener
el scope `user:email`. Con el token de `gh`:

    gh auth refresh -h github.com -s user:email   # una sola vez

Uso (solo librería estándar, no hace falta venv):

    python3 scripts/seed_via_api.py
    python3 scripts/seed_via_api.py --org-name "Demo Defensa"
    python3 scripts/seed_via_api.py -p "Portal Clientes" -p "API Inventario"
    python3 scripts/seed_via_api.py -p "Un Solo Proyecto"
    python3 scripts/seed_via_api.py --api-url http://localhost:8000

El token se toma de --token, de la variable GITHUB_TOKEN o de `gh auth token`,
en ese orden. Los slugs llevan un sufijo aleatorio para poder correrlo varias
veces sin choques.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.request

DEFAULT_API_URL = "https://api.secretsapi.online"
SEED_ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".seed.env")
INTEGRATIONS_ENV_SLUG = "stg"

# Variables por proyecto y ambiente. Los valores son de demo, no reales.
PROJECTS: list[dict] = [
    {
        "name": "Tienda Online",
        # El front agrupa por estas dos claves: "folder" → vista "Por Proyecto",
        # "team" → vista "Por Equipo". Sin ellas el proyecto cae en "Sin clasificar".
        "tags": {"folder": "E-commerce", "team": "Equipo Web"},
        "environments": {
            "dev": {
                "NODE_ENV": "development",
                "DATABASE_URL": "postgres://tienda:dev-pass@localhost:5432/tienda_dev",
                "STRIPE_SECRET_KEY": "sk_test_demo_dev_51Hx",
                "NEXT_PUBLIC_API_URL": "http://localhost:8080",
                "LOG_LEVEL": "debug",
            },
            "stg": {
                "NODE_ENV": "staging",
                "DATABASE_URL": "postgres://tienda:stg-pass@stg-db.internal:5432/tienda",
                "STRIPE_SECRET_KEY": "sk_test_demo_stg_51Hx",
                "NEXT_PUBLIC_API_URL": "https://stg-api.tienda.example",
                "LOG_LEVEL": "info",
            },
            "prd": {
                "NODE_ENV": "production",
                "DATABASE_URL": "postgres://tienda:prd-pass@prd-db.internal:5432/tienda",
                "STRIPE_SECRET_KEY": "sk_live_demo_prd_51Hx",
                "NEXT_PUBLIC_API_URL": "https://api.tienda.example",
                "LOG_LEVEL": "warn",
            },
        },
    },
    {
        "name": "Servicio de Pagos",
        "tags": {"folder": "Fintech", "team": "Equipo Pagos"},
        "environments": {
            "dev": {
                "PORT": "3000",
                "REDIS_URL": "redis://localhost:6379/0",
                "JWT_SECRET": "dev-jwt-secret-demo",
                "PAYPAL_CLIENT_ID": "demo-paypal-sandbox-dev",
                "FEATURE_REFUNDS": "true",
            },
            "stg": {
                "PORT": "3000",
                "REDIS_URL": "redis://stg-redis.internal:6379/0",
                "JWT_SECRET": "stg-jwt-secret-demo",
                "PAYPAL_CLIENT_ID": "demo-paypal-sandbox-stg",
                "FEATURE_REFUNDS": "true",
            },
            "prd": {
                "PORT": "3000",
                "REDIS_URL": "redis://prd-redis.internal:6379/0",
                "JWT_SECRET": "prd-jwt-secret-demo",
                "PAYPAL_CLIENT_ID": "demo-paypal-live-prd",
                "FEATURE_REFUNDS": "false",
            },
        },
    },
]


# Tokens de sistema (globales, sin proyecto). `exercise` = endpoints de
# /v1/service/* que se llaman con el token recién creado para que quede
# registrado su último uso. El de keys:rotate NO se ejercita: usarlo rota
# llaves de verdad.
SYSTEM_TOKENS: list[dict] = [
    {
        "name": "lambda-rotation",
        "description": "Rotación diaria de llaves (Lambda rotation-worker)",
        "scopes": ["keys:rotate"],
        "expires_in_days": 365,
        "exercise": [],
    },
    {
        "name": "ci-deploy-reader",
        "description": "Pipeline de CI: lee proyectos y ambientes antes de desplegar",
        "scopes": ["projects:list", "projects:read", "environments:list"],
        "expires_in_days": 90,
        "exercise": ["/service/projects", "/service/projects/{project_id}",
                     "/service/projects/{project_id}/environments"],
    },
    {
        "name": "auditoria-org",
        "description": "Reporte mensual de auditoría de la organización",
        "scopes": ["org:read", "projects:list"],
        "expires_in_days": 180,
        "exercise": ["/service/organizations/{org_id}", "/service/projects"],
    },
    {
        "name": "monitoreo-inventario",
        "description": "Dashboard interno: inventario de proyectos y ambientes",
        "scopes": ["projects:list", "projects:read", "environments:list"],
        "expires_in_days": 30,
        "exercise": ["/service/projects", "/service/projects/{project_id}/environments"],
    },
]

# Tokens de proyecto: se crean en CADA proyecto (pestaña Tokens del proyecto).
# `environment` = slug del ambiente al que queda restringido (None = todos).
# `exercise` = llamadas de prueba a /v1/service/* para registrar su último uso;
# {env_id} es el ambiente del token, {project_id} el proyecto.
PROJECT_TOKENS: list[dict] = [
    {
        "name": "backend-produccion",
        "description": "Servidor de producción: lee los secretos de prd al arrancar",
        "scopes": ["secrets:read"],
        "environment": "prd",
        "expires_in_days": 90,
        "exercise": ["/service/secrets?environment={env_id}"],
    },
    {
        "name": "backend-staging",
        "description": "Servidor de staging: lee secretos y datos del ambiente stg",
        "scopes": ["secrets:read", "environments:read"],
        "environment": "stg",
        "expires_in_days": 60,
        "exercise": ["/service/secrets?environment={env_id}", "/service/environments/{env_id}"],
    },
    {
        "name": "dev-local",
        "description": "Desarrollo local con la CLI (tek-secrets pull) contra dev",
        "scopes": ["secrets:read"],
        "environment": "dev",
        "expires_in_days": 30,
        "exercise": ["/service/secrets?environment={env_id}"],
    },
    {
        "name": "ci-pipeline",
        "description": "GitHub Actions: inspecciona el proyecto y sus ambientes antes del deploy",
        "scopes": ["projects:read", "environments:list"],
        "environment": None,
        "expires_in_days": 180,
        "exercise": ["/service/projects/{project_id}", "/service/projects/{project_id}/environments"],
    },
]

TOKENS_OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".seed-tokens.env")


class ApiError(RuntimeError):
    pass


def slugify(text: str) -> str:
    replacements = str.maketrans("áéíóúñü", "aeiounu")
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower().translate(replacements))
    return slug.strip("-")


def resolve_token(cli_token: str | None) -> str:
    if cli_token:
        return cli_token
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    try:
        out = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        sys.exit("No hay token: pasá --token, exportá GITHUB_TOKEN o logueate con `gh auth login`.")


def load_integrations(path: str) -> tuple[dict | None, dict | None]:
    """Devuelve (render_data, vercel_data); None si faltan credenciales."""
    values: dict[str, str] = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    values[key.strip()] = value.strip().strip('"').strip("'")
    for key in ("RENDER_SERVICE_ID", "RENDER_API_TOKEN", "VERCEL_PROJECT_ID",
                "VERCEL_TOKEN", "VERCEL_TARGET"):
        if os.environ.get(key):
            values[key] = os.environ[key]

    render = None
    if values.get("RENDER_SERVICE_ID") and values.get("RENDER_API_TOKEN"):
        render = {
            "render_server_id": values["RENDER_SERVICE_ID"],
            "render_token": values["RENDER_API_TOKEN"],
        }

    vercel = None
    if values.get("VERCEL_PROJECT_ID") and values.get("VERCEL_TOKEN"):
        targets = [t.strip() for t in values.get("VERCEL_TARGET", "preview").split(",") if t.strip()]
        vercel = {
            "vercel_project_id": values["VERCEL_PROJECT_ID"],
            "vercel_token": values["VERCEL_TOKEN"],
            "vercel_target": targets,
        }
    return render, vercel


def call(api_url: str, token: str, method: str, path: str, body: dict | None = None,
         service_token: bool = False) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    auth = ({"Authorization": f"Bearer {token}"} if service_token
            else {"X-GitHub-Token": token})
    req = urllib.request.Request(
        f"{api_url.rstrip('/')}/v1{path}",
        data=data,
        method=method,
        headers={**auth, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise ApiError(f"{method} {path} → HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise ApiError(f"{method} {path} → no se pudo conectar: {e.reason}") from None


def doc_id(doc: dict) -> str:
    return str(doc.get("_id") or doc.get("id"))


def seed_system_tokens(api: str, token: str, suffix: str,
                       org_id: str | None, project_id: str | None) -> list[str]:
    """Crea los SYSTEM_TOKENS y los ejercita. Devuelve líneas KEY=secreto."""
    print("\n✓ Tokens de sistema")
    lines = ["", "# --- Tokens de sistema (globales) ---"]
    for spec in SYSTEM_TOKENS:
        name = f"{spec['name']}-{suffix}"
        try:
            created = call(api, token, "POST", "/system-tokens", {
                "name": name,
                "description": spec["description"],
                "scopes": spec["scopes"],
                "expires_in_days": spec["expires_in_days"],
            })
        except ApiError as e:
            if "Document failed validation" in str(e):
                raise ApiError(
                    f"{e}\n  El validador de Mongo exige project_id. Con el túnel de Mongo "
                    "abierto, correr una vez:\n    python3 ~/Desktop/tesis/tek-secrets/rotation/scripts/"
                    "relax_service_token_validator.py --mongodb-url \"<url>\" --db secrets-27222"
                ) from None
            raise
        secret = created.get("tokenSecret") or created.get("token_secret")
        lines.append(f"SYSTEM_{spec['name'].upper().replace('-', '_')}={secret}")

        uses = 0
        for path in spec["exercise"]:
            if ("{project_id}" in path and not project_id) or ("{org_id}" in path and not org_id):
                continue
            call(api, secret, "GET", path.format(project_id=project_id, org_id=org_id),
                 service_token=True)
            uses += 1
        uso = f"{uses} llamadas de prueba" if uses else "sin usar (rotaría llaves)"
        print(f"    ✓ {name:<28} {', '.join(spec['scopes']):<50} {uso}")
    return lines


def seed_project_tokens(api: str, token: str, suffix: str, project_name: str,
                        project_id: str, envs_by_slug: dict[str, dict]) -> list[str]:
    """Crea los PROJECT_TOKENS en un proyecto y los ejercita. Devuelve líneas KEY=secreto."""
    lines = ["", f"# --- Tokens del proyecto {project_name} ({project_id}) ---"]
    prefix = slugify(project_name).upper().replace("-", "_")
    for spec in PROJECT_TOKENS:
        env_slug = spec["environment"]
        env_id = doc_id(envs_by_slug[env_slug]) if env_slug else None
        body = {
            "name": f"{spec['name']}-{suffix}",
            "description": spec["description"],
            "scopes": spec["scopes"],
            "expiresInDays": spec["expires_in_days"],
        }
        if env_id:
            body["environmentId"] = env_id
        created = call(api, token, "POST", f"/projects/{project_id}/tokens", body)
        secret = created.get("tokenSecret") or created.get("token_secret")
        lines.append(f"{prefix}_{spec['name'].upper().replace('-', '_')}={secret}")

        for path in spec["exercise"]:
            call(api, secret, "GET", path.format(project_id=project_id, env_id=env_id),
                 service_token=True)
        alcance = env_slug or "todos"
        print(f"    🔑 {spec['name']:<20} [{alcance:<5}] {', '.join(spec['scopes']):<36} "
              f"{len(spec['exercise'])} llamadas")
    return lines


def write_tokens_file(lines: list[str]) -> None:
    header = ["# Tokens creados por seed_via_api.py — NO commitear (ignorado por *.env).",
              "# El secreto solo se muestra al crearlo; este archivo es la única copia.",
              "# Cada corrida lo sobrescribe."]
    old_umask = os.umask(0o077)
    try:
        with open(TOKENS_OUT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(header + lines) + "\n")
    finally:
        os.umask(old_umask)
    print(f"\n  Secretos de los tokens guardados en {TOKENS_OUT_FILE}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=("Seed de demo vía la API de Tek Secrets: organización, proyectos con "
                     "variables por ambiente, Render/Vercel en staging, tokens de proyecto "
                     "y tokens de sistema."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
ejemplos:
  python3 scripts/seed_via_api.py
      Todo con los valores por defecto (org "Avila Tek", proyectos "Tienda Online"
      y "Servicio de Pagos", tokens de proyecto y de sistema).

  python3 scripts/seed_via_api.py -o "Demo Defensa" -p "Portal Clientes" -p "API Inventario"
      Organización y proyectos con tus nombres.

  python3 scripts/seed_via_api.py -p "Tek Secrets Back" -f "Backend" -t "Equipo API" \\
                                  -p "Tek Secrets Front" -f "Frontend" -t "Equipo Web"
      Cada proyecto en su carpeta y equipo (-f/-t van en el mismo orden que -p).

  python3 scripts/seed_via_api.py -p "Un Solo Proyecto"
      Un solo proyecto (usa las variables de la primera plantilla).

  python3 scripts/seed_via_api.py -p "Proyecto A" --no-project-tokens --no-system-tokens
      Solo org + proyecto + variables, sin tokens.

  python3 scripts/seed_via_api.py --only-system-tokens
      Solo los 4 tokens de sistema (no crea org ni proyectos).

  python3 scripts/seed_via_api.py --api-url http://localhost:8000
      Contra la API local.

archivos:
  scripts/.seed.env          credenciales de Render/Vercel (entrada, ignorado por git)
  scripts/.seed-tokens.env   secretos de los tokens creados (salida, se sobrescribe)
""",
    )
    parser.add_argument(
        "--org-name", "-o", default="Avila Tek", metavar="NOMBRE",
        help='Nombre de la organización (default: "Avila Tek").',
    )
    parser.add_argument(
        "--project", "-p", action="append", dest="projects", metavar="NOMBRE",
        help=("Nombre de un proyecto. Repetir el flag para varios: -p \"A\" -p \"B\". "
              "Toman en orden las variables de las plantillas (si hay más nombres que "
              "plantillas, se reusan en ciclo). "
              'Default: "Tienda Online" y "Servicio de Pagos".'),
    )
    parser.add_argument(
        "--folder", "-f", action="append", dest="folders", metavar="CARPETA",
        help=("Carpeta (vista \"Por Proyecto\") de cada proyecto, en el mismo orden que -p. "
              "Si se pasa una sola, aplica a todos. Default: la de la plantilla "
              "(\"E-commerce\", \"Fintech\")."),
    )
    parser.add_argument(
        "--team", "-t", action="append", dest="teams", metavar="EQUIPO",
        help=("Equipo (vista \"Por Equipo\") de cada proyecto, en el mismo orden que -p. "
              "Si se pasa uno solo, aplica a todos. Default: el de la plantilla "
              "(\"Equipo Web\", \"Equipo Pagos\")."),
    )
    parser.add_argument(
        "--api-url", default=os.environ.get("TEK_API_URL", DEFAULT_API_URL), metavar="URL",
        help=f"URL de la API (default: TEK_API_URL o {DEFAULT_API_URL}).",
    )
    parser.add_argument(
        "--token", metavar="TOKEN",
        help="Token de GitHub (default: GITHUB_TOKEN o `gh auth token`). Necesita scope user:email.",
    )
    tokens = parser.add_mutually_exclusive_group()
    tokens.add_argument("--no-system-tokens", action="store_true",
                        help="No crear los tokens de sistema de demo.")
    parser.add_argument("--no-project-tokens", action="store_true",
                        help="No crear los tokens de cada proyecto.")
    tokens.add_argument("--only-system-tokens", action="store_true",
                        help=("Crear solo los tokens de sistema (sin organización ni proyectos). "
                              "Tu usuario ya tiene que ser owner/admin de alguna organización."))
    args = parser.parse_args()

    if args.projects:
        names = [n.strip() for n in args.projects if n.strip()]
        if not names:
            parser.error("--project no puede ser vacío")
        project_specs = [
            {**PROJECTS[i % len(PROJECTS)], "name": name} for i, name in enumerate(names)
        ]
    else:
        project_specs = [dict(spec) for spec in PROJECTS]

    def pick(values: list[str] | None, i: int) -> str | None:
        if not values:
            return None
        return values[0] if len(values) == 1 else (values[i] if i < len(values) else None)

    for i, spec in enumerate(project_specs):
        tags = dict(spec["tags"])
        folder, team = pick(args.folders, i), pick(args.teams, i)
        if folder:
            tags["folder"] = folder
        if team:
            tags["team"] = team
        spec["tags"] = tags

    token = resolve_token(args.token)
    suffix = secrets.token_hex(2)
    api = args.api_url
    render_data, vercel_data = load_integrations(SEED_ENV_FILE)

    try:
        print(f"→ API: {api}")
        if render_data is None:
            print("  ! Sin RENDER_SERVICE_ID/RENDER_API_TOKEN: no se asigna Render.")
        if vercel_data is None:
            print("  ! Sin VERCEL_PROJECT_ID/VERCEL_TOKEN: no se asigna Vercel.")

        org_id: str | None = None
        project_id: str | None = None
        token_lines: list[str] = []

        if args.only_system_tokens:
            listed = call(api, token, "GET", "/organizations/")
            if listed:
                org_id = doc_id(listed[0])
            write_tokens_file(seed_system_tokens(api, token, suffix, org_id, None))
            print("\nListo.")
            return

        org = call(api, token, "POST", "/organizations/", {
            "name": args.org_name,
            "slug": f"{slugify(args.org_name)}-{suffix}",
        })
        org_id = doc_id(org)
        print(f"✓ Organización '{org['name']}' ({org_id})")

        for spec in project_specs:
            project = call(api, token, "POST", "/projects/", {"project": {
                "name": spec["name"],
                "slug": f"{slugify(spec['name'])}-{suffix}",
                "tags": spec["tags"],
                "organization_id": org_id,
            }})
            project_id = project_id or doc_id(project)
            current_id = doc_id(project)
            print(f"  ✓ Proyecto '{project['name']}' ({current_id})")

            envs = call(api, token, "GET", f"/projects/{current_id}/environments")
            by_slug = {e["slug"]: e for e in envs.get("environments", [])}

            for env_slug, variables in spec["environments"].items():
                env = by_slug.get(env_slug)
                if env is None:
                    raise ApiError(f"El proyecto {current_id} no tiene el ambiente '{env_slug}'")
                call(api, token, "PUT", f"/environments/{doc_id(env)}", {
                    "environment": {"secrets": variables},
                })
                extras: list[str] = []
                if env_slug == INTEGRATIONS_ENV_SLUG:
                    if render_data:
                        call(api, token, "PATCH", f"/environments/{doc_id(env)}/render",
                             {"render_data": render_data})
                        extras.append("Render")
                    if vercel_data:
                        call(api, token, "PATCH", f"/environments/{doc_id(env)}/vercel",
                             {"vercel_data": vercel_data})
                        extras.append(f"Vercel ({', '.join(vercel_data['vercel_target'])})")
                suffix_txt = f" + {' + '.join(extras)}" if extras else ""
                print(f"    ✓ {env['name']:<12} {len(variables)} variables{suffix_txt}")

            if not args.no_project_tokens:
                token_lines += seed_project_tokens(
                    api, token, suffix, spec["name"], current_id, by_slug)

        if not args.no_system_tokens:
            token_lines += seed_system_tokens(api, token, suffix, org_id, project_id)

        if token_lines:
            write_tokens_file(token_lines)

    except ApiError as e:
        print(f"✗ {e}", file=sys.stderr)
        if "HTTP 401" in str(e):
            print(
                "  El token no autenticó. Si usás el de `gh`, agregale el scope de email:\n"
                "    gh auth refresh -h github.com -s user:email",
                file=sys.stderr,
            )
        sys.exit(1)

    print("\nListo. Entrá a https://app.secretsapi.online con la misma cuenta de GitHub para verlo.")


if __name__ == "__main__":
    main()
