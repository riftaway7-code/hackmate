import { useState } from 'react'
import { useAuth } from '../lib/AuthContext'
import { toggleVote } from '../lib/queries'

export function VoteButton({
  score,
  voted,
  postId,
  commentId,
}: {
  score: number
  voted: boolean
  postId?: string
  commentId?: string
}) {
  const { user, signInWithGithub } = useAuth()
  const [localScore, setLocalScore] = useState(score)
  const [localVoted, setLocalVoted] = useState(voted)
  const [busy, setBusy] = useState(false)

  async function handleClick() {
    if (!user) {
      await signInWithGithub()
      return
    }
    if (busy) return
    setBusy(true)
    const next = !localVoted
    setLocalVoted(next)
    setLocalScore((s) => s + (next ? 1 : -1))
    try {
      await toggleVote(user.id, { postId, commentId }, localVoted)
    } catch {
      setLocalVoted(!next)
      setLocalScore((s) => s + (next ? -1 : 1))
    } finally {
      setBusy(false)
    }
  }

  return (
    <button className={`vote-btn${localVoted ? ' voted' : ''}`} onClick={handleClick} disabled={busy}>
      ▲ {localScore}
    </button>
  )
}
