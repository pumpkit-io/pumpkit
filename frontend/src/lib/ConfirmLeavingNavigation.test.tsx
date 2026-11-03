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
      <button onClick={() => navigate(-1)}>Go back</button>
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

  it('asks once before navigate(-1) goes back, and stays when declined', async () => {
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Go back' }));
      await waitFor(() => expect(confirm).toHaveBeenCalled());
    });

    await waitFor(() => expect(window.location.pathname).toBe('/uploading'));
    expect(path()).toBe('/uploading');
    expect(confirm).toHaveBeenCalledTimes(1);
  });

  it('asks once before navigate(-1) goes back, and goes when confirmed', async () => {
    confirm.mockReturnValue(true);

    act(() => fireEvent.click(screen.getByRole('button', { name: 'Go back' })));

    await waitFor(() => expect(path()).toBe('/start'));
    expect(confirm).toHaveBeenCalledTimes(1);
  });

  describe('popstate', () => {
    const shown = () => (window.history.state as { idx: number }).idx;
    const pop = (idx: number) =>
      act(() => {
        window.dispatchEvent(new PopStateEvent('popstate', { state: { idx } }));
      });

    it('lets a pop onto the entry shown through without asking or moving', () => {
      const go = vi.spyOn(window.history, 'go');

      pop(shown());

      expect(confirm).not.toHaveBeenCalled();
      expect(go).not.toHaveBeenCalled();
      go.mockRestore();
    });

    it('still asks on the next pop when turning back a declined one moved nowhere', () => {
      const go = vi.spyOn(window.history, 'go').mockImplementation(() => {});
      const before = shown() - 1;

      pop(before);
      pop(before);

      expect(confirm).toHaveBeenCalledTimes(2);
      expect(go).toHaveBeenNthCalledWith(2, 1);
      go.mockRestore();
    });
  });
});
