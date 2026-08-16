import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchCategories } from '../lib/queries'
import type { Category } from '../lib/types'

export function Home() {
  const [categories, setCategories] = useState<Category[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { fetchCategories().then(setCategories).catch((e) => setError(e.message)) }, [])
  return (
    <div className="home-grid">
      <div>
        <section className="hero"><div className="eyebrow">Open source · community powered</div><h1>Build better Hackintoshes, together.</h1><p>Ask for help, report issues, share your setup, and trade hard-won knowledge with the HackMate community.</p></section>
        <div className="section-title">Browse channels</div>
        {error && <div className="error">{error}</div>}
        {!categories && !error && <div className="meta">Loading channels…</div>}
        <div className="category-grid">{categories?.map((category) => (
          <Link key={category.id} to={`/c/${category.slug}`}><article className="category-card"><div className="category-name"><span>#</span>{category.name}</div><div className="meta">{category.description}</div></article></Link>
        ))}</div>
      </div>
      <aside className="community-panel"><div className="community-panel-accent" /><div className="community-panel-body"><h3>About HackMate</h3><p>A focused place for builders helping builders. Be specific, be kind, and share what worked.</p><div className="stat-row"><div className="stat"><strong>4</strong><span>channels</span></div><div className="stat"><strong>24/7</strong><span>open</span></div></div></div></aside>
    </div>
  )
}
