# JavaScript and TypeScript standards

## Modules
Use ES modules (`import`/`export`) and set `"type": "module"` in `package.json` for new Node projects. Use `const` by default and `let` only when reassigning; never `var`. Use strict equality (`===`).

## Dependencies
Prefer the platform: the browser DOM, `localStorage`, and Node's standard library (`node:test`, `node:assert`, `node:fs`). Do not add npm dependencies unless the task explicitly requires them; the sandbox runs checks offline, so tests must not need `npm install`.

## Immutability
Do not mutate arrays or objects passed in as arguments. Return new values: `[...todos, todo]`, `todos.filter(...)`, `todos.map(t => t.id === id ? { ...t, done: !t.done } : t)`.

## Browser code
Keep DOM code thin: query elements once, render from state, and re-render after state changes. Escape user text with `textContent`, never `innerHTML`, to avoid XSS. Persist with `localStorage` using `JSON.stringify` / `JSON.parse`, and handle missing or corrupt stored data by falling back to an empty list.

## TypeScript
When the project uses TypeScript, type exported functions and data shapes explicitly (`interface Todo { id: string; title: string; done: boolean }`). Avoid `any`.
