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

function deleteTodo(todos, id) {
  return todos.filter((t) => t.id !== id)
}

module.exports = { addTodo, toggleTodo, nextId, deleteTodo }
