import { useEffect, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../lib/AuthContext'
import { VoteButton } from '../components/VoteButton'
import { createPost, fetchCategory, fetchMyVotes, fetchPosts } from '../lib/queries'
import type { Category, Post } from '../lib/types'

export function CategoryPage() {
  const { slug } = useParams<{ slug: string }>()
  const { user, signInWithGithub } = useAuth()
  const [category, setCategory] = useState<Category | null>(null)
  const [posts, setPosts] = useState<Post[] | null>(null)
  const [votedIds, setVotedIds] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)

  async function load() {
    if (!slug) return
    try {
      const cat = await fetchCategory(slug)
      setCategory(cat)
      if (!cat) return
      const p = await fetchPosts(cat.id)
      setPosts(p)
      if (user) {
        const voted = await fetchMyVotes(user.id, p.map((x) => x.id), [])
        setVotedIds(voted)
      }
    } catch (e) {
      setError((e as Error).message)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, user])

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div className="section-title">{category?.name ?? slug}</div>
        {user ? (
          <button onClick={() => setShowForm((s) => !s)}>{showForm ? 'cancel' : '+ new post'}</button>
        ) : (
          <button onClick={signInWithGithub}>sign in to post</button>
        )}
      </div>

      {error && <div className="error">{error}</div>}

      {showForm && category && (
        <NewPostForm
          categoryId={category.id}
          onCreated={() => {
            setShowForm(false)
            load()
          }}
        />
      )}

      {!posts && !error && <div className="meta">loading…</div>}
      {posts?.length === 0 && <div className="meta">No posts yet — be the first.</div>}
      {posts?.map((p) => (
        <div key={p.id} className="card">
          <Link to={`/p/${p.id}`} style={{ textDecoration: 'none' }}>
            <div style={{ color: 'var(--text)' }}>{p.title}</div>
          </Link>
          <div className="meta" style={{ display: 'flex', alignItems: 'center', gap: '0.8rem', marginTop: '0.3rem' }}>
            <VoteButton score={p.score ?? 0} voted={votedIds.has(p.id)} postId={p.id} />
            <span>{p.comment_count ?? 0} comments</span>
            <span>by {p.profiles?.github_username ?? 'unknown'}</span>
            <span>{new Date(p.created_at).toLocaleDateString()}</span>
          </div>
        </div>
      ))}
    </div>
  )
}

function NewPostForm({ categoryId, onCreated }: { categoryId: string; onCreated: () => void }) {
  const { user } = useAuth()
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!user || !title.trim()) return
    setBusy(true)
    setError(null)
    try {
      await createPost(categoryId, user.id, title.trim(), body.trim())
      setTitle('')
      setBody('')
      onCreated()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
      <input placeholder="title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} required />
      <textarea placeholder="body (optional)" rows={4} value={body} onChange={(e) => setBody(e.target.value)} />
      {error && <div className="error">{error}</div>}
      <div>
        <button disabled={busy} type="submit">post</button>
      </div>
    </form>
  )
}
