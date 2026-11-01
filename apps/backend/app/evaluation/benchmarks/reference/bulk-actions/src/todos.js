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

function completeAll(todos) {
  return todos.map((t) => ({ ...t, done: true }))
}

function toggleAll(todos) {
  const target = !todos.every((t) => t.done)
  return todos.map((t) => ({ ...t, done: target }))
}

module.exports = { addTodo, toggleTodo, nextId, completeAll, toggleAll }
