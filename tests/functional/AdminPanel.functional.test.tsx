import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AdminPanelView from '../../views/AdminPanelView';

const authMocks = vi.hoisted(() => ({
  signOut: vi.fn(),
  session: { access_token: 'token_123' },
  profile: { id: 'admin_1', email: 'admin@test.com', organization_id: 'org_1', role: 'admin' },
}));

vi.mock('../../contexts/AuthContext', () => ({
  supabase: {
    auth: { signOut: authMocks.signOut },
  },
  useAuth: () => ({
    session: authMocks.session,
    profile: authMocks.profile,
  }),
}));

function renderAdmin() {
  return render(
    <MemoryRouter>
      <AdminPanelView />
    </MemoryRouter>,
  );
}

describe('AdminPanel functional component tests', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/api/org/members')) {
        return {
          ok: true,
          json: async () => ({
            members: [
              { id: 'admin_1', email: 'admin@test.com', role: 'admin', created_at: '2026-01-01T00:00:00' },
              { id: 'member_1', email: 'member@test.com', role: 'member', created_at: '2026-01-02T00:00:00' },
            ],
            organization: { name: 'Acme', code: 'ABC12345' },
          }),
        } as Response;
      }
      if (url.endsWith('/api/rag/documents') && (!init || init.method === undefined)) {
        return {
          ok: true,
          json: async () => ({
            documents: [
              { id: 'doc_1', file_name: 'standards.txt', file_type: 'txt', file_size: 100, chunk_count: 2, created_at: '2026-01-01T00:00:00' },
            ],
          }),
        } as Response;
      }
      if (url.endsWith('/api/rag/documents') && init?.method === 'POST') {
        return { ok: true, json: async () => ({ chunk_count: 3 }) } as Response;
      }
      if (url.includes('/api/rag/documents/') && init?.method === 'DELETE') {
        return { ok: true, json: async () => ({ message: 'deleted' }) } as Response;
      }
      if (url.includes('/api/org/members/') && init?.method === 'PUT') {
        return { ok: true, json: async () => ({ message: 'updated' }) } as Response;
      }
      return { ok: true, json: async () => ({}) } as Response;
    }));
  });

  it('loads organization, members, and knowledge-base documents', async () => {
    renderAdmin();

    expect(await screen.findByText('Acme')).toBeInTheDocument();
    expect(screen.getByText('ABC12345')).toBeInTheDocument();
    expect(screen.getByText('member@test.com')).toBeInTheDocument();
    expect(screen.getByText('standards.txt')).toBeInTheDocument();
  });

  it('rejects unsupported admin upload extension', async () => {
    const user = userEvent.setup({ applyAccept: false });
    renderAdmin();
    await screen.findByText('Acme');
    const file = new File(['x'], 'bad.exe', { type: 'application/octet-stream' });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;

    await user.upload(input, file);

    expect(await screen.findByText(/Unsupported file type/i)).toBeInTheDocument();
  });

  it('uploads a valid knowledge-base document', async () => {
    const user = userEvent.setup();
    renderAdmin();
    await screen.findByText('Acme');
    const file = new File(['standards'], 'new-standards.txt', { type: 'text/plain' });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;

    await user.upload(input, file);

    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/rag/documents',
      expect.objectContaining({ method: 'POST' }),
    ));
  });

  it('deletes a knowledge-base document after confirmation', async () => {
    const user = userEvent.setup();
    renderAdmin();

    await screen.findByText('standards.txt');
    const removeButtons = screen.getAllByRole('button', { name: /remove/i });
    await user.click(removeButtons[removeButtons.length - 1]);

    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/rag/documents/doc_1',
      expect.objectContaining({ method: 'DELETE' }),
    ));
  });
});
