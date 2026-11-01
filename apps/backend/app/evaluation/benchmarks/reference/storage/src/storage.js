function serialize(todos) {
  return JSON.stringify(todos)
}

function isTodo(value) {
  return (
    value !== null &&
    typeof value === 'object' &&
    typeof value.id === 'number' &&
    typeof value.title === 'string' &&
    typeof value.done === 'boolean'
  )
}

function deserialize(text) {
  let data
  try {
    data = JSON.parse(text)
  } catch {
    return []
  }
  return Array.isArray(data) ? data.filter(isTodo) : []
}

module.exports = { serialize, deserialize }
