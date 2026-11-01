const test = require('node:test')
const assert = require('node:assert/strict')

const { addTodo, deleteTodo } = require('../src/todos')

test('deleteTodo removes only the matching todo, purely', () => {
  const todos = addTodo(addTodo(addTodo([], 'a'), 'b'), 'c')
  const result = deleteTodo(todos, 2)
  assert.deepEqual(result.map((t) => t.title), ['a', 'c'])
  assert.equal(todos.length, 3)
})

test('deleteTodo with an unknown id leaves the list unchanged', () => {
  const todos = addTodo([], 'a')
  assert.deepEqual(deleteTodo(todos, 99), todos)
})
