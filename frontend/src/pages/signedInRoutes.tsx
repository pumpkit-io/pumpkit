import { Navigate, Route } from 'react-router-dom';
import { NewPost } from './NewPost';
import { Persona } from './Persona';
import { Scheduled } from './Scheduled';
import { Settings } from './Settings';

/** The pages inside AppLayout, for App and for the page tests, which render the same tree. */
export function signedInRoutes() {
  return (
    <>
      <Route path="/new" element={<NewPost />} />
      <Route path="/posts" element={<Scheduled />} />
      <Route path="/persona" element={<Persona />} />
      <Route path="/settings" element={<Settings />} />
      <Route path="/home" element={<Navigate to="/new" replace />} />
    </>
  );
}
