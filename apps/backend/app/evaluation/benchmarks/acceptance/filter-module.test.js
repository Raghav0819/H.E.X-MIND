const test = require('node:test')
const assert = require('node:assert/strict')

const { addTodo, toggleTodo } = require('../src/todos')
const { filterTodos, FILTERS } = require('../src/filter')

const todos = toggleTodo(addTodo(addTodo([], 'a'), 'b'), 2)

test('filterTodos supports all, active and done', () => {
  assert.deepEqual(FILTERS, ['all', 'active', 'done'])
  assert.deepEqual(filterTodos(todos, 'all').map((t) => t.id), [1, 2])
  assert.deepEqual(filterTodos(todos, 'active').map((t) => t.id), [1])
  assert.deepEqual(filterTodos(todos, 'done').map((t) => t.id), [2])
})

test('filterTodos rejects unknown filters', () => {
  assert.throws(() => filterTodos(todos, 'later'), { message: 'unknown filter' })
})
