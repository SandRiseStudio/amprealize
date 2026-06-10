import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RouteMainColumnSkeleton } from '../components/loading/RouteMainColumnSkeleton';

describe('RouteMainColumnSkeleton', () => {
  it('exposes a polite status region and visually hidden loading text', () => {
    render(<RouteMainColumnSkeleton />);

    expect(screen.getByRole('status', { name: /loading page/i })).toBeInTheDocument();
    expect(screen.getByText('Loading page content')).toBeInTheDocument();
  });
});
