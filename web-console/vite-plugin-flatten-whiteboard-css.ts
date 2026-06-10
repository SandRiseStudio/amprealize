/**
 * Post-processes extracted tldraw CSS chunks (`WhiteboardCanvas-*.css` or legacy `whiteboard-vendor*.css`)
 * so shipped CSS follows the product rule: no drop-shadow stacks, no linear-gradient fills.
 *
 * Theme inset hairlines on controls are preserved where they are not `var(--tl-shadow-*)`.
 */
import type { Plugin } from 'vite';

function replaceLinearGradients(css: string): string {
  const needle = 'linear-gradient(';
  let result = '';
  let i = 0;
  while (i < css.length) {
    const idx = css.indexOf(needle, i);
    if (idx === -1) {
      result += css.slice(i);
      break;
    }
    result += css.slice(i, idx);
    let depth = 0;
    let j = idx + needle.length;
    for (; j < css.length; j++) {
      const c = css[j];
      if (c === '(') {
        depth += 1;
      } else if (c === ')') {
        if (depth === 0) {
          j += 1;
          break;
        }
        depth -= 1;
      }
    }
    const inner = css.slice(idx + needle.length, j - 1);
    result += flatColorFromGradientArgs(inner);
    i = j;
  }
  return result;
}

function flatColorFromGradientArgs(inner: string): string {
  if (inner.includes('tl-color-panel')) {
    return 'var(--tl-color-panel)';
  }
  if (inner.includes('tl-color-muted-2')) {
    return 'var(--tl-color-muted-2)';
  }
  return 'var(--tl-color-muted-2)';
}

function stripInsetHairlineShadows(css: string): string {
  return (
    css
      .replace(
        /box-shadow:inset 0px 0px 0px 1px var\(--tl-color-divider\);/g,
        'outline:1px solid var(--tl-color-divider);outline-offset:-1px;box-shadow:none;',
      )
      .replace(
        /box-shadow:inset 0px 0px 0px 1\.5px var\(--tl-color-selected\);/g,
        'outline:1.5px solid var(--tl-color-selected);outline-offset:-1px;box-shadow:none;',
      )
      .replace(
        /box-shadow:inset 0px 0px 0px 2px var\(--tl-color-text-1\);/g,
        'outline:2px solid var(--tl-color-text-1);outline-offset:-1px;box-shadow:none;',
      )
      .replace(
        /box-shadow:inset 0px 0px 0px 2px var\(--tl-color-text-1\),var\(--tl-shadow-1\)\}/g,
        'outline:2px solid var(--tl-color-text-1);outline-offset:-1px;box-shadow:none}',
      )
      .replace(
        /box-shadow:inset 0px 0px 0px 2px var\(--tl-color-text-1\), var\(--tl-shadow-1\)\}/g,
        'outline:2px solid var(--tl-color-text-1);outline-offset:-1px;box-shadow:none}',
      )
  );
}

function flattenTldrawVendorCss(css: string): string {
  let out = css;
  for (const n of [1, 2, 3, 4] as const) {
    out = out.replace(new RegExp(`--tl-shadow-${n}:[\\s\\S]*?;`, 'g'), `--tl-shadow-${n}: none;`);
  }
  out = replaceLinearGradients(out);
  out = stripInsetHairlineShadows(out);
  out = out.replace(/box-shadow:var\(--tl-shadow-[1-4]\)/g, 'box-shadow:none');
  return out;
}

export function flattenWhiteboardVendorCssPlugin(): Plugin {
  return {
    name: 'amprealize:flatten-whiteboard-vendor-css',
    generateBundle(_options, bundle) {
      for (const chunk of Object.values(bundle)) {
        if (chunk.type !== 'asset') continue;
        if (typeof chunk.source !== 'string') continue;
        if (!chunk.fileName.endsWith('.css')) continue;
        if (!chunk.fileName.includes('whiteboard-vendor') && !chunk.fileName.includes('WhiteboardCanvas'))
          continue;
        chunk.source = flattenTldrawVendorCss(chunk.source);
      }
    },
  };
}
