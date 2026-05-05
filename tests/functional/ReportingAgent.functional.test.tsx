import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ReportingAgent from '../../components/ReportingAgent';

const authMocks = vi.hoisted(() => ({
  getSession: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock('../../contexts/AuthContext', () => ({
  supabase: {
    auth: {
      getSession: authMocks.getSession,
      signOut: authMocks.signOut,
    },
  },
  useAuth: () => ({
    profile: { id: 'user_1', email: 'user@test.com', organization_id: 'org_1', role: 'admin' },
  }),
}));

vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn(async () => ({ svg: '<svg data-testid="diagram"></svg>' })),
  },
}));

function renderAgent() {
  return render(
    <MemoryRouter>
      <ReportingAgent />
    </MemoryRouter>,
  );
}

const completedResponse = {
  thread_id: 'thread_1',
  status: 'completed',
  memory: 'Use concise summaries.',
  intent: {
    request_id: 'req_test',
    task_type: 'report',
    input_mode: 'text_only',
    user_prompt: 'Create a QBR.',
    detected_category: 'Financial Report',
    document_metadata: { attached: false, file_type: 'none', file_name: null },
    content_scope: 'QBR',
    confidence_score: 0.9,
    is_ambiguous: false,
    is_supported: true,
    constraints: { hallucination_allowed: false, output_structure_required: true },
    timestamp: '2026-01-01T00:00:00',
  },
  report: {
    request_id: 'req_test',
    status: 'completed',
    source_type: 'text',
    confidence_level: 'high',
    generated_at: '2026-01-01T00:00:00',
    report: {
      hero_image_keyword: 'finance',
      executive_summary: '[INTERNAL] Revenue increased.',
      highlights: ['12% growth QoQ'],
      risks_and_blockers: ['[LOW] Data delay. Impact minimal. Mitigation refresh. Owner Ops.'],
      actions_required: ['ACTION: Validate data | Owner: Analytics | Timeline: 1 week'],
      evidence_links: ['[SOURCE: Internal - Q1]'],
      diagrams: [{ title: 'Flow', mermaid_code: 'flowchart TD\n  A --> B' }],
      additional_sections: [{ title: 'Revenue', content: 'Revenue details.', image_keyword: '' }],
    },
  },
};

describe('ReportingAgent functional component tests', () => {
  beforeEach(() => {
    authMocks.getSession.mockResolvedValue({ data: { session: { access_token: 'token_123' } } });
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.includes('/preferences/')) {
        return { ok: true, json: async () => ({ preference_rules: 'Default test memory.' }) };
      }
      return { ok: true, json: async () => completedResponse };
    }));
  });

  it('shows invalid prompt error when user submits empty state', async () => {
    const user = userEvent.setup({ applyAccept: false });
    renderAgent();

    await user.click(screen.getByRole('button', { name: /initialize synthesis/i }));

    expect(await screen.findByText(/INVALID_PROMPT Fault/i)).toBeInTheDocument();
    expect(screen.getByText(/Please provide a prompt or a document/i)).toBeInTheDocument();
  });

  it('valid prompt calls agent API and renders report sections', async () => {
    const user = userEvent.setup();
    renderAgent();

    await user.type(screen.getByPlaceholderText(/Describe your reporting goal/i), 'Create a QBR.');
    await user.click(screen.getByRole('button', { name: /initialize synthesis/i }));

    expect(await screen.findByText(/Executive Summary/i)).toBeInTheDocument();
    expect(screen.getByText(/12% growth QoQ/i)).toBeInTheDocument();
    expect(screen.getByText(/Revenue details/i)).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      'http://localhost:8000/agent/run',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer token_123' }),
      }),
    );
  });

  it('renders ambiguity state for low-confidence valid backend response', async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockImplementation(async (url: string) => {
      if (url.includes('/preferences/')) {
        return { ok: true, json: async () => ({ preference_rules: 'Default test memory.' }) } as Response;
      }
      return {
        ok: true,
        json: async () => ({
          ...completedResponse,
          status: 'needs_clarification',
          report: null,
          clarification_question: 'Please clarify the scope.',
        }),
      } as Response;
    });
    renderAgent();

    await user.type(screen.getByPlaceholderText(/Describe your reporting goal/i), 'Analyze.');
    await user.click(screen.getByRole('button', { name: /initialize synthesis/i }));

    expect(await screen.findByText(/Ambiguity Detected/i)).toBeInTheDocument();
    expect(screen.getByText(/Please clarify the scope/i)).toBeInTheDocument();
  });

  it('renders low-signal rejection for invalid document content', async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockImplementation(async (url: string) => {
      if (url.includes('/preferences/')) {
        return { ok: true, json: async () => ({ preference_rules: 'Default test memory.' }) } as Response;
      }
      return {
        ok: true,
        json: async () => ({
          ...completedResponse,
          status: 'rejected_low_signal',
          report: null,
          rejection_reason: 'Low Signal Detected',
        }),
      } as Response;
    });
    renderAgent();

    await user.type(screen.getByPlaceholderText(/Describe your reporting goal/i), 'Create report.');
    await user.click(screen.getByRole('button', { name: /initialize synthesis/i }));

    expect(await screen.findByText(/Insufficient Signal/i)).toBeInTheDocument();
    expect(screen.getByText(/Low Signal Detected/i)).toBeInTheDocument();
  });

  it('rejects unsupported file extension before API call', async () => {
    const user = userEvent.setup({ applyAccept: false });
    renderAgent();
    const file = new File(['bad'], 'malware.exe', { type: 'application/octet-stream' });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;

    await user.upload(input, file);

    expect(await screen.findByText(/INVALID_FORMAT Fault/i)).toBeInTheDocument();
    expect(screen.getByText(/Only .pdf, .txt, and .docx allowed/i)).toBeInTheDocument();
  });
});
