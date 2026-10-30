import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { HoverLabels } from '@/features/posts/HoverLabel';
import { UndoRedo } from './UndoRedo';

describe('UndoRedo', () => {
  it.each([
    ['Undo', 'Undo edit'],
    ['Redo', 'Redo edit'],
  ])('labels %s on hover', async (button, label) => {
    render(
      <HoverLabels>
        <UndoRedo onUndo={() => {}} onRedo={() => {}} />
      </HoverLabels>,
    );

    fireEvent.pointerMove(screen.getByRole('button', { name: button }), { pointerType: 'mouse' });

    expect(await screen.findByRole('tooltip')).toHaveTextContent(label);
  });
});
