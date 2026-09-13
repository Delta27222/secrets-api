# Convenciones de Git y Commits

## Estilo de commits (Conventional Commits)

Formato: `<tipo>(<ámbito>): <descripción corta en imperativo>` — en español, sin punto final. El `<ámbito>` es opcional pero recomendado (el módulo o feature tocado).

### Tipos permitidos

- `feat`: nueva funcionalidad
- `fix`: corrección de un error
- `refactor`: cambio de código que no corrige un bug ni añade una funcionalidad
- `style`: cambios de formato (espacios, comas, etc.) que no afectan el comportamiento
- `docs`: documentación
- `test`: añadir o corregir pruebas
- `chore`: mantenimiento, dependencias o configuración del build

### Ejemplos

- `feat(secrets): implementar endpoint de rotación de secretos`
- `fix(auth): corregir validación de JWT expirado`
- `refactor(services): extraer lógica de cifrado a módulo propio`
