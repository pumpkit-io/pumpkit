import { Route } from 'react-router-dom';
import type { OperatorDetails } from '@/lib/instance';
import { LEGAL_DOCUMENTS } from './documents';
import { LegalPage } from './LegalPage';

/**
 * One public route per legal document, outside the signed-in layout. The documents are the
 * hosted Instance's, so an Instance without Operator details registers none (ADR 0011).
 */
export function legalRoutes(operator: OperatorDetails | null) {
  if (!operator) return [];
  return LEGAL_DOCUMENTS.map((doc) => (
    <Route key={doc.path} path={doc.path} element={<LegalPage document={doc} />} />
  ));
}
