import { Route, Routes } from 'react-router-dom'
import { Topbar } from './components/Topbar'
import { Home } from './pages/Home'
import { CategoryPage } from './pages/CategoryPage'
import { PostDetail } from './pages/PostDetail'

export default function App() {
  return (
    <div className="wrap">
      <Topbar />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/c/:slug" element={<CategoryPage />} />
        <Route path="/p/:postId" element={<PostDetail />} />
      </Routes>
      <div className="footer">
        HackMate Community · <a href="../">back to hackmate</a>
      </div>
    </div>
  )
}
