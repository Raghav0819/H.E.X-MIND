const COMPARATORS = {
  title: (a, b) => a.title.toLowerCase().localeCompare(b.title.toLowerCase()),
  id: (a, b) => a.id - b.id,
  status: (a, b) => Number(a.done) - Number(b.done),
}

function sortTodos(todos, by) {
  const compare = COMPARATORS[by]
  if (!compare) throw new Error('unknown sort')
  return [...todos].sort(compare)
}

module.exports = { sortTodos }
