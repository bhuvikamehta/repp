import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import LoginView from '../../views/LoginView';
import SignupView from '../../views/SignupView';
import CreateOrgView from '../../views/CreateOrgView';

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  signInWithPassword: vi.fn(),
  signInWithOAuth: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mocks.navigate,
  };
});

vi.mock('../../contexts/AuthContext', () => ({
  supabase: {
    auth: {
      signInWithPassword: mocks.signInWithPassword,
      signInWithOAuth: mocks.signInWithOAuth,
    },
  },
}));

function renderWithRouter(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe('Auth view unit tests', () => {
  beforeEach(() => {
    mocks.navigate.mockReset();
    mocks.signInWithPassword.mockReset();
    mocks.signInWithOAuth.mockReset();
    vi.stubGlobal('fetch', vi.fn());
  });

  it('logs in valid email/password and navigates home', async () => {
    const user = userEvent.setup();
    mocks.signInWithPassword.mockResolvedValue({ error: null });
    renderWithRouter(<LoginView />);

    await user.type(screen.getByPlaceholderText('agent@reporting-agent.com'), 'agent@test.com');
    await user.type(screen.getByPlaceholderText('••••••••'), 'password123');
    await user.click(screen.getByRole('button', { name: /log in/i }));

    await waitFor(() => expect(mocks.signInWithPassword).toHaveBeenCalledWith({
      email: 'agent@test.com',
      password: 'password123',
    }));
    expect(mocks.navigate).toHaveBeenCalledWith('/');
  });

  it('shows login error for invalid credentials', async () => {
    const user = userEvent.setup();
    mocks.signInWithPassword.mockResolvedValue({ error: { message: 'Invalid login' } });
    renderWithRouter(<LoginView />);

    await user.type(screen.getByPlaceholderText('agent@reporting-agent.com'), 'bad@test.com');
    await user.type(screen.getByPlaceholderText('••••••••'), 'wrongpass');
    await user.click(screen.getByRole('button', { name: /log in/i }));

    expect(await screen.findByText('Invalid login')).toBeInTheDocument();
  });

  it('submits signup and renders success for valid org code', async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: async () => ({ message: 'Signup successful' }),
    } as Response);
    renderWithRouter(<SignupView />);

    await user.type(screen.getByPlaceholderText('e.g. A1B2C3D4'), 'ABC12345');
    await user.type(screen.getByPlaceholderText('agent@reporting-agent.com'), 'member@test.com');
    await user.type(screen.getByPlaceholderText('••••••••'), 'password123');
    await user.click(screen.getByRole('button', { name: /sign up/i }));

    expect(await screen.findByText(/Account successfully created/i)).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/auth/signup',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ email: 'member@test.com', password: 'password123', org_code: 'ABC12345' }),
      }),
    );
  });

  it('shows signup error for invalid org code', async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'Invalid organization code' }),
    } as Response);
    renderWithRouter(<SignupView />);

    await user.type(screen.getByPlaceholderText('e.g. A1B2C3D4'), 'BAD');
    await user.type(screen.getByPlaceholderText('agent@reporting-agent.com'), 'member@test.com');
    await user.type(screen.getByPlaceholderText('••••••••'), 'password123');
    await user.click(screen.getByRole('button', { name: /sign up/i }));

    expect(await screen.findByText('Invalid organization code')).toBeInTheDocument();
  });

  it('creates organization and displays invite code', async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: async () => ({ organization: { name: 'Acme', code: 'A1B2C3D4' } }),
    } as Response);
    renderWithRouter(<CreateOrgView />);

    await user.type(screen.getByPlaceholderText('e.g. Acme Corp'), 'Acme');
    await user.type(screen.getByPlaceholderText('admin@acmecorp.com'), 'admin@test.com');
    await user.type(screen.getByPlaceholderText('••••••••'), 'password123');
    await user.click(screen.getByRole('button', { name: /create organization/i }));

    expect(await screen.findByText('A1B2C3D4')).toBeInTheDocument();
  });
});
