import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { BrowserRouter, Link, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { ConfirmLeavingNavigation } from './ConfirmLeavingNavigation';
import { useConfirmLeaving } from './useConfirmLeaving';

const MESSAGE = 'Still uploading. Leave anyway?';

function Uploading() {
  useConfirmLeaving(true, MESSAGE);
  const navigate = useNavigate();
  return (
    <>
      <Link to="/elsewhere">Elsewhere</Link>
      <button onClick={() => navigate('/elsewhere')}>Go elsewhere</button>
    </>
  );
}

function Where() {
  return <output aria-label="Path">{useLocation().pathname}</output>;
}

function renderApp() {
  return render(
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <ConfirmLeavingNavigation>
        <Routes>
          <Route path="/start" element={<Link to="/uploading">Upload</Link>} />
          <Route path="/uploading" element={<Uploading />} />
          <Route path="/elsewhere" element={<p>Elsewhere page</p>} />
        </Routes>
        <Where />
      </ConfirmLeavingNavigation>
    </BrowserRouter>,
  );
}

const path = () => screen.getByRole('status', { name: 'Path' }).textContent;

describe('ConfirmLeavingNavigation', () => {
  let confirm: MockInstance<(message?: string) => boolean>;

  beforeEach(async () => {
    window.history.replaceState(null, '', '/start');
    confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderApp();
    fireEvent.click(screen.getByRole('link', { name: 'Upload' }));
    await waitFor(() => expect(path()).toBe('/uploading'));
  });

  afterEach(() => confirm.mockRestore());

  it('asks before a link or a navigate() leaves, and stays when declined', () => {
    fireEvent.click(screen.getByRole('link', { name: 'Elsewhere' }));
    fireEvent.click(screen.getByRole('button', { name: 'Go elsewhere' }));

    expect(confirm).toHaveBeenCalledTimes(2);
    expect(confirm).toHaveBeenCalledWith(MESSAGE);
    expect(path()).toBe('/uploading');
  });

  it('leaves once the User confirms', async () => {
    confirm.mockReturnValue(true);

    fireEvent.click(screen.getByRole('button', { name: 'Go elsewhere' }));

    await waitFor(() => expect(path()).toBe('/elsewhere'));
  });

  it('turns the browser back button around when declined', async () => {
    await act(async () => {
      window.history.back();
      await waitFor(() => expect(confirm).toHaveBeenCalledWith(MESSAGE));
    });

    await waitFor(() => expect(window.location.pathname).toBe('/uploading'));
    expect(path()).toBe('/uploading');
    expect(screen.getByRole('link', { name: 'Elsewhere' })).toBeInTheDocument();
    expect(confirm).toHaveBeenCalledTimes(1);
  });

  it('goes back when the User confirms', async () => {
    confirm.mockReturnValue(true);

    act(() => window.history.back());

    await waitFor(() => expect(path()).toBe('/start'));
    expect(confirm).toHaveBeenCalledTimes(1);
  });
});
