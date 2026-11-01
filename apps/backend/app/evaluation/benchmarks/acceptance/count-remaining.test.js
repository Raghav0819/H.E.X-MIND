const test = require('node:test')
const assert = require('node:assert/strict')

const { addTodo, toggleTodo, countRemaining } = require('../src/todos')

test('countRemaining counts open todos', () => {
  const todos = toggleTodo(addTodo(addTodo(addTodo([], 'a'), 'b'), 'c'), 2)
  assert.equal(countRemaining(todos), 2)
  assert.equal(countRemaining([]), 0)
})
