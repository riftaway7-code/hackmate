import { supabase } from './supabase'
import type { Category, Comment, Post } from './types'

export async function fetchCategories(): Promise<Category[]> {
  const { data, error } = await supabase.from('categories').select('*').order('sort_order')
  if (error) throw error
  return data
}

export async function fetchCategory(slug: string): Promise<Category | null> {
  const { data, error } = await supabase.from('categories').select('*').eq('slug', slug).maybeSingle()
  if (error) throw error
  return data
}

export async function fetchPosts(categoryId: string): Promise<Post[]> {
  const { data: posts, error } = await supabase
    .from('posts')
    .select('*, profiles(*)')
    .eq('category_id', categoryId)
    .order('created_at', { ascending: false })
  if (error) throw error
  if (!posts.length) return posts

  const ids = posts.map((p) => p.id)
  const [{ data: scores }, { data: comments }] = await Promise.all([
    supabase.from('post_scores').select('*').in('post_id', ids),
    supabase.from('comments').select('id, post_id').in('post_id', ids),
  ])

  const scoreMap = new Map((scores ?? []).map((s) => [s.post_id, s.score]))
  const countMap = new Map<string, number>()
  for (const c of comments ?? []) countMap.set(c.post_id, (countMap.get(c.post_id) ?? 0) + 1)

  return posts.map((p) => ({
    ...p,
    score: scoreMap.get(p.id) ?? 0,
    comment_count: countMap.get(p.id) ?? 0,
  }))
}

export async function fetchPost(postId: string): Promise<Post | null> {
  const { data: post, error } = await supabase
    .from('posts')
    .select('*, profiles(*)')
    .eq('id', postId)
    .maybeSingle()
  if (error) throw error
  if (!post) return null

  const { data: scores } = await supabase.from('post_scores').select('*').eq('post_id', postId).maybeSingle()
  return { ...post, score: scores?.score ?? 0 }
}

export async function fetchComments(postId: string): Promise<Comment[]> {
  const { data: comments, error } = await supabase
    .from('comments')
    .select('*, profiles(*)')
    .eq('post_id', postId)
    .order('created_at')
  if (error) throw error
  if (!comments.length) return comments

  const ids = comments.map((c) => c.id)
  const { data: scores } = await supabase.from('comment_scores').select('*').in('comment_id', ids)
  const scoreMap = new Map((scores ?? []).map((s) => [s.comment_id, s.score]))

  return comments.map((c) => ({ ...c, score: scoreMap.get(c.id) ?? 0 }))
}

export async function fetchMyVotes(userId: string, postIds: string[], commentIds: string[]) {
  const { data, error } = await supabase
    .from('votes')
    .select('post_id, comment_id')
    .eq('user_id', userId)
    .or(
      [
        postIds.length ? `post_id.in.(${postIds.join(',')})` : null,
        commentIds.length ? `comment_id.in.(${commentIds.join(',')})` : null,
      ]
        .filter(Boolean)
        .join(',')
    )
  if (error) throw error
  return new Set((data ?? []).map((v) => v.post_id ?? v.comment_id))
}

export async function createPost(categoryId: string, authorId: string, title: string, body: string) {
  const { data, error } = await supabase
    .from('posts')
    .insert({ category_id: categoryId, author_id: authorId, title, body })
    .select()
    .single()
  if (error) throw error
  return data
}

export async function createComment(
  postId: string,
  authorId: string,
  body: string,
  parentId: string | null
) {
  const { data, error } = await supabase
    .from('comments')
    .insert({ post_id: postId, author_id: authorId, body, parent_id: parentId })
    .select()
    .single()
  if (error) throw error
  return data
}

export async function toggleVote(
  userId: string,
  target: { postId?: string; commentId?: string },
  currentlyVoted: boolean
) {
  if (currentlyVoted) {
    const { error } = await supabase
      .from('votes')
      .delete()
      .eq('user_id', userId)
      .eq(target.postId ? 'post_id' : 'comment_id', target.postId ?? target.commentId)
    if (error) throw error
  } else {
    const { error } = await supabase
      .from('votes')
      .insert({ user_id: userId, post_id: target.postId ?? null, comment_id: target.commentId ?? null })
    if (error) throw error
  }
}
