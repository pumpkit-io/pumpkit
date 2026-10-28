import { Navigate, Route } from 'react-router-dom';
import { NewPost } from './NewPost';
import { Persona } from './Persona';
import { PostPage } from './PostPage';
import { Scheduled } from './Scheduled';
import { Settings } from './Settings';

/** The pages inside AppLayout, for App and for the page tests, which render the same tree. */
export function signedInRoutes() {
  return (
    <>
      <Route path="/new" element={<NewPost />} />
      <Route path="/posts" element={<Scheduled />} />
      {/* The Post page's breadcrumb links to these tabs; until the Posts page has them, each shows the old list. */}
      {['scheduled', 'drafts', 'published', 'failed'].map((tab) => (
        <Route key={tab} path={`/posts/${tab}`} element={<Scheduled />} />
      ))}
      <Route path="/posts/:id" element={<PostPage />} />
      <Route path="/persona" element={<Persona />} />
      <Route path="/settings" element={<Settings />} />
      <Route path="/home" element={<Navigate to="/new" replace />} />
    </>
  );
}
