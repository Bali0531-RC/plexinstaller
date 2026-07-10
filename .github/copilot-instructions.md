## Shell requirements

The default shell for this project is fish shell.

All shell commands must be written for fish syntax, not bash, zsh, sh, or POSIX shell.

Rules:
- Use `set VAR value` instead of `export VAR=value`
- Use `command1; and command2` instead of `command1 && command2`
- Use `command1; or command2` instead of `command1 || command2`
- Use `$(command)` substitutions as `(command)`
- Use fish loops:
  `for x in $list`
  not:
  `for x in "$@"; do`
- Do not use bashisms such as:
  - `[[ ]]`
  - `${VAR:-default}`
  - arrays with `()`
  - `source` when `.` is intended
  - `eval "$(command)"`
- Before suggesting terminal commands, verify they are valid fish syntax.