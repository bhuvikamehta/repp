import { render, screen } from '@testing-library/react';
import { act } from 'react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import Terminal, { LogEntry } from '../../components/Terminal';

function makeLogger() {
  let listener: ((entry: LogEntry) => void) | null = null;
  return {
    logger: {
      subscribe: vi.fn((cb: (entry: LogEntry) => void) => {
        listener = cb;
        return vi.fn();
      }),
    },
    emit(entry: LogEntry) {
      listener?.(entry);
    },
  };
}

describe('Terminal unit tests', () => {
  it('does not render when closed', () => {
    const { logger } = makeLogger();

    render(<Terminal isOpen={false} onClose={vi.fn()} logger={logger} />);

    expect(screen.queryByText(/System Telemetry Log/i)).not.toBeInTheDocument();
  });

  it('renders emitted logs and payload details', async () => {
    const source = makeLogger();
    render(<Terminal isOpen onClose={vi.fn()} logger={source.logger} />);

    act(() => {
      source.emit({
        id: '1',
        timestamp: '10:00',
        type: 'api',
        message: 'Called endpoint',
        payload: { status: 200 },
      });
    });

    expect(await screen.findByText('Called endpoint')).toBeInTheDocument();
    expect(screen.getByText('[API]')).toBeInTheDocument();
    expect(screen.getByText(/View Payload/i)).toBeInTheDocument();
  });

  it('clears logs when Clear is clicked', async () => {
    const user = userEvent.setup();
    const source = makeLogger();
    render(<Terminal isOpen onClose={vi.fn()} logger={source.logger} />);
    act(() => {
      source.emit({ id: '1', timestamp: '10:00', type: 'warn', message: 'Warning' });
    });

    await screen.findByText('Warning');
    await user.click(screen.getByRole('button', { name: /clear/i }));

    expect(screen.queryByText('Warning')).not.toBeInTheDocument();
    expect(screen.getByText(/No activity recorded/i)).toBeInTheDocument();
  });

  it('calls onClose when close button is clicked', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const { logger } = makeLogger();
    render(<Terminal isOpen onClose={onClose} logger={logger} />);

    const buttons = screen.getAllByRole('button');
    await user.click(buttons[1]);

    expect(onClose).toHaveBeenCalled();
  });
});
