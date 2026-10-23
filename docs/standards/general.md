# General coding standards

## Scope of changes
Change only what the task asks for. Read the current file before editing it; never assume its contents from earlier messages. Prefer small, targeted edits (`replace_in_file`) over rewriting whole files. Do not reformat unrelated code.

## Naming and structure
Use descriptive names: `todos`, `addTodo`, `isCompleted`; avoid single letters except loop indices. Keep functions short and focused on one job. Put pure logic (data changes, filtering, validation) in separate functions from code that touches the DOM, storage or the network, so the logic can be tested.

## Errors
Validate input at the boundary (user input, parsed storage data). Fail with a clear message rather than silently ignoring bad data. Never swallow errors without at least logging them.

## Comments
Comment why, not what. Keep comments short. Remove commented-out code.

## Files
Do not create files outside the project structure described in the task. Do not touch `.env` files, `.git`, `.hexmind`, or `node_modules`.
