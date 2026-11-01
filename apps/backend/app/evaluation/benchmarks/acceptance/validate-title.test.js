const test = require('node:test')
const assert = require('node:assert/strict')

const { addTodo } = require('../src/todos')

test('addTodo trims titles', () => {
  assert.equal(addTodo([], '  milk  ')[0].title, 'milk')
})

test('addTodo rejects empty and whitespace titles', () => {
  assert.throws(() => addTodo([], ''), { message: 'title required' })
  assert.throws(() => addTodo([], '   '), { message: 'title required' })
})
