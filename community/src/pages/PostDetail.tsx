import { useEffect, useState, type FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import { useAuth } from '../lib/AuthContext'
import { VoteButton } from '../components/VoteButton'
import { createComment, fetchComments, fetchMyVotes, fetchPost } from '../lib/queries'
import type { Comment, Post } from '../lib/types'

export function PostDetail() {
  const { postId } = useParams<{ postId: string }>()
  const { user, signInWithGithub } = useAuth()
  const [post, setPost] = useState<Post | null>(null)
  const [comments, setComments] = useState<Comment[] | null>(null)
  const [votedIds, setVotedIds] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [replyTo, setReplyTo] = useState<string | null>(null)

  async function load() {
    if (!postId) return
    try {
      const [p, c] = await Promise.all([fetchPost(postId), fetchComments(postId)])
      setPost(p)
      setComments(c)
      if (user && p) {
        const voted = await fetchMyVotes(user.id, [p.id], c.map((x) => x.id))
        setVotedIds(voted)
      }
    } catch (e) {
      setError((e as Error).message)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [postId, user])

  if (error) return <div className="error">{error}</div>
  if (!post) return <div className="meta">loading…</div>

  const topLevel = comments?.filter((c) => !c.parent_id) ?? []
  const repliesOf = (id: string) => comments?.filter((c) => c.parent_id === id) ?? []

  return (
    <div>
      <article className="card post-detail">
        <div className="eyebrow">Discussion</div>
        <h1>{post.title}</h1>
        {post.body && <div className="post-body">{post.body}</div>}
        <div className="meta post-meta">
          <VoteButton score={post.score ?? 0} voted={votedIds.has(post.id)} postId={post.id} />
          <span>by {post.profiles?.github_username ?? 'unknown'}</span>
          <span>{new Date(post.created_at).toLocaleString()}</span>
        </div>
      </article>

      <div className="section-title">Comments</div>

      {user ? (
        <CommentForm postId={post.id} parentId={null} onDone={load} />
      ) : (
        <button onClick={signInWithGithub}>sign in to comment</button>
      )}

      {topLevel.map((c) => (
        <div key={c.id}>
          <CommentCard
            comment={c}
            voted={votedIds.has(c.id)}
            onReply={() => setReplyTo(c.id)}
          />
          {replyTo === c.id && (
            <div className="reply-thread">
              <CommentForm
                postId={post.id}
                parentId={c.id}
                onDone={() => {
                  setReplyTo(null)
                  load()
                }}
              />
            </div>
          )}
          {repliesOf(c.id).map((r) => (
            <div key={r.id} className="reply-thread">
              <CommentCard comment={r} voted={votedIds.has(r.id)} />
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function CommentCard({
  comment,
  voted,
  onReply,
}: {
  comment: Comment
  voted: boolean
  onReply?: () => void
}) {
  return (
    <div className="card comment-card">
      <div className="comment-body">{comment.body}</div>
      <div className="meta comment-actions">
        <VoteButton score={comment.score ?? 0} voted={voted} commentId={comment.id} />
        <span>by {comment.profiles?.github_username ?? 'unknown'}</span>
        <span>{new Date(comment.created_at).toLocaleString()}</span>
        {onReply && (
          <button className="secondary" onClick={onReply}>
            reply
          </button>
        )}
      </div>
    </div>
  )
}

function CommentForm({
  postId,
  parentId,
  onDone,
}: {
  postId: string
  parentId: string | null
  onDone: () => void
}) {
  const { user } = useAuth()
  const [body, setBody] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!user || !body.trim()) return
    setBusy(true)
    setError(null)
    try {
      await createComment(postId, user.id, body.trim(), parentId)
      setBody('')
      onDone()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="card composer">
      <textarea
        placeholder={parentId ? 'write a reply…' : 'write a comment…'}
        rows={3}
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />
      {error && <div className="error">{error}</div>}
      <div>
        <button disabled={busy} type="submit">
          {parentId ? 'reply' : 'comment'}
        </button>
      </div>
    </form>
  )
}
