/**
 * A todo: { id: number, title: string, done: boolean }
 * All functions are pure: they return new arrays and never mutate their input.
 */

function nextId(todos) {
  return todos.reduce((max, t) => Math.max(max, t.id), 0) + 1
}

function addTodo(todos, title) {
  return [...todos, { id: nextId(todos), title, done: false }]
}

function toggleTodo(todos, id) {
  return todos.map((t) => (t.id === id ? { ...t, done: !t.done } : t))
}

function renameTodo(todos, id, title) {
  const clean = String(title ?? '').trim()
  if (!clean) throw new Error('title required')
  return todos.map((t) => (t.id === id ? { ...t, title: clean } : t))
}

module.exports = { addTodo, toggleTodo, nextId, renameTodo }
