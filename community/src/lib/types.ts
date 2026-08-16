export interface Profile {
  id: string
  github_username: string
  avatar_url: string | null
  created_at: string
}

export interface Category {
  id: string
  slug: string
  name: string
  description: string
  sort_order: number
}

export interface Post {
  id: string
  category_id: string
  author_id: string
  title: string
  body: string
  created_at: string
  profiles?: Profile
  score?: number
  comment_count?: number
}

export interface Comment {
  id: string
  post_id: string
  author_id: string
  parent_id: string | null
  body: string
  created_at: string
  profiles?: Profile
  score?: number
}
