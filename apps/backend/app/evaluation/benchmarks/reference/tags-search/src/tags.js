function normalize(tag) {
  const clean = String(tag ?? '').trim().toLowerCase()
  if (!clean) throw new Error('tag required')
  return clean
}

function addTag(todos, id, tag) {
  const clean = normalize(tag)
  return todos.map((t) => {
    if (t.id !== id) return t
    const tags = t.tags ?? []
    return { ...t, tags: tags.includes(clean) ? tags : [...tags, clean] }
  })
}

function removeTag(todos, id, tag) {
  const clean = normalize(tag)
  return todos.map((t) => (t.id === id ? { ...t, tags: (t.tags ?? []).filter((x) => x !== clean) } : t))
}

function searchTodos(todos, query) {
  const q = String(query ?? '').trim().toLowerCase()
  if (!q) return [...todos]
  return todos.filter((t) => t.title.toLowerCase().includes(q) || (t.tags ?? []).some((tag) => tag.includes(q)))
}

module.exports = { addTag, removeTag, searchTodos }
