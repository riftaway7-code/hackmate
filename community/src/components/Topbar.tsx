import { Link } from 'react-router-dom'
import { useAuth } from '../lib/AuthContext'

export function Topbar() {
  const { user, profile, loading, signInWithGithub, signOut } = useAuth()
  const identity = profile?.github_username ?? user?.email ?? '?'

  return (
    <header className="topbar">
      <Link to="/" className="brand"><span className="brand-status" /><span>HackMate</span><span className="brand-section">Community</span></Link>
      {loading ? null : user ? (
        <div className="user-menu">
          <div className="avatar">{identity.slice(0, 1).toUpperCase()}</div>
          <div className="user-copy"><strong>{identity}</strong><span>online</span></div>
          <button className="icon-button" onClick={signOut} title="Sign out">↪</button>
        </div>
      ) : <button className="github-button" onClick={signInWithGithub}>Sign in with GitHub</button>}
    </header>
  )
}
