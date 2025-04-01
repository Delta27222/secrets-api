# `tek-secrets`

**Usage**:

```console
$ tek-secrets [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--install-completion`: Install completion for the current shell.
* `--show-completion`: Show completion for the current shell, to copy it or customize the installation.
* `--help`: Show this message and exit.

**Commands**:

* `login`: Authenticate with GitHub and authorize...
* `user`: Retrieve and display information about the...
* `logout`: Terminate the current authenticated session.
* `projects`
* `env`

## `tek-secrets login`

Authenticate with GitHub and authorize against Tek Secrets

This command:
1. Initiates GitHub OAuth flow
2. Retrieves GitHub access token
3. Authenticates with the Tek Secrets API using the GitHub token
4. Displays authentication status and user information

Raises:
    typer.Exit: If GitHub token retrieval fails

**Usage**:

```console
$ tek-secrets login [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `tek-secrets user`

Retrieve and display information about the currently authenticated user.

Requires:
    - Active authentication session (user must be logged in)

Outputs:
    - User information in key-value format
    - Error message if not authenticated or request fails

**Usage**:

```console
$ tek-secrets user [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `tek-secrets logout`

Terminate the current authenticated session.

Clears the stored access token and ends the user session.

**Usage**:

```console
$ tek-secrets logout [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `tek-secrets projects`

**Usage**:

```console
$ tek-secrets projects [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `list`: List all projects for the authenticated user.
* `show`: Display detailed information about a...

### `tek-secrets projects list`

List all projects for the authenticated user.

Args:
    organization_id (Optional): The organization ID to filter projects.
                                    If not provided, user will be prompted to select one.

Behavior:
    - Requires authenticated session
    - If no organization_id provided, prompts user to select one
    - Makes API request to fetch projects
    - Displays projects in list format

Raises:
    typer.Exit: If user is not authenticated or no projects found

**Usage**:

```console
$ tek-secrets projects list [OPTIONS]
```

**Options**:

* `-o, --org TEXT`: Organization ID
* `--help`: Show this message and exit.

### `tek-secrets projects show`

Display detailed information about a specific project.

Args:
    project_id (Optional): The project ID to view details.
                               If not provided, user will be prompted to select one.

Behavior:
    - Requires authenticated session
    - If no project_id provided, prompts user to select one
    - Makes API request to fetch project details
    - Displays project information

Raises:
    typer.Exit: If user is not authenticated

**Usage**:

```console
$ tek-secrets projects show [OPTIONS]
```

**Options**:

* `-p, --project TEXT`: Project ID
* `--help`: Show this message and exit.

## `tek-secrets env`

**Usage**:

```console
$ tek-secrets env [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `get`: Retrieve secrets for a specific project...
* `update`: Update environment secrets using values...

### `tek-secrets env get`

Retrieve secrets for a specific project environment.

Args:
    organization_id (Optional): Organization identifier
    project_id (Optional): Project identifier
    env (Optional): Target environment slug
    
Behavior:
    - Requires authenticated session
    - If IDs not provided, interactively prompts for selection
    - Displays environment variables in readable format
    
Raises:
    typer.Exit: If user is not authenticated

**Usage**:

```console
$ tek-secrets env get [OPTIONS]
```

**Options**:

* `-o, --org TEXT`: Organization ID
* `-p, --project TEXT`: Project ID
* `-e, --env TEXT`: Project environment
* `--output-env FILE`: Path to save the environment variables
* `--help`: Show this message and exit.

### `tek-secrets env update`

Update environment secrets using values from a .env file.

Args:
    env_file (Path): Path to .env file containing updated secrets
    env_slug (Optional): Environment identifier slug
    organization_id (Optional): Organization identifier
    project_id (Optional): Project identifier
    environment_id (Optional): Direct environment ID
    
Behavior:
    - Requires authenticated session
    - Parses provided .env file into key-value pairs
    - Updates specified environment with new secrets
    - Supports both interactive selection and direct ID specification
    
Raises:
    typer.Exit: If authentication fails or update operation errors occur

**Usage**:

```console
$ tek-secrets env update [OPTIONS]
```

**Options**:

* `--env-file FILE`: Path to .env file containing updated secrets  [required]
* `-e, --env TEXT`: Project environment slug
* `-o, --org TEXT`: Organization ID
* `-p, --project TEXT`: Project ID
* `--env-id TEXT`: Environment ID (use when slug is not specified)
* `--help`: Show this message and exit.
