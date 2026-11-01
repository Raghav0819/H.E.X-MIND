function summarize(todos, today) {
  const total = todos.length
  const done = todos.filter((t) => t.done).length
  const overdue = todos.filter((t) => !t.done && typeof t.dueDate === 'string' && t.dueDate < today).length
  const completionRate = total === 0 ? 0 : Math.round((done / total) * 100) / 100
  return { total, done, remaining: total - done, overdue, completionRate }
}

module.exports = { summarize }
