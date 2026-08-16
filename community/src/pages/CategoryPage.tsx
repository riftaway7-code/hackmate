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
      const nextPosts = await fetchPosts(cat.id)
      setPosts(nextPosts)
      if (user) setVotedIds(await fetchMyVotes(user.id, nextPosts.map((post) => post.id), []))
    } catch (caught) { setError((caught as Error).message) }
  }

  useEffect(() => { load() /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [slug, user])

  return (
    <div>
      <div className="page-header">
        <div><div className="eyebrow">Channel</div><h1># {category?.name ?? slug}</h1><div className="page-subtitle">{category?.description}</div></div>
        {user ? <button onClick={() => setShowForm((visible) => !visible)}>{showForm ? 'Cancel' : '+ New post'}</button> : <button onClick={signInWithGithub}>Sign in to post</button>}
      </div>
      {error && <div className="error">{error}</div>}
      {showForm && category && <NewPostForm categoryId={category.id} onCreated={() => { setShowForm(false); load() }} />}
      {!posts && !error && <div className="meta">Loading posts…</div>}
      {posts?.length === 0 && <div className="empty-state">No posts yet — start the conversation.</div>}
      <div className="feed">{posts?.map((post) => (
        <article key={post.id} className="card post-card">
          <div className="vote-column"><VoteButton score={post.score ?? 0} voted={votedIds.has(post.id)} postId={post.id} /></div>
          <div className="post-content"><Link to={`/p/${post.id}`} className="post-title">{post.title}</Link><div className="meta post-meta"><span>by <strong>{post.profiles?.github_username ?? 'unknown'}</strong></span><span>◯ {post.comment_count ?? 0} comments</span><span>{new Date(post.created_at).toLocaleDateString()}</span></div></div>
        </article>
      ))}</div>
    </div>
  )
}

function NewPostForm({ categoryId, onCreated }: { categoryId: string; onCreated: () => void }) {
  const { user } = useAuth()
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!user || !title.trim()) return
    setBusy(true); setError(null)
    try { await createPost(categoryId, user.id, title.trim(), body.trim()); setTitle(''); setBody(''); onCreated() }
    catch (caught) { setError((caught as Error).message) } finally { setBusy(false) }
  }
  return (
    <form onSubmit={submit} className="card composer">
      <input placeholder="Give your post a clear title" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={300} required />
      <textarea placeholder="Add context, specs, logs, or anything else that helps…" rows={5} value={body} onChange={(event) => setBody(event.target.value)} />
      {error && <div className="error">{error}</div>}
      <div><button disabled={busy} type="submit">Publish post</button></div>
    </form>
  )
}
