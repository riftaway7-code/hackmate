import { Route, Routes } from 'react-router-dom'
import { Sidebar } from './components/Sidebar'
import { Topbar } from './components/Topbar'
import { Home } from './pages/Home'
import { CategoryPage } from './pages/CategoryPage'
import { PostDetail } from './pages/PostDetail'

export default function App() {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-main">
        <Topbar />
        <main className="content-area">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/c/:slug" element={<CategoryPage />} />
            <Route path="/p/:postId" element={<PostDetail />} />
          </Routes>
        </main>
        <div className="footer">HackMate Community · <a href="../">back to hackmate</a></div>
      </div>
    </div>
  )
}
