function isOverdue(todo, today) {
  return !todo.done && typeof todo.dueDate === 'string' && todo.dueDate < today
}

module.exports = { isOverdue }
