/**
 * A todo: { id: number, title: string, done: boolean }
 * All functions are pure: they return new arrays and never mutate their input.
 */

function nextId(todos) {
  return todos.reduce((max, t) => Math.max(max, t.id), 0) + 1
}

function addTodo(todos, title) {
  const clean = String(title ?? '').trim()
  if (!clean) throw new Error('title required')
  return [...todos, { id: nextId(todos), title: clean, done: false }]
}

function toggleTodo(todos, id) {
  return todos.map((t) => (t.id === id ? { ...t, done: !t.done } : t))
}



module.exports = { addTodo, toggleTodo, nextId }
