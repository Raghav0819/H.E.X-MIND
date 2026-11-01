const test = require('node:test')
const assert = require('node:assert/strict')

const { addTodo } = require('../src/todos')
const { serialize, deserialize } = require('../src/storage')

test('serialize and deserialize round-trip', () => {
  const todos = addTodo(addTodo([], 'a'), 'b')
  assert.equal(typeof serialize(todos), 'string')
  assert.deepEqual(deserialize(serialize(todos)), todos)
})

test('deserialize tolerates corrupt data', () => {
  assert.deepEqual(deserialize('not json'), [])
  assert.deepEqual(deserialize('{"a": 1}'), [])
  const mixed = JSON.stringify([{ id: 1, title: 'ok', done: false }, { id: 'x', title: 'bad', done: false }, null, 3])
  assert.deepEqual(deserialize(mixed), [{ id: 1, title: 'ok', done: false }])
})
