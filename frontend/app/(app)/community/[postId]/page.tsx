'use client';

import { useParams } from 'next/navigation';

import PostDetailPage from '@/components/community/PostDetailPage';

export default function CommunityPostRoute() {
  const params = useParams<{ postId: string }>();
  return <PostDetailPage postId={params.postId} />;
}
