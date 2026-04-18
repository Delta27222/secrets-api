# Tek Secrets API

API y herramientas para gestionar **secretos por proyecto y entorno** (desarrollo, staging, producción, etc.), con **organizaciones**, **miembros** y autenticación vía **GitHub OAuth**. Los datos viven en **MongoDB**; la API está construida con **FastAPI**.

En este monorepo también hay un **CLI** (`cli/`) para autenticarse, listar proyectos y leer o actualizar variables de entorno remotas. Detalle de comandos: [`cli/README.md`](cli/README.md).

Documentación interactiva de la API (con el servidor en marcha): `http://127.0.0.1:8000/docs`.

---

## Requisitos

- Python 3.10 o superior  
- Una base **MongoDB** (local o Atlas) y, si usas login GitHub en serio, una **GitHub OAuth App** (`GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`)

Todas las rutas de la API están bajo el prefijo **`/v1`**.

---

### **Pasos para correr la API (Tek Secrets)**

Desde la carpeta **`api/`** del repositorio:

1. **Crear y activar el entorno virtual, e instalar dependencias**

   ```bash
   cd api
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Variables de entorno (recomendado)**  
   Crea `api/.env` con al menos `MONGODB_URL` (y opcionalmente `SECRET_KEY`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`). Sin esto, la app usará valores por defecto del código, que pueden no ser válidos en tu máquina.

3. **Arrancar la API**

   ```bash
   fastapi dev app/main.py
   ```

   Equivalente habitual con uvicorn:

   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

4. **Desactivar el venv** (cuando termines en esa terminal)

   ```bash
   deactivate
   ```

---

### **Pasos para correr los seeds (MongoDB)**

Los seeds rellenan datos mínimos de prueba (usuario, organización, proyecto, entorno, etc.). El script lee **`MONGODB_URL`** desde el entorno o desde **`api/.env`**.

1. **Definir la conexión a MongoDB** (elige una opción)

   - En **`api/.env`**:

     ```env
     MONGODB_URL=mongodb+srv://USUARIO:PASSWORD@cluster.mongodb.net/?retryWrites=true&w=majority
     MONGO_DB=nombre_de_tu_base
     ```

   - O en la misma sesión, antes de ejecutar el script:

     ```bash
     export MONGODB_URL='mongodb+srv://USUARIO:PASSWORD@cluster.mongodb.net/?retryWrites=true&w=majority'
     ```

   No subas credenciales al repositorio; usa solo tu `.env` local o variables en tu máquina.

2. **Ejecutar el seed** (con el venv activado y estando en **`api/`**)

   ```bash
   python3 scripts/seed_mongo.py
   ```

   Si ya existe un usuario con username `seed-dev-user`, el script no vuelve a crear todo el conjunto inicial. Más opciones y notas (p. ej. `MONGODB_DIRECT_URL`) están en el docstring al inicio de `api/scripts/seed_mongo.py`.

---

## Estructura rápida

| Ruta | Rol |
|------|-----|
| `api/` | Servicio FastAPI (`app/`), `requirements.txt`, `scripts/seed_mongo.py` |
| `cli/` | Cliente de línea de comandos `tek-secrets` |
