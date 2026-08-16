import { Link } from 'react-router-dom'
import { useAuth } from '../lib/AuthContext'

export function Topbar() {
  const { user, profile, loading, signInWithGithub, signOut } = useAuth()

  return (
    <div className="topbar">
      <Link to="/" className="brand">HACKMATE // COMMUNITY</Link>
      {loading ? null : user ? (
        <div className="meta" style={{ display: 'flex', alignItems: 'center', gap: '0.8rem' }}>
          <span>{profile?.github_username ?? user.email}</span>
          <button className="secondary" onClick={signOut}>sign out</button>
        </div>
      ) : (
        <button onClick={signInWithGithub}>sign in with github</button>
      )}
    </div>
  )
}
