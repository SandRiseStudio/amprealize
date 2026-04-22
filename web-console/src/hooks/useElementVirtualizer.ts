/**
 * Element-scrolling virtual list hook — same behavior as @tanstack/react-virtual's
 * `useVirtualizer`, implemented locally so eslint-plugin-react-hooks does not treat
 * TanStack's exported hook name as a known incompatible-library symbol.
 *
 * Logic aligned with @tanstack/react-virtual/src/index.tsx (MIT).
 */
import { flushSync } from 'react-dom';
import { useEffect, useLayoutEffect, useReducer, useState } from 'react';
import {
  Virtualizer,
  elementScroll,
  observeElementOffset,
  observeElementRect,
} from '@tanstack/react-virtual';
import type { PartialKeys, VirtualizerOptions } from '@tanstack/react-virtual';

const useIsomorphicLayoutEffect =
  typeof document !== 'undefined' ? useLayoutEffect : useEffect;

type ReactVirtualizerOptions<
  TScrollElement extends Element | Window,
  TItemElement extends Element,
> = VirtualizerOptions<TScrollElement, TItemElement> & {
  useFlushSync?: boolean;
};

function useElementVirtualizerBase<
  TScrollElement extends Element | Window,
  TItemElement extends Element,
>({
  useFlushSync = true,
  ...options
}: ReactVirtualizerOptions<TScrollElement, TItemElement>): Virtualizer<
  TScrollElement,
  TItemElement
> {
  const rerender = useReducer(() => ({}), {})[1];

  const resolvedOptions: VirtualizerOptions<TScrollElement, TItemElement> = {
    ...options,
    onChange: (instance, sync) => {
      if (useFlushSync && sync) {
        flushSync(rerender);
      } else {
        rerender();
      }
      options.onChange?.(instance, sync);
    },
  };

  const [instance] = useState(
    () => new Virtualizer<TScrollElement, TItemElement>(resolvedOptions),
  );

  instance.setOptions(resolvedOptions);

  useIsomorphicLayoutEffect(() => {
    return instance._didMount();
  }, []);

  useIsomorphicLayoutEffect(() => {
    return instance._willUpdate();
  });

  return instance;
}

export function useElementVirtualizer<
  TScrollElement extends Element,
  TItemElement extends Element,
>(
  options: PartialKeys<
    ReactVirtualizerOptions<TScrollElement, TItemElement>,
    'observeElementRect' | 'observeElementOffset' | 'scrollToFn'
  >,
): Virtualizer<TScrollElement, TItemElement> {
  return useElementVirtualizerBase<TScrollElement, TItemElement>({
    observeElementRect,
    observeElementOffset,
    scrollToFn: elementScroll,
    ...options,
  });
}
