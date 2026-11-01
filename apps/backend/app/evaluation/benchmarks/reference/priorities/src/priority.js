const PRIORITIES = ['low', 'medium', 'high']

function setPriority(todos, id, priority) {
  if (!PRIORITIES.includes(priority)) throw new Error('unknown priority')
  return todos.map((t) => (t.id === id ? { ...t, priority } : t))
}

function rank(todo) {
  return PRIORITIES.indexOf(todo.priority ?? 'medium')
}

function nextTodo(todos) {
  const open = todos.filter((t) => !t.done)
  if (open.length === 0) return null
  return open.reduce((best, t) => (rank(t) > rank(best) || (rank(t) === rank(best) && t.id < best.id) ? t : best))
}

module.exports = { PRIORITIES, setPriority, nextTodo }
