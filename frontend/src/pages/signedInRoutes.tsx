import { Navigate, Route } from 'react-router-dom';
import { STATUS_TAB, TAB_ORDER } from '@/features/posts/postStatus';
import { NewPost } from './NewPost';
import { Persona } from './Persona';
import { PostPage } from './PostPage';
import { Posts } from './Posts';
import { Settings } from './Settings';

/** The pages inside AppLayout, for App and for the page tests, which render the same tree. */
export function signedInRoutes() {
  return (
    <>
      <Route path="/new" element={<NewPost />} />
      <Route path="/posts" element={<Navigate to={STATUS_TAB.scheduled.path} replace />} />
      {TAB_ORDER.map((status) => (
        <Route key={status} path={STATUS_TAB[status].path} element={<Posts status={status} />} />
      ))}
      <Route path="/posts/:id" element={<PostPage />} />
      <Route path="/persona" element={<Persona />} />
      <Route path="/settings" element={<Settings />} />
      <Route path="/home" element={<Navigate to="/new" replace />} />
      <Route path="/scheduled" element={<Navigate to={STATUS_TAB.scheduled.path} replace />} />
    </>
  );
}
