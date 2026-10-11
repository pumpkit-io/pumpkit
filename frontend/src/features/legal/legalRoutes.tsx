import { Route } from 'react-router-dom';
import { LEGAL_DOCUMENTS } from './documents';
import { LegalPage } from './LegalPage';

/** One public route per legal document, outside the signed-in layout. */
export const legalRoutes = LEGAL_DOCUMENTS.map((doc) => (
  <Route key={doc.path} path={doc.path} element={<LegalPage document={doc} />} />
));
