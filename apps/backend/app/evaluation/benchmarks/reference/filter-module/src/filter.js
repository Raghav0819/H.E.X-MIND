const FILTERS = ['all', 'active', 'done']

function filterTodos(todos, filter) {
  if (filter === 'all') return [...todos]
  if (filter === 'active') return todos.filter((t) => !t.done)
  if (filter === 'done') return todos.filter((t) => t.done)
  throw new Error('unknown filter')
}

module.exports = { filterTodos, FILTERS }
