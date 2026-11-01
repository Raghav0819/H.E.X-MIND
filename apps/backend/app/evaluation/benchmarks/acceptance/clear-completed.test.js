const test = require('node:test')
const assert = require('node:assert/strict')

const { addTodo, toggleTodo, clearCompleted } = require('../src/todos')

test('clearCompleted keeps only open todos', () => {
  const todos = toggleTodo(toggleTodo(addTodo(addTodo(addTodo([], 'a'), 'b'), 'c'), 1), 3)
  assert.deepEqual(clearCompleted(todos).map((t) => t.title), ['b'])
  assert.equal(todos.length, 3)
})
