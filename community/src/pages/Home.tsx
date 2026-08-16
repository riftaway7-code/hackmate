import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchCategories } from '../lib/queries'
import type { Category } from '../lib/types'

export function Home() {
  const [categories, setCategories] = useState<Category[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchCategories().then(setCategories).catch((e) => setError(e.message))
  }, [])

  return (
    <div>
      <div className="section-title">Categories</div>
      {error && <div className="error">{error}</div>}
      {!categories && !error && <div className="meta">loading…</div>}
      {categories?.map((c) => (
        <Link key={c.id} to={`/c/${c.slug}`} style={{ textDecoration: 'none' }}>
          <div className="card">
            <div style={{ color: 'var(--accent)' }}>{c.name}</div>
            <div className="meta">{c.description}</div>
          </div>
        </Link>
      ))}
    </div>
  )
}
