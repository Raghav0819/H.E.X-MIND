const test = require('node:test')
const assert = require('node:assert/strict')

const { addTodo, renameTodo } = require('../src/todos')

test('renameTodo sets a trimmed title on the matching todo only', () => {
  const todos = addTodo(addTodo([], 'a'), 'b')
  const result = renameTodo(todos, 2, '  bread ')
  assert.deepEqual(result.map((t) => t.title), ['a', 'bread'])
  assert.equal(todos[1].title, 'b')
})

test('renameTodo rejects empty titles', () => {
  assert.throws(() => renameTodo(addTodo([], 'a'), 1, '  '), { message: 'title required' })
})
