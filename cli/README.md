# `tek-secrets`

**Usage**:

```console
$ tek-secrets [OPTIONS] COMMAND [ARGS]...
```

**Options**:

- `--install-completion`: Install completion for the current shell.
- `--show-completion`: Show completion for the current shell, to copy it or customize the installation.
- `--help`: Show this message and exit.

**Commands**:

- `login`: Inicia sesión con GitHub y autentica...
- `user`: Obtiene y muestra la información del...
- `logout`: Cierra sesión eliminando el token de...
- `projects`
- `env`

## `tek-secrets login`

Inicia sesión con GitHub y autentica contra la API de FastAPI.

**Usage**:

```console
$ tek-secrets login [OPTIONS]
```

**Options**:

- `--help`: Show this message and exit.

## `tek-secrets user`

Obtiene y muestra la información del usuario actual.

**Usage**:

```console
$ tek-secrets user [OPTIONS]
```

**Options**:

- `--help`: Show this message and exit.

## `tek-secrets logout`

Cierra sesión eliminando el token de acceso guardado.

**Usage**:

```console
$ tek-secrets logout [OPTIONS]
```

**Options**:

- `--help`: Show this message and exit.

## `tek-secrets projects`

**Usage**:

```console
$ tek-secrets projects [OPTIONS] COMMAND [ARGS]...
```

**Options**:

- `--help`: Show this message and exit.

**Commands**:

- `list`: Lista los proyectos del usuario autenticado.

### `tek-secrets projects list`

Lista los proyectos del usuario autenticado. Si no se especifica una organización, se solicita una.

**Usage**:

```console
$ tek-secrets projects list [OPTIONS]
```

**Options**:

- `-o, --org TEXT`: ID de la organización
- `--help`: Show this message and exit.

## `tek-secrets env`

**Usage**:

```console
$ tek-secrets env [OPTIONS] COMMAND [ARGS]...
```

**Options**:

- `--help`: Show this message and exit.

**Commands**:

- `get`: Obtiene los secrets de un entoro especifico
- `update`: Actualiza los secretos de un entorno...

### `tek-secrets env get`

Obtiene los secrets de un entoro especifico

**Usage**:

```console
$ tek-secrets env get [OPTIONS]
```

**Options**:

- `-o, --org TEXT`: ID de la organización
- `-p, --project TEXT`: ID del project
- `-e, --env TEXT`: Entorno del project
- `--help`: Show this message and exit.

### `tek-secrets env update`

Actualiza los secretos de un entorno específico usando el contenido de un archivo .env.

**Usage**:

```console
$ tek-secrets env update [OPTIONS]
```

**Options**:

- `--env-file FILE`: [required]
- `-e, --env TEXT`: Slug del Entorno del project.
- `-o, --org TEXT`: ID de la organización
- `-p, --project TEXT`: ID del project
- `--env-id TEXT`: Id del Entorno del project. (usar en caso de que no indique slug)
- `--help`: Show this message and exit.
