import { useEffect, useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { fetchCategories } from '../lib/queries'
import type { Category } from '../lib/types'

const icons: Record<string, string> = { general: '#', help: '?', bugs: '!', showcase: '✦' }

export function Sidebar() {
  const [categories, setCategories] = useState<Category[]>([])
  useEffect(() => { fetchCategories().then(setCategories).catch(() => undefined) }, [])

  return (
    <aside className="sidebar">
      <Link to="/" className="server-mark" aria-label="HackMate Community">
        <img src={`${import.meta.env.BASE_URL}hackmate-logo.png`} alt="" />
      </Link>
      <div className="sidebar-rule" />
      <nav className="channel-list" aria-label="Community categories">
        <div className="channel-heading">Channels</div>
        {categories.map((category) => (
          <NavLink key={category.id} to={`/c/${category.slug}`} className={({ isActive }) => `channel-link${isActive ? ' active' : ''}`}>
            <span className="channel-icon">{icons[category.slug] ?? '#'}</span>
            <span>{category.name}</span>
          </NavLink>
        ))}
      </nav>
      <a className="sidebar-home" href="../" title="Back to HackMate">↗</a>
    </aside>
  )
}
