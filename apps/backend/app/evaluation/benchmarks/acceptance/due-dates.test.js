const test = require('node:test')
const assert = require('node:assert/strict')

const { addTodo, toggleTodo } = require('../src/todos')
const { isOverdue } = require('../src/dates')

test('addTodo stores an optional due date', () => {
  const todos = addTodo(addTodo([], 'a', '2026-01-31'), 'b')
  assert.equal(todos[0].dueDate, '2026-01-31')
  assert.equal(todos[1].dueDate, null)
})

test('isOverdue only for open todos due before today', () => {
  const todos = addTodo(addTodo(addTodo([], 'late', '2026-01-01'), 'today', '2026-02-01'), 'none')
  assert.equal(isOverdue(todos[0], '2026-02-01'), true)
  assert.equal(isOverdue(todos[1], '2026-02-01'), false)
  assert.equal(isOverdue(todos[2], '2026-02-01'), false)
  assert.equal(isOverdue(toggleTodo(todos, 1)[0], '2026-02-01'), false)
})
